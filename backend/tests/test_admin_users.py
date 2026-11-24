import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal, engine
from app.models import AuditLog
from tests.conftest import PASSWORD, auth, register


@pytest.mark.parametrize("role", ["client", "master"])
def test_non_admin_cannot_use_admin_endpoints(client: TestClient, role: str) -> None:
    token = register(client, role)["access_token"]
    other = register(client, "client")["user"]["id"]
    headers = auth(token)
    assert client.get("/api/v1/admin/users", headers=headers).status_code == 403
    assert client.get(f"/api/v1/admin/users/{other}", headers=headers).status_code == 403
    resp = client.post(f"/api/v1/admin/users/{other}/block", json={"reason": "spam"}, headers=headers)
    assert resp.status_code == 403


def test_admin_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/users").status_code == 401


def test_admin_lists_users_with_filters_and_cursor(client: TestClient, admin_token: str) -> None:
    for _ in range(3):
        register(client, "client")
    register(client, "master")
    headers = auth(admin_token)

    page1 = client.get("/api/v1/admin/users?role=client&limit=2", headers=headers).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = client.get(
        f"/api/v1/admin/users?role=client&limit=2&cursor={page1['next_cursor']}", headers=headers
    )
    items2 = page2.json()["items"]
    assert len(items2) == 1 and page2.json()["next_cursor"] is None
    ids = {u["id"] for u in page1["items"]} | {u["id"] for u in items2}
    assert len(ids) == 3

    masters = client.get("/api/v1/admin/users?role=master", headers=headers).json()["items"]
    assert [m["master_approval_status"] for m in masters] == ["pending_approval"]


def test_block_takes_effect_immediately_and_is_audited(client: TestClient, admin_token: str) -> None:
    victim = register(client, "client", email="blocked@example.com")
    victim_id = victim["user"]["id"]

    resp = client.post(
        f"/api/v1/admin/users/{victim_id}/block", json={"reason": "Fraud report"}, headers=auth(admin_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"

    # Existing access token stops working, refresh is revoked and login is refused.
    assert client.get("/api/v1/me", headers=auth(victim["access_token"])).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": "blocked@example.com", "password": PASSWORD})
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "ACCOUNT_BLOCKED"

    with SessionLocal() as db:
        entry = db.scalar(select(AuditLog).where(AuditLog.entity_id == victim_id))
    assert entry is not None
    assert entry.action == "user.blocked"
    assert entry.reason == "Fraud report"

    unblock = client.post(f"/api/v1/admin/users/{victim_id}/unblock", headers=auth(admin_token))
    assert unblock.json()["status"] == "active"
    login = client.post("/api/v1/auth/login", json={"email": "blocked@example.com", "password": PASSWORD})
    assert login.status_code == 200


def test_admin_cannot_block_self(client: TestClient, admin_token: str) -> None:
    me = client.get("/api/v1/me", headers=auth(admin_token)).json()
    resp = client.post(
        f"/api/v1/admin/users/{me['id']}/block", json={"reason": "oops"}, headers=auth(admin_token)
    )
    assert resp.status_code == 409


def test_unknown_user_returns_404(client: TestClient, admin_token: str) -> None:
    resp = client.get("/api/v1/admin/users/00000000-0000-0000-0000-000000000000", headers=auth(admin_token))
    assert resp.status_code == 404


@pytest.mark.parametrize("table", ["audit_log", "domain_events"])
def test_append_only_tables_reject_updates_and_deletes(client: TestClient, table: str) -> None:
    register(client, "client")
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO audit_log (id, actor_type, action, entity_type) "
                "VALUES (gen_random_uuid(), 'system', 'test', 'test')"
            )
        )
        db.commit()
    for statement in (f"UPDATE {table} SET created_at = now()", f"DELETE FROM {table}"):
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
            conn.execute(text(statement))
