"""Production readiness: shared rate limits, S3 storage, geocoding, routing, SMS, billable rule,
configuration,
readiness and security headers. External services are replaced by mock servers / mock transports."""

import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer
from PIL import Image
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from starlette.requests import Request

from app import worker
from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.integrations import maps, sms, storage
from app.models import AuditLog, Notification, User
from app.services import billable
from tests.conftest import auth, register
from tests.factories import build_catalogue, make_master

API = "/api/v1"


# ---------------------------------------------------------------- rate limiting


def test_postgres_limiter_is_shared_between_processes() -> None:
    first, second = ratelimit.PostgresLimiter(), ratelimit.PostgresLimiter()  # two "processes"
    key = f"login:{uuid.uuid4()}"
    assert first.hit(key, 2, 60) and second.hit(key, 2, 60)
    assert not first.hit(key, 2, 60) and not second.hit(key, 2, 60)
    assert first.hit(f"upload:{key}", 2, 60)  # other operation types have their own counter


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers, "method": "GET", "path": "/"})


def test_forwarded_for_is_believed_only_from_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", ["10.0.0.0/8"])
    ratelimit._trusted.cache_clear()
    try:
        assert (
            ratelimit.client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"
        )  # spoofed header ignored
        assert ratelimit.client_ip(_request("10.0.0.5", "198.51.100.7, 10.0.0.9")) == "198.51.100.7"
        assert ratelimit.client_ip(_request("10.0.0.5", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    finally:
        ratelimit._trusted.cache_clear()


def test_api_uses_the_postgres_limiter(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "postgres")
    monkeypatch.setattr(get_settings(), "rate_limit_login", 2)
    try:
        codes = [
            client.post(f"{API}/auth/login", json={"email": "x@example.lv", "password": "y"}).status_code
            for _ in range(3)
        ]
        assert codes == [401, 401, 429]
        with SessionLocal() as db:
            assert db.execute(
                select(ratelimit.text("count(*)")).select_from(ratelimit.text("rate_limit_counters"))
            ).scalar()
    finally:
        ratelimit.postgres_limiter.reset()


def test_worker_purges_old_rate_limit_windows() -> None:
    ratelimit.PostgresLimiter().hit("x:1", 5, 60)
    assert worker.purge_rate_limits(datetime.now(UTC) + timedelta(hours=2)) >= 1


# ---------------------------------------------------------------- S3 storage (moto server over HTTP)


@pytest.fixture(scope="module")
def s3_server() -> Iterator[str]:
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def s3(s3_server: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    settings = get_settings()
    private, public = f"priv-{uuid.uuid4().hex[:8]}", f"pub-{uuid.uuid4().hex[:8]}"
    for name, value in (
        ("storage_backend", "s3"),
        ("s3_endpoint_url", s3_server),
        ("s3_region", "eu-central-1"),
        ("s3_access_key_id", SecretStr("test")),
        ("s3_secret_access_key", SecretStr("test")),
        ("s3_private_bucket", private),
        ("s3_public_bucket", public),
    ):
        monkeypatch.setattr(settings, name, value)
    client = storage._s3_client()
    for bucket in (private, public):
        client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
    storage.get_storage.cache_clear()
    storage.get_public_storage.cache_clear()
    yield client
    storage.get_storage.cache_clear()
    storage.get_public_storage.cache_clear()


def test_s3_adapter_put_open_delete_list(s3: Any) -> None:
    store = storage.get_storage()
    key = storage.new_key()
    store.put(key, b"hello")
    with store.open(key) as handle:
        assert handle.read() == b"hello"
    assert [k for k, _ in store.objects()] == [key]
    store.delete(key)
    with pytest.raises(FileNotFoundError):
        store.open(key)
    with pytest.raises(ValueError):
        store.put("../evil", b"x")


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 800), (1, 2, 3)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_private_and_public_files_go_to_separate_buckets_and_keep_access_rules(
    client: TestClient, s3: Any, admin_token: str
) -> None:
    cat = build_catalogue()
    make_master(client, cat)
    token = register(client, "client")["access_token"]
    req = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Brīvības iela 1",
            "city": "riga",
        },
        headers=auth(token),
    ).json()
    photo = client.post(
        f"{API}/client/requests/{req['id']}/photos",
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        headers=auth(token),
    ).json()
    settings = get_settings()
    private_keys = [
        o["Key"] for o in s3.list_objects_v2(Bucket=settings.s3_private_bucket).get("Contents", [])
    ]
    assert len(private_keys) == 1
    assert (
        client.get(f"{API}/client/requests/{req['id']}/photos/{photo['id']}", headers=auth(token)).status_code
        == 200
    )
    other = register(client, "client")["access_token"]
    assert (
        client.get(f"{API}/client/requests/{req['id']}/photos/{photo['id']}", headers=auth(other)).status_code
        == 404
    )
    assert (
        client.get(f"{API}/media/{private_keys[0]}").status_code == 404
    )  # private never via the public route
    media = client.post(
        f"{API}/admin/media",
        files={"file": ("p.jpg", _jpeg(), "image/jpeg")},
        data={"rights_basis": "own", "personal_data_checked": "true"},
        headers=auth(admin_token),
    ).json()
    public_keys = {o["Key"] for o in s3.list_objects_v2(Bucket=settings.s3_public_bucket)["Contents"]}
    assert len(public_keys) == 3 and not public_keys & set(private_keys)
    assert client.get(media["urls"]["800"]).status_code == 200


def test_storage_migration_copies_verifies_and_is_idempotent(s3: Any, tmp_path: Any) -> None:
    from app.services.storage_migration import migrate

    local = storage.LocalStorage(tmp_path)
    good, bad = storage.new_key(), storage.new_key()
    local.put(good, b"good")
    local.put(bad, b"tampered")
    with SessionLocal() as db:
        owner = User(role="client", email="m@example.lv", password_hash="x", full_name="M")
        db.add(owner)
        db.flush()
        from app.models import Attachment

        for key, data in ((good, b"good"), (bad, b"original")):
            import hashlib

            db.add(
                Attachment(
                    owner_user_id=owner.id,
                    entity_type="request",
                    entity_id=uuid.uuid4(),
                    storage_key=key,
                    mime_type="image/jpeg",
                    size_bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )
        db.commit()
        target = storage.get_storage()
        first = migrate(db, local, target, private=True)
        second = migrate(db, local, target, private=True)
    assert (first.copied, first.mismatched) == (1, [bad])
    assert second.copied == 0 and second.skipped_existing == 1
    assert local.exists(good) and local.exists(bad)  # nothing deleted locally


# ---------------------------------------------------------------- geocoding


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _google(status: str, location_type: str = "ROOFTOP", lat: float = 56.95, lng: float = 24.11) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["components"] == "country:LV"
        results = [{"geometry": {"location": {"lat": lat, "lng": lng}, "location_type": location_type}}]
        return httpx.Response(200, json={"status": status, "results": results if status == "OK" else []})

    return handler


def test_google_geocoder_accepts_precise_latvian_results_only() -> None:
    ok = maps.GoogleGeocoder("k", _transport(_google("OK"))).geocode("Brīvības iela 1, Rīga")
    assert ok is not None and ok.source == "google" and str(ok.lat) == "56.950000"
    assert maps.GoogleGeocoder("k", _transport(_google("OK", "APPROXIMATE"))).geocode("Rīga") is None
    assert maps.GoogleGeocoder("k", _transport(_google("OK", lat=59.4, lng=24.7))).geocode("Tallinn") is None
    assert maps.GoogleGeocoder("k", _transport(_google("ZERO_RESULTS"))).geocode("nekas") is None
    with pytest.raises(maps.ProviderError):
        maps.GoogleGeocoder("k", _transport(_google("REQUEST_DENIED"))).geocode("x")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(maps.ProviderError):
        maps.GoogleGeocoder("k", _transport(timeout)).geocode("x")


def test_geocoder_outage_is_reported_truthfully(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cat = build_catalogue()
    make_master(client, cat)
    token = register(client, "client")["access_token"]
    monkeypatch.setattr("app.services.requests.get_geocoder", lambda: maps.NoGeocoder())
    body = {"w_id": "W092", "description": "Jāuzstāda lustra.", "address": "Brīvības iela 1", "city": "riga"}
    resp = client.post(f"{API}/client/requests", json=body, headers=auth(token))
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "GEOCODING_UNAVAILABLE"
    with_device = client.post(
        f"{API}/client/requests", json={**body, "lat": "56.95", "lon": "24.10"}, headers=auth(token)
    )
    assert with_device.status_code == 201  # the device location still works


def test_production_refuses_the_geocoder_stub() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret="x" * 40, environment="test", geocoder="google")  # google without a key


# ---------------------------------------------------------------- routing


def test_google_route_matrix_and_osrm() -> None:
    def google(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-Api-Key"] == "k"
        rows = [
            {"originIndex": 0, "duration": "600s", "condition": "ROUTE_EXISTS"},
            {"originIndex": 1, "condition": "ROUTE_NOT_FOUND"},
        ]
        return httpx.Response(200, json=rows)

    assert maps.GoogleRouting("k", _transport(google)).eta_minutes(
        [(56.9, 24.1), (56.8, 24.0)], (56.95, 24.1)
    ) == [10, None]

    def osrm(request: httpx.Request) -> httpx.Response:
        assert "/table/v1/driving/" in request.url.path
        return httpx.Response(200, json={"code": "Ok", "durations": [[125.0], [None]]})

    assert maps.OsrmRouting("http://osrm", _transport(osrm)).eta_minutes(
        [(56.9, 24.1), (56.8, 24.0)], (56.95, 24.1)
    ) == [3, None]


def test_routing_outage_falls_back_and_opens_the_circuit() -> None:
    calls = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    provider = maps.GoogleRouting("k", _transport(down))
    maps.routing_circuit.reset()
    try:
        assert maps.safe_eta(provider, [(56.9, 24.1)], (56.95, 24.1)) == [None]
        assert maps.safe_eta(provider, [(56.9, 24.1)], (56.95, 24.1)) == [None]
        assert len(calls) == 1  # second call skipped while the circuit is open
    finally:
        maps.routing_circuit.reset()


def test_matching_still_works_when_routing_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cat = build_catalogue()
    make_master(client, cat)
    monkeypatch.setattr(
        "app.services.matching.get_routing",
        lambda: maps.GoogleRouting("k", _transport(lambda r: httpx.Response(500))),
    )
    maps.routing_circuit.reset()
    token = register(client, "client")["access_token"]
    req = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Brīvības iela 1",
            "city": "riga",
            "lat": "56.95",
            "lon": "24.10",
        },
        headers=auth(token),
    ).json()
    submitted = client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(token)).json()
    maps.routing_circuit.reset()
    assert submitted["status"] == "proposed"
    with SessionLocal() as db:
        from app.models import MatchingCandidate

        assert db.scalar(select(MatchingCandidate.eta_source)) == "fallback"  # the source is always explicit


def test_routing_success_is_recorded_as_routing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cat = build_catalogue()
    make_master(client, cat)

    def ok(r):
        return httpx.Response(200, json=[{"originIndex": 0, "duration": "420s", "condition": "ROUTE_EXISTS"}])  # noqa: E731

    monkeypatch.setattr("app.services.matching.get_routing", lambda: maps.GoogleRouting("k", _transport(ok)))
    maps.routing_circuit.reset()
    token = register(client, "client")["access_token"]
    req = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Brīvības iela 1",
            "city": "riga",
            "lat": "56.95",
            "lon": "24.10",
        },
        headers=auth(token),
    ).json()
    submitted = client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(token)).json()
    assert submitted["proposal"]["masters"][0]["eta_minutes"] == 7


# ---------------------------------------------------------------- SMS


def _messente(status_code: int, body: Any) -> sms.MessenteSender:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][0]["channel"] == "sms" and payload["dlr_url"].endswith("token=t")
        return httpx.Response(status_code, json=body)

    return sms.MessenteSender(
        "u", "p", "FIKSO", "https://app/api/v1/webhooks/sms/messente?token=t", _transport(handler)
    )


def _sms_row(phone: str | None = "auto") -> uuid.UUID:
    if phone == "auto":
        phone = f"+3712{uuid.uuid4().int % 10**7:07d}"
    with SessionLocal() as db:
        user = User(
            role="client",
            email=f"{uuid.uuid4().hex[:6]}@example.lv",
            phone=phone,
            password_hash="x",
            full_name="S",
        )
        db.add(user)
        db.flush()
        row = Notification(user_id=user.id, type="order.accepted", channel="sms", status="pending")
        db.add(row)
        db.commit()
        return row.id


def _row(row_id: uuid.UUID) -> Notification:
    with SessionLocal() as db:
        row = db.get(Notification, row_id)
        assert row is not None
        return row


def test_sms_is_sent_only_when_the_provider_returns_a_message_id() -> None:
    row_id = _sms_row()
    accepted = _messente(201, {"messages": [{"message_id": "m-1", "channel": "sms"}], "omnimessage_id": "o"})
    assert worker.deliver_notifications(datetime.now(UTC), accepted) == 1
    row = _row(row_id)
    assert (row.status, row.provider, row.provider_message_id, row.attempts) == ("sent", "messente", "m-1", 1)
    worker.deliver_notifications(datetime.now(UTC) + timedelta(hours=1), accepted)
    assert _row(row_id).attempts == 1  # never sent twice


def test_sms_temporary_failures_retry_and_permanent_ones_fail() -> None:
    now = datetime.now(UTC)
    temporary = _sms_row()
    worker.deliver_notifications(now, _messente(503, {}))
    row = _row(temporary)
    assert row.status == "pending" and row.attempts == 1 and row.next_attempt_at > now  # type: ignore[operator]
    worker.deliver_notifications(now, _messente(503, {}))  # not due yet: untouched
    assert _row(temporary).attempts == 1
    accepted = _messente(201, {"messages": [{"message_id": "r-1"}]})
    worker.deliver_notifications(now + timedelta(hours=1), accepted)
    assert _row(temporary).status == "sent"  # the retry succeeded

    permanent = _sms_row()
    worker.deliver_notifications(now + timedelta(hours=2), _messente(400, {"errors": []}))
    assert _row(permanent).status == "failed" and _row(permanent).attempts == 1

    no_id = _sms_row()
    worker.deliver_notifications(now + timedelta(hours=3), _messente(201, {"unexpected": True}))
    assert _row(no_id).status == "pending" and _row(no_id).provider_message_id is None  # no proof → not sent


def test_sms_without_phone_or_provider_is_never_reported_as_sent() -> None:
    no_phone = _sms_row(None)
    worker.deliver_notifications(datetime.now(UTC), _messente(201, {"messages": [{"message_id": "x"}]}))
    assert _row(no_phone).status == "failed"
    skipped = _sms_row()
    worker.deliver_notifications(datetime.now(UTC), None)
    assert _row(skipped).status == "skipped"


def test_delivery_report_webhook(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "sms_webhook_token", SecretStr("secret-token"))
    row_id = _sms_row()
    worker.deliver_notifications(datetime.now(UTC), _messente(201, {"messages": [{"message_id": "dlr-1"}]}))
    url = f"{API}/webhooks/sms/messente"
    assert (
        client.post(f"{url}?token=wrong", json={"message_id": "dlr-1", "status": "DELIVRD"}).status_code
        == 403
    )
    assert (
        client.post(
            f"{url}?token=secret-token", json={"message_id": "dlr-1", "status": "DELIVRD"}
        ).status_code
        == 204
    )
    assert _row(row_id).status == "delivered" and _row(row_id).delivered_at is not None
    assert (
        client.post(
            f"{url}?token=secret-token", json={"message_id": "unknown", "status": "DELIVRD"}
        ).status_code
        == 204
    )


def test_sms_rows_are_queued_only_when_a_provider_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import notifications

    with SessionLocal() as db:
        user = User(role="client", email="q@example.lv", password_hash="x", full_name="Q")
        db.add(user)
        db.flush()
        notifications.notify(db, user.id, "order.accepted")
        db.commit()
        assert db.scalar(select(Notification.channel).where(Notification.channel == "sms")) is None
        monkeypatch.setattr("app.integrations.sms.get_sms_sender", lambda: _messente(201, {}))
        notifications.notify(db, user.id, "order.accepted")
        db.commit()
        assert db.scalar(select(Notification.status).where(Notification.channel == "sms")) == "pending"


# ---------------------------------------------------------------- billable time rule (Q-01)


@pytest.mark.parametrize(
    ("rounding", "step", "seconds", "expected"),
    [
        ("none", 1, 3661, 3661),
        ("up", 15, 900, 900),  # exactly on the boundary stays
        ("up", 15, 901, 1800),
        ("up", 15, 0, 0),
        ("down", 15, 1799, 900),
        ("nearest", 15, 449, 0),
        ("nearest", 15, 450, 900),  # half a step rounds up
        ("nearest", 30, 5400 + 899, 5400),
    ],
)
def test_billable_rounding_boundaries(rounding: Any, step: int, seconds: int, expected: int) -> None:
    assert billable.apply(seconds, billable.Rule(rounding, step, False)) == expected


def test_rule_changes_withdraw_approval_and_are_audited(client: TestClient, admin_token: str) -> None:
    h = auth(admin_token)
    start = client.get(f"{API}/admin/settings", headers=h).json()
    assert start["unconfirmed_policies"] == ["billable_time", "immediate_job_minutes", "order_buffer_minutes"]
    assert set(start["billable_options"]) == {"A", "B", "C", "D"}
    body = {"policy": "billable_time", "confirmed": True, "reason": "Īpašnieks apstiprināja A"}
    assert (
        "billable_time"
        not in client.post(f"{API}/admin/settings/policy-confirmation", json=body, headers=h).json()[
            "unconfirmed_policies"
        ]
    )
    changed = client.put(
        f"{API}/admin/settings/billable-time/rule",
        json={"rounding": "up", "step_minutes": 15, "reason": "Tests"},
        headers=h,
    ).json()
    assert changed["billable_time"] == {"rounding": "up", "step_minutes": 15}
    assert "billable_time" in changed["unconfirmed_policies"]  # a new rule needs a new approval
    with SessionLocal() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "settings.changed").count() >= 3
    client_token = register(client, "client")["access_token"]
    assert client.get(f"{API}/admin/settings", headers=auth(client_token)).status_code == 403


# ---------------------------------------------------------------- configuration, readiness, security


BASE: dict[str, Any] = {"jwt_secret": "x" * 40}
PROD: dict[str, Any] = {
    **BASE,
    "environment": "production",
    "catalogue_role": "issuer",
    "geocoder": "none",
    "catalogue_signing_key_id": "prod-2026-11",
    "storage_backend": "s3",
    "s3_private_bucket": "p",
    "s3_public_bucket": "q",
    "app_origin": "https://app.fiksoapp.eu",
    "rate_limit_backend": "postgres",
    "cookie_secure": True,
}


def test_production_configuration_is_validated_without_echoing_secrets() -> None:
    from app.core.signing import generate_keypair

    private, _ = generate_keypair()
    prod = {**PROD, "catalogue_signing_private_key": private}
    assert Settings(**prod).storage_backend == "s3"
    for broken in (
        {"storage_backend": "local"},
        {"rate_limit_backend": "memory"},
        {"cookie_secure": False},
        {"app_origin": "http://insecure"},
        {"s3_public_bucket": "p"},
        {"sms_provider": "messente", "messente_api_password": SecretStr("hunter2-secret")},
    ):
        with pytest.raises(ValidationError) as caught:
            Settings(**{**prod, **broken})
        assert "hunter2-secret" not in str(caught.value) and private not in str(caught.value)


def test_readiness_reports_checks(client: TestClient) -> None:
    body = client.get(f"{API}/health/ready").json()
    assert body["status"] == "ok"
    assert body["checks"]["migrations"] == "ok" and body["checks"]["private_storage"] == "ok"
    assert body["checks"]["unconfirmed_policies"]
    assert client.get(f"{API}/health/live").json() == {"status": "ok"}


def test_security_headers_request_id_and_origin_check(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = client.get(f"{API}/health/live", headers={"X-Request-ID": "bad id with spaces\nInjected: 1"})
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["x-frame-options"] == "DENY"
    assert " " not in resp.headers["x-request-id"]
    assert (
        client.get(f"{API}/health/live", headers={"X-Request-ID": "abc-123-def"}).headers["x-request-id"]
        == "abc-123-def"
    )
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "app_origin", "https://app.fiksoapp.eu")
    guarded = TestClient(create_app())
    assert guarded.post(f"{API}/auth/refresh", headers={"Origin": "https://evil.example"}).status_code == 403
    assert (
        guarded.post(f"{API}/auth/refresh", headers={"Origin": "https://app.fiksoapp.eu"}).status_code == 401
    )


def test_access_log_has_route_templates_not_urls(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="fikso.access")
    client.get(f"{API}/public/specialisations/some-slug?token=secret&phone=+37120000000")
    lines = [r.getMessage() for r in caplog.records if r.name == "fikso.access"]
    assert any("/public/specialisations/{slug}" in line for line in lines)
    assert not any("secret" in line or "3712" in line for line in lines)


def test_finalisation_applies_the_configured_rule_and_records_it(
    client: TestClient, admin_token: str
) -> None:
    from app.models import Order, WorkSegment
    from tests.test_stage_d import _confirm, _offer_id, _submitted

    cat = build_catalogue()
    master = make_master(client, cat)
    client.put(
        f"{API}/admin/settings/billable-time/rule",
        headers=auth(admin_token),
        json={"rounding": "up", "step_minutes": 15, "reason": "Tests"},
    )
    token = register(client, "client")["access_token"]
    _confirm(client, token, _submitted(client, token))
    order_id = _offer_id(client, master)
    for action in ("accept", "depart", "arrive", "start", "finish"):
        client.post(f"{API}/master/orders/{order_id}/{action}", headers=auth(master.token))
    with SessionLocal() as db:
        segment = db.scalar(select(WorkSegment).where(WorkSegment.order_id == uuid.UUID(order_id)))
        assert segment is not None
        segment.ended_at = segment.started_at + timedelta(minutes=61)
        db.commit()
    client.put(
        f"{API}/master/orders/{order_id}/worksheet",
        json={"work_description": "Darbs"},
        headers=auth(master.token),
    )
    done = client.post(f"{API}/master/orders/{order_id}/finalise", headers=auth(master.token)).json()
    assert done["worksheet"]["billable_seconds"] == 75 * 60  # 61 min, every started 15 min
    assert done["worksheet"]["labour_amount_eur"] == "50.00"
    with SessionLocal() as db:
        from app.models import Worksheet

        sheet = db.scalar(select(Worksheet).where(Worksheet.order_id == uuid.UUID(order_id)))
        assert sheet is not None and sheet.calculation is not None
        assert sheet.calculation["billable_rule"] == {
            "rounding": "up",
            "step_minutes": 15,
            "confirmed": False,
        }
        assert sheet.calculation["actual_work_seconds"] == 61 * 60
        assert db.get(Order, uuid.UUID(order_id)) is not None


def test_every_protected_route_requires_authentication(client: TestClient) -> None:
    """Security sweep: no admin/client/master/notification route answers without a session."""
    import re

    from app.main import app

    failures = []
    for path, operations in app.openapi()["paths"].items():
        if not re.match(r"/api/v1/(admin|client|master|notifications)", path):
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in operations:
            resp = client.request(method.upper(), url, json={})
            if resp.status_code != 401:
                failures.append(f"{method.upper()} {path} → {resp.status_code}")
    assert failures == []


def test_role_separation_on_admin_routes(client: TestClient) -> None:
    import re

    from app.main import app

    token = register(client, "master")["access_token"]
    failures = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/admin"):
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in operations:
            resp = client.request(method.upper(), url, json={}, headers=auth(token))
            if resp.status_code != 403:
                failures.append(f"{method.upper()} {path} → {resp.status_code}")
    assert failures == []


def test_oversized_request_is_refused_before_reading_the_body(client: TestClient) -> None:
    resp = client.post(f"{API}/auth/login", content=b"x", headers={"Content-Length": str(50 * 1024 * 1024)})
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_repeated_payment_and_adjustment_are_recorded_once(client: TestClient, admin_token: str) -> None:
    """A retried admin submission (double click, network retry) carries the same Idempotency-Key and must
    not create a second financial entry."""
    from app.models import CommissionLedgerEntry

    master = make_master(client, build_catalogue())
    base = f"{API}/admin/commission/masters/{master.profile_id}"
    today = datetime.now(UTC).date().isoformat()
    payment = {"amount_eur": "25.00", "paid_on": today, "payment_method": "cash"}
    key = {"Idempotency-Key": str(uuid.uuid4()), **auth(admin_token)}
    first = client.post(f"{base}/payments", json=payment, headers=key)
    second = client.post(f"{base}/payments", json=payment, headers=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["paid_total_eur"] == second.json()["paid_total_eur"] == "25.00"
    adjustment = {"amount_eur": "10.00", "reason": "Korekcija"}
    adjust_key = {"Idempotency-Key": str(uuid.uuid4()), **auth(admin_token)}
    for _ in range(3):
        assert client.post(f"{base}/adjustments", json=adjustment, headers=adjust_key).status_code == 201
    # Without a key every submission is a new entry (the previous behaviour stays).
    client.post(f"{base}/payments", json=payment, headers=auth(admin_token))
    with SessionLocal() as db:
        entries = db.scalars(
            select(CommissionLedgerEntry).where(CommissionLedgerEntry.master_id == master.profile_id)
        ).all()
    assert sorted(e.entry_type for e in entries) == ["adjustment", "payment", "payment"]


def test_database_outage_is_a_clear_temporary_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from app.api.v1 import public

    def down(*_: Any, **__: Any) -> Any:
        raise OperationalError("SELECT 1", {}, Exception("connection refused to 10.0.0.1"))

    monkeypatch.setattr(public.places, "cities", down)
    resp = client.get(f"{API}/public/cities")
    assert resp.status_code == 503 and resp.headers["Retry-After"] == "30"
    assert resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "10.0.0.1" not in resp.text


def test_storage_outage_is_a_clear_temporary_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import EndpointConnectionError

    from app.api.v1 import public

    def down(*_: Any, **__: Any) -> Any:
        raise EndpointConnectionError(endpoint_url="https://s3.internal.example")

    monkeypatch.setattr(public.places, "cities", down)
    resp = client.get(f"{API}/public/cities")
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert "s3.internal" not in resp.text


def test_worker_healthcheck_follows_the_last_pass() -> None:
    from app import cli
    from app.models import JobRun

    with SessionLocal() as db:
        db.query(JobRun).delete()
        db.commit()
    with pytest.raises(SystemExit):
        cli.worker_health(5)
    worker.run_once()
    cli.worker_health(5)  # a fresh pass: healthy, no exit
    with SessionLocal() as db:  # other worker tests count the passes they make
        db.query(JobRun).delete()
        db.commit()


def test_payment_date_is_checked_against_the_riga_business_day(
    client: TestClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (Docker QA 2026-11-05 00:40 Riga = 11-04 UTC): "today" in Riga was refused as future."""
    from datetime import date

    from app.services import commission

    monkeypatch.setattr(commission, "business_today", lambda _db: date(2026, 11, 5))
    master = make_master(client, build_catalogue())
    url = f"{API}/admin/commission/masters/{master.profile_id}/payments"
    for paid_on, expected in (("2026-11-05", 201), ("2026-11-06", 422)):
        body = {"amount_eur": "5.00", "paid_on": paid_on, "payment_method": "cash"}
        assert client.post(url, json=body, headers=auth(admin_token)).status_code == expected, paid_on


def test_worker_survives_a_database_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (Docker QA): with PostgreSQL stopped the worker process crashed and crash-looped."""
    from sqlalchemy.exc import OperationalError

    class Stop(Exception):
        pass

    calls: list[str] = []

    def flaky_once() -> None:
        calls.append("pass")
        if len(calls) < 3:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        raise Stop

    monkeypatch.setattr(worker, "run_once", flaky_once)
    monkeypatch.setattr(worker, "mark_stale_runs", lambda _now: 0)
    monkeypatch.setattr(worker.time, "sleep", lambda _s: None)
    with pytest.raises(Stop):
        worker.run_forever(0)
    assert calls == ["pass", "pass", "pass"]  # two failed passes were skipped, the loop kept going
