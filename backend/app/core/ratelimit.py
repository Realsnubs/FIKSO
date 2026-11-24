"""Rate limiting shared by every backend process (production) or kept in memory (tests, one-process dev).

Production uses PostgreSQL: one atomic upsert per hit on a fixed-window counter, so N API processes and N
hosts share the same limits and restarts do not reset them. The client key is the peer address, or — only
when the peer is a trusted proxy — the first untrusted address in X-Forwarded-For (otherwise anyone could
pick their own key).
"""

import ipaddress
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import lru_cache
from threading import Lock

from fastapi import Request, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class MemoryLimiter:
    """Sliding window in process memory: correct for one process only (tests, local dev)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_UPSERT = text(
    "INSERT INTO rate_limit_counters (bucket, window_start, hits) "
    "VALUES (:bucket, to_timestamp(floor(extract(epoch from now()) / :window) * :window), 1) "
    "ON CONFLICT (bucket, window_start) DO UPDATE SET hits = rate_limit_counters.hits + 1 "
    "RETURNING hits"
)


class PostgresLimiter:
    """Fixed-window counters in `rate_limit_counters`; old windows are purged by the worker."""

    def hit(self, key: str, limit: int, window: int) -> bool:
        from app.core.db import engine

        try:
            with engine.begin() as conn:
                hits = conn.execute(_UPSERT, {"bucket": key, "window": window}).scalar_one()
        except Exception:  # noqa: BLE001 - a broken limiter must not take the API down
            logger.exception("rate limiter unavailable; request allowed")
            return True
        return int(hits) <= limit

    def reset(self) -> None:
        from app.core.db import engine

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_counters"))


@lru_cache
def _trusted() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(net, strict=False) for net in get_settings().trusted_proxies)


def _is_trusted(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in _trusted())


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer):
        return peer
    forwarded = [
        part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()
    ]
    # Walk from the nearest hop: the first address our own proxies did not add is the client.
    for address in reversed(forwarded):
        if not _is_trusted(address):
            return address
    return forwarded[0] if forwarded else peer


memory_limiter = MemoryLimiter()
postgres_limiter = PostgresLimiter()


class _Limiter:
    """Facade chosen by RATE_LIMIT_BACKEND; `limiter.reset()` keeps the test fixtures working."""

    @property
    def backend(self) -> MemoryLimiter | PostgresLimiter:
        return postgres_limiter if get_settings().rate_limit_backend == "postgres" else memory_limiter

    def hit(self, key: str, limit: int, window: int) -> bool:
        return self.backend.hit(key, limit, window)

    def reset(self) -> None:
        memory_limiter.reset()
        if get_settings().rate_limit_backend == "postgres":
            postgres_limiter.reset()


limiter = _Limiter()


def rate_limit(bucket: str, limit_setting: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit: int = getattr(settings, limit_setting)
        if not limiter.hit(f"{bucket}:{client_ip(request)}", limit, settings.rate_limit_window_seconds):
            raise AppError(
                "RATE_LIMITED", "Too many attempts. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS
            )

    return dependency
