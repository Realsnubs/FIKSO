"""Maps, geocoding and ETA behind replaceable adapters (ARCHITECTURE §8, Q-02).

Providers: Google Maps Platform (Geocoding API + Routes API route matrix) or a self-hosted OSRM for routing.
Every call has a timeout; a failing provider opens a short circuit so matching never waits on it
repeatedly, and ETA then falls back to straight-line distance at the configured speed — the source is
always recorded (`routing` / `fallback`). Addresses and coordinates are never logged.
"""

import hashlib
import logging
import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

EARTH_KM = 6371.0088
# Latvia's bounding box: coordinates outside it are rejected as implausible for FIKSO.
LAT_RANGE = (55.6, 58.1)
LON_RANGE = (20.9, 28.3)
# Geocoding results at least this precise are accepted (Google location_type); city-level ones are not.
PRECISE = {"ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine (great-circle) distance; also used in SQL for the work-zone filter."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def in_latvia(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


class ProviderError(Exception):
    """The provider is unreachable, refused the call or answered nonsense (not: "address not found")."""


@dataclass(frozen=True)
class GeoPoint:
    lat: Decimal
    lon: Decimal
    source: str


class Geocoder(Protocol):
    def geocode(self, address: str) -> GeoPoint | None:
        """The point, None when the address cannot be located precisely; ProviderError when the service
        fails."""
        ...


class RoutingProvider(Protocol):
    name: str

    def eta_minutes(
        self, origins: Sequence[tuple[float, float]], destination: tuple[float, float]
    ) -> list[int | None]:
        """Driving minutes from each origin, None for an origin without a route; ProviderError on failure."""
        ...


class Circuit:
    """After a failure the provider is skipped for `cooldown` seconds (fallback is used meanwhile)."""

    def __init__(self, cooldown: float = 60.0) -> None:
        self.cooldown = cooldown
        self._open_until = 0.0
        self._lock = threading.Lock()

    def available(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._open_until

    def fail(self) -> None:
        with self._lock:
            self._open_until = time.monotonic() + self.cooldown

    def reset(self) -> None:
        with self._lock:
            self._open_until = 0.0


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=get_settings().provider_timeout_seconds, transport=transport)


class StubGeocoder:
    """Development only: a stable point in the Riga area derived from the address text. Never real data."""

    def geocode(self, address: str) -> GeoPoint | None:
        digest = hashlib.sha256(address.strip().lower().encode()).digest()
        lat = 56.90 + digest[0] / 255 * 0.10
        lon = 24.00 + digest[1] / 255 * 0.25
        return GeoPoint(Decimal(f"{lat:.6f}"), Decimal(f"{lon:.6f}"), "stub")


class NoGeocoder:
    def geocode(self, address: str) -> GeoPoint | None:
        raise ProviderError("no geocoder configured")


class GoogleGeocoder:
    URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    def geocode(self, address: str) -> GeoPoint | None:
        params = {
            "address": address,
            "components": "country:LV",
            "language": "lv",
            "region": "lv",
            "key": self.api_key,
        }
        try:
            with _client(self.transport) as client:
                response = client.get(self.URL, params=params)
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"geocoding request failed: {type(exc).__name__}") from exc
        status = data.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK" or response.status_code != 200:
            raise ProviderError(f"geocoding status {status}")
        for result in data.get("results", []):
            geometry = result.get("geometry", {})
            if geometry.get("location_type") not in PRECISE:
                continue
            location = geometry.get("location", {})
            lat, lon = float(location["lat"]), float(location["lng"])
            if in_latvia(lat, lon):
                return GeoPoint(Decimal(f"{lat:.6f}"), Decimal(f"{lon:.6f}"), "google")
        return None


class NoRouting:
    name = "none"

    def eta_minutes(
        self, origins: Sequence[tuple[float, float]], destination: tuple[float, float]
    ) -> list[int | None]:
        return [None for _ in origins]


class GoogleRouting:
    """Routes API computeRouteMatrix: all candidates in one call, traffic-aware driving times."""

    name = "google"
    URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    def eta_minutes(
        self, origins: Sequence[tuple[float, float]], destination: tuple[float, float]
    ) -> list[int | None]:
        def waypoint(point: tuple[float, float]) -> dict[str, Any]:
            return {"waypoint": {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}}

        body = {
            "origins": [waypoint(o) for o in origins],
            "destinations": [waypoint(destination)],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
        }
        try:
            with _client(self.transport) as client:
                response = client.post(self.URL, json=body, headers=headers)
            response.raise_for_status()
            rows: list[dict[str, Any]] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"route matrix failed: {type(exc).__name__}") from exc
        result: list[int | None] = [None for _ in origins]
        for row in rows:
            index = row.get("originIndex", 0)
            if row.get("condition") == "ROUTE_EXISTS" and isinstance(row.get("duration"), str):
                seconds = float(row["duration"].rstrip("s"))
                result[index] = max(1, math.ceil(seconds / 60))
        return result


class OsrmRouting:
    """Self-hosted OSRM table service (no traffic data; free to run, no per-request fee)."""

    name = "osrm"

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def eta_minutes(
        self, origins: Sequence[tuple[float, float]], destination: tuple[float, float]
    ) -> list[int | None]:
        points = [*origins, destination]
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
        url = f"{self.base_url}/table/v1/driving/{coords}"
        params = {"sources": ";".join(str(i) for i in range(len(origins))), "destinations": str(len(origins))}
        try:
            with _client(self.transport) as client:
                response = client.get(url, params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"osrm table failed: {type(exc).__name__}") from exc
        if data.get("code") != "Ok":
            raise ProviderError(f"osrm code {data.get('code')}")
        return [
            max(1, math.ceil(row[0] / 60)) if row and row[0] is not None else None
            for row in data.get("durations", [])
        ]


routing_circuit = Circuit()


def safe_eta(
    provider: RoutingProvider, origins: Sequence[tuple[float, float]], destination: tuple[float, float]
) -> list[int | None]:
    """Provider ETAs, or all None (→ fallback) when it is not configured, failing or in its cool-down."""
    if provider.name == "none" or not origins or not routing_circuit.available():
        return [None for _ in origins]
    try:
        values = provider.eta_minutes(origins, destination)
    except ProviderError as exc:
        routing_circuit.fail()
        logger.warning("routing provider failed, using fallback ETA: %s", exc)
        return [None for _ in origins]
    return values if len(values) == len(origins) else [None for _ in origins]


@lru_cache
def get_geocoder() -> Geocoder:
    settings = get_settings()
    if settings.geocoder == "google" and settings.google_maps_api_key:
        return GoogleGeocoder(settings.google_maps_api_key.get_secret_value())
    return StubGeocoder() if settings.geocoder == "stub" else NoGeocoder()


@lru_cache
def get_routing() -> RoutingProvider:
    settings = get_settings()
    if settings.maps_provider == "google" and settings.google_maps_api_key:
        return GoogleRouting(settings.google_maps_api_key.get_secret_value())
    if settings.maps_provider == "osrm" and settings.osrm_base_url:
        return OsrmRouting(settings.osrm_base_url)
    return NoRouting()


def fallback_eta_minutes(km: float, speed_kmh: float) -> int:
    return max(1, math.ceil(km / speed_kmh * 60))
