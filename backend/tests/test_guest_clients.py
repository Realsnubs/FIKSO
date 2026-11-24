"""Ordering without a password (owner decision 2026-11-24): guest accounts, first password, SMS codes."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.integrations import sms
from app.models import DomainEvent, LoginCode, User
from tests.conftest import PASSWORD, auth, register

GUEST = {"email": "Guest@Example.com", "full_name": "Viesis Klients", "phone": "+37121112222"}


def guest(client: TestClient, **changes: str) -> dict[str, Any]:
    resp = client.post("/api/v1/auth/guest/client", json={**GUEST, **changes})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


class FakeSender:
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, text: str, reference: str) -> sms.SmsAccepted:
        self.sent.append((to, text))
        return sms.SmsAccepted("fake", reference)

    def code(self) -> str:
        return self.sent[-1][1].split("kods ir ")[1][:6]


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> FakeSender:
    fake = FakeSender()
    monkeypatch.setattr(sms, "get_sms_sender", lambda: fake)
    return fake


def test_guest_gets_a_signed_in_client_account_without_a_password(client: TestClient) -> None:
    body = guest(client)
    assert body["user"]["role"] == "client"
    assert body["user"]["email"] == "guest@example.com"
    assert body["user"]["has_password"] is False
    assert client.cookies.get("fikso_refresh")
    # The account works like any client account.
    assert client.get("/api/v1/client/requests", headers=auth(body["access_token"])).status_code == 200
    with SessionLocal() as db:
        user = db.get(User, body["user"]["id"])
        event = db.scalar(select(DomainEvent).where(DomainEvent.aggregate_id == user.id))  # type: ignore[union-attr]
    assert user is not None and user.password_hash is None
    assert event is not None and event.payload == {"role": "client", "password": False}


def test_guest_cannot_take_over_an_existing_account(client: TestClient) -> None:
    existing = register(client, "client", email="taken@example.com")
    resp = client.post("/api/v1/auth/guest/client", json={**GUEST, "email": "TAKEN@example.com"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "EMAIL_TAKEN"
    resp = client.post("/api/v1/auth/guest/client", json={**GUEST, "phone": existing["user"]["phone"]})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "PHONE_TAKEN"


def test_guest_account_cannot_be_used_with_an_empty_or_any_password(client: TestClient) -> None:
    guest(client)
    for password in ("x", PASSWORD):
        resp = client.post("/api/v1/auth/login", json={"email": GUEST["email"], "password": password})
        assert resp.status_code == 401


def test_only_clients_may_be_password_less() -> None:
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as db:
        db.add(User(role="master", email="m@example.com", phone="+37121113333", full_name="M"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_guest_sets_a_first_password_then_signs_in_with_it(client: TestClient) -> None:
    token = guest(client)["access_token"]
    resp = client.post("/api/v1/me/password", headers=auth(token), json={"password": PASSWORD})
    assert resp.status_code == 200 and resp.json()["has_password"] is True
    login = client.post("/api/v1/auth/login", json={"email": GUEST["email"], "password": PASSWORD})
    assert login.status_code == 200


def test_changing_an_existing_password_needs_the_current_one(client: TestClient) -> None:
    token = register(client, "client")["access_token"]
    body = {"password": "another-horse-43"}
    assert client.post("/api/v1/me/password", headers=auth(token), json=body).status_code == 401
    wrong = {**body, "current_password": "wrong-password"}
    assert client.post("/api/v1/me/password", headers=auth(token), json=wrong).status_code == 401
    right = {**body, "current_password": PASSWORD}
    assert client.post("/api/v1/me/password", headers=auth(token), json=right).status_code == 200


def test_setting_a_password_needs_a_session(client: TestClient) -> None:
    assert client.post("/api/v1/me/password", json={"password": PASSWORD}).status_code == 401


def test_sms_code_signs_a_client_in_once(client: TestClient, sender: FakeSender) -> None:
    guest(client)
    client.cookies.clear()
    assert client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]}).status_code == 202
    assert sender.sent[0][0] == GUEST["phone"]
    code = sender.code()
    with SessionLocal() as db:
        stored = db.scalar(select(LoginCode.code_hash))
    assert stored is not None and code not in stored

    resp = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": code})
    assert resp.status_code == 200 and resp.json()["user"]["email"] == "guest@example.com"
    assert client.cookies.get("fikso_refresh")
    again = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": code})
    assert again.status_code == 401 and again.json()["error"]["code"] == "INVALID_CODE"


def test_sms_code_answer_does_not_reveal_accounts(client: TestClient, sender: FakeSender) -> None:
    master = register(client, "master")
    for phone in ("+37129990000", master["user"]["phone"]):
        assert client.post("/api/v1/auth/sms-code", json={"phone": phone}).status_code == 202
    # Unknown numbers and non-clients get nothing; masters and admins keep password sign-in only.
    assert sender.sent == []


def test_sms_code_locks_after_five_wrong_attempts(client: TestClient, sender: FakeSender) -> None:
    guest(client)
    client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]})
    code = sender.code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        resp = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": wrong})
        assert resp.status_code == 401
    resp = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": code})
    assert resp.status_code == 401


def test_sms_code_expires_and_a_new_one_replaces_the_old(client: TestClient, sender: FakeSender) -> None:
    guest(client)
    client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]})
    first = sender.code()
    client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]})
    second = sender.code()
    if first != second:
        resp = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": first})
        assert resp.status_code == 401
    with SessionLocal() as db:
        db.execute(update(LoginCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    resp = client.post("/api/v1/auth/sms-code/verify", json={"phone": GUEST["phone"], "code": second})
    assert resp.status_code == 401


def test_blocked_client_gets_no_sms_code(client: TestClient, sender: FakeSender) -> None:
    body = guest(client)
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == body["user"]["id"]).values(status="blocked"))
        db.commit()
    client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]})
    assert sender.sent == []


def test_sms_code_is_refused_without_an_sms_provider(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/sms-code", json={"phone": GUEST["phone"]})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "SMS_UNAVAILABLE"


def test_sms_code_requests_are_rate_limited(client: TestClient, sender: FakeSender) -> None:
    codes = [
        client.post("/api/v1/auth/sms-code", json={"phone": "+37129990000"}).status_code for _ in range(4)
    ]
    assert codes == [202, 202, 202, 429]
