from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import DomainEvent, User
from tests.conftest import PASSWORD, auth, register


def test_register_client_returns_tokens_and_refresh_cookie(client: TestClient) -> None:
    body = register(client, "client", email="Anna@Example.com")
    assert body["user"]["role"] == "client"
    assert body["user"]["email"] == "anna@example.com"
    assert body["user"]["master_approval_status"] is None
    assert client.cookies.get("fikso_refresh")

    me = client.get("/api/v1/me", headers=auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_register_master_starts_pending_approval(client: TestClient) -> None:
    body = register(client, "master")
    assert body["user"]["role"] == "master"
    assert body["user"]["master_approval_status"] == "pending_approval"


def test_registration_records_domain_event(client: TestClient) -> None:
    body = register(client, "client")
    with SessionLocal() as db:
        event = db.scalar(select(DomainEvent).where(DomainEvent.aggregate_id == body["user"]["id"]))
    assert event is not None
    assert event.event_type == "user.registered"
    assert event.payload == {"role": "client"}


def test_password_is_hashed(client: TestClient) -> None:
    body = register(client, "client")
    with SessionLocal() as db:
        user = db.get(User, body["user"]["id"])
    assert user is not None
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_duplicate_email_is_rejected_case_insensitively(client: TestClient) -> None:
    register(client, "client", email="dup@example.com")
    resp = client.post(
        "/api/v1/auth/register/master",
        json={"email": "DUP@example.com", "password": PASSWORD, "full_name": "X", "phone": "+37129999999"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_TAKEN"


def test_validation_error_does_not_echo_password(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/register/client",
        json={"email": "bad", "password": "short-pw", "full_name": "X", "phone": "123"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "short-pw" not in resp.text


def test_login_wrong_password_and_unknown_email_look_the_same(client: TestClient) -> None:
    register(client, "client", email="known@example.com")
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "known@example.com", "password": "nope-nope-nope"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_me_requires_valid_token(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=auth("not-a-jwt")).status_code == 401


def test_refresh_rotates_token_and_reuse_revokes_all_sessions(client: TestClient) -> None:
    register(client, "client")
    old_cookie = client.cookies.get("fikso_refresh")

    first = client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    new_cookie = client.cookies.get("fikso_refresh")
    assert new_cookie and new_cookie != old_cookie

    # Replaying the rotated token is treated as theft: it fails and the newer session dies too.
    client.cookies.set("fikso_refresh", old_cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.set("fikso_refresh", new_cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token(client: TestClient) -> None:
    register(client, "client")
    cookie = client.cookies.get("fikso_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("fikso_refresh", cookie, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_login_is_rate_limited(client: TestClient) -> None:
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "wrong-password"})
    resp = client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "wrong-password"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


def test_health(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}
