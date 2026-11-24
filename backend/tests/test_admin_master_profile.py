"""Admin approval and rejection of master profiles (step 4.4.4, R-AUTH-03, owner decisions 2026-11-02)."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models import AuditLog, DomainEvent, MasterProfile, User
from app.services import master_admin
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register

SPEC = seed_id("cm-s01")
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
ALLOWED = {
    ("pending_approval", "approve"): "approved",
    ("rejected", "approve"): "approved",
    ("pending_approval", "reject"): "rejected",
}


@dataclass
class M:
    id: uuid.UUID
    user_id: uuid.UUID
    h: dict[str, str]


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
    yield Fx(auth(admin_token), admin_id)


def _master(client: TestClient) -> M:
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
    assert master_id is not None
    return M(master_id, user_id, auth(body["access_token"]))


def _set_status(fx: Fx, master: M, status: str, reason: str | None = None) -> None:
    decided = {"decided_by": fx.admin_id, "decided_at": T0} if status != "pending_approval" else {}
    with SessionLocal() as db:
        db.execute(
            update(MasterProfile)
            .where(MasterProfile.id == master.id)
            .values(approval_status=status, decision_reason=reason, **decided)
        )
        db.commit()


def _approve(client: TestClient, fx: Fx, master_id: Any, version: int = 1, **extra: Any) -> Any:
    return client.post(
        f"/api/v1/admin/masters/{master_id}/approve",
        json={"expected_version": version, **extra},
        headers=fx.admin,
    )


def _reject(
    client: TestClient, fx: Fx, master_id: Any, version: int = 1, reason: Any = "Nepilnīgi dati"
) -> Any:
    body = {"expected_version": version, **({"reason": reason} if reason is not None else {})}
    return client.post(f"/api/v1/admin/masters/{master_id}/reject", json=body, headers=fx.admin)


def _state(master: M) -> tuple[Any, ...]:
    """Every profile column, plus all audit entries and events (any change shows up here)."""
    with SessionLocal() as db:
        profile = db.get(MasterProfile, master.id)
        assert profile is not None
        return (
            tuple(sorted((c.key, getattr(profile, c.key)) for c in MasterProfile.__table__.columns)),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _profile_log(master: M) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "master_profile", AuditLog.entity_id == master.id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _error(resp: Any) -> tuple[int, str]:
    return resp.status_code, resp.json()["error"]["code"]


# --- access -------------------------------------------------------------------------------------------------


def test_only_admins_decide(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    customer = auth(register(client, "client")["access_token"])
    before = _state(master)
    for action, body in (
        ("approve", {"expected_version": 1}),
        ("reject", {"expected_version": 1, "reason": "x"}),
    ):
        url = f"/api/v1/admin/masters/{master.id}/{action}"
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers=master.h).status_code == 403  # no self-approval
        assert client.post(url, json=body, headers=customer).status_code == 403
    assert _state(master) == before


def test_service_refuses_a_non_admin_or_the_master_itself(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    before = _state(master)
    with SessionLocal() as db:
        own = db.get(User, master.user_id)
        assert own is not None
        impostor = User(
            id=master.user_id, role="admin", email="x@example.lv", password_hash="x", full_name="X"
        )
        for actor in (own, impostor):
            with pytest.raises(AppError) as exc:
                master_admin.decide_profile(db, actor, master.id, master_admin.Decision("approve", 1))
            assert exc.value.code == "DECISION_FORBIDDEN"
            db.rollback()
    assert _state(master) == before


# --- transitions --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending_approval", "approved", "rejected"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_every_transition(client: TestClient, fx: Fx, status: str, action: str) -> None:
    master = _master(client)
    _set_status(fx, master, status, "Vecs iemesls" if status == "rejected" else None)
    before = _state(master)
    resp = _approve(client, fx, master.id) if action == "approve" else _reject(client, fx, master.id)
    expected = ALLOWED.get((status, action))
    if expected is None:  # approved → rejected and every repeat are refused
        assert _error(resp) == (409, "INVALID_TRANSITION")
        assert resp.json()["error"]["details"] == {"status": status, "version": 1, "action": action}
        assert _state(master) == before
        return
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["approval_status"], body["version"], body["decided_by"]) == (expected, 2, str(fx.admin_id))
    assert body["decision_reason"] == ("Nepilnīgi dati" if action == "reject" else None)
    [entry] = _profile_log(master)
    assert entry.action == f"master.profile.{expected}" and entry.actor_id == fx.admin_id
    assert entry.before is not None and entry.after is not None
    assert (entry.before["approval_status"], entry.after["approval_status"]) == (status, expected)
    with SessionLocal() as db:
        [event] = db.scalars(select(DomainEvent).where(DomainEvent.event_type.like("master.profile.%"))).all()
    assert event.event_type == entry.action and "decision_reason" not in event.payload


# --- input --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": 1},  # no reason
        {"expected_version": 1, "reason": ""},
        {"expected_version": 1, "reason": "   "},
        {"expected_version": 1, "reason": "x" * 1001},
        {"expected_version": 1, "reason": None},
        {"reason": "Nepilnīgi dati"},  # no version
        {"expected_version": 0, "reason": "Nepilnīgi dati"},
        {"expected_version": "one", "reason": "Nepilnīgi dati"},
        {"expected_version": 1, "reason": "Nepilnīgi dati", "decided_by": str(uuid.uuid4())},
    ],
)
def test_reject_needs_a_reason_and_a_version(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client)
    before = _state(master)
    resp = client.post(f"/api/v1/admin/masters/{master.id}/reject", json=body, headers=fx.admin)
    assert resp.status_code == 422
    assert _state(master) == before


def test_approve_accepts_no_reason_or_other_fields(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    before = _state(master)
    for extra in ({"reason": "x"}, {"approval_status": "approved"}):
        assert _approve(client, fx, master.id, **extra).status_code == 422
    assert (
        client.post(f"/api/v1/admin/masters/{master.id}/approve", json={}, headers=fx.admin).status_code
        == 422
    )
    assert _state(master) == before


# --- versions, repeats, unknown -----------------------------------------------------------------------------


def test_stale_or_repeated_decision_changes_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    stale = _approve(client, fx, master.id, version=7)
    assert _error(stale) == (409, "VERSION_CONFLICT")
    assert stale.json()["error"]["details"] == {"status": "pending_approval", "version": 1}
    assert _approve(client, fx, master.id).status_code == 200
    before = _state(master)
    for repeat in (_approve(client, fx, master.id), _reject(client, fx, master.id)):
        assert _error(repeat) == (409, "VERSION_CONFLICT")
        assert repeat.json()["error"]["details"] == {"status": "approved", "version": 2}
    # Even with the current version, an approved profile is not rejected directly.
    assert _error(_reject(client, fx, master.id, version=2)) == (409, "INVALID_TRANSITION")
    assert _state(master) == before
    assert [e.action for e in _profile_log(master)] == ["master.profile.approved"]


def test_unknown_or_deleted_masters(client: TestClient, fx: Fx) -> None:
    master, gone = _master(client), _master(client)
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == gone.user_id).values(deleted_at=T0))
        db.commit()
    before = _state(gone)
    for target in (uuid.uuid4(), master.user_id, gone.id):
        assert _error(_approve(client, fx, target)) == (404, "MASTER_NOT_FOUND")
        assert _error(_reject(client, fx, target)) == (404, "MASTER_NOT_FOUND")
    assert _state(gone) == before
    assert _profile_log(master) == []


# --- history and effects ------------------------------------------------------------------------------------


def test_reject_then_reapprove_keeps_history_and_clears_the_current_reason(
    client: TestClient, fx: Fx
) -> None:
    master = _master(client)
    rejected = _reject(client, fx, master.id, reason="Trūkst dokumentu").json()
    assert (rejected["approval_status"], rejected["decision_reason"]) == ("rejected", "Trūkst dokumentu")
    caps = client.get("/api/v1/master/capabilities", headers=master.h).json()
    assert caps["rejection_reason"] == "Trūkst dokumentu"
    # A rejected profile is read-only (owner decision 2026-11-02).
    request = {"specialisation_id": str(SPEC)}
    blocked = client.post("/api/v1/master/specialisations", json=request, headers=master.h)
    assert _error(blocked) == (409, "MASTER_PROFILE_REJECTED")

    approved = _approve(client, fx, master.id, version=2).json()
    assert (approved["approval_status"], approved["version"], approved["decision_reason"]) == (
        "approved",
        3,
        None,
    )
    caps = client.get("/api/v1/master/capabilities", headers=master.h).json()
    assert (caps["approval_status"], caps["rejection_reason"]) == ("approved", None)
    assert client.get("/api/v1/me", headers=master.h).json()["master_approval_status"] == "approved"
    assert client.post("/api/v1/master/specialisations", json=request, headers=master.h).status_code == 201

    log = _profile_log(master)
    assert [e.action for e in log] == ["master.profile.rejected", "master.profile.approved"]
    assert log[0].reason == "Trūkst dokumentu" and log[0].after == log[1].before
    assert log[1].before is not None and log[1].before["decision_reason"] == "Trūkst dokumentu"
    assert log[1].after is not None and log[1].after["decision_reason"] is None
    assert log[0].after is not None and log[0].after["decided_at"] != log[1].after["decided_at"]


def test_blocked_account_stays_blocked(client: TestClient, fx: Fx) -> None:
    """Blocking is the existing user mechanism; a profile decision neither lifts nor replaces it."""
    master = _master(client)
    blocked = client.post(
        f"/api/v1/admin/users/{master.user_id}/block", json={"reason": "Sūdzības"}, headers=fx.admin
    )
    assert blocked.status_code == 200
    approved = _approve(client, fx, master.id)
    assert approved.status_code == 200
    assert (approved.json()["approval_status"], approved.json()["user_status"]) == ("approved", "blocked")
    with SessionLocal() as db:
        user = db.get(User, master.user_id)
        assert user is not None and (user.status, user.blocked_reason) == ("blocked", "Sūdzības")
    # The blocked master cannot act at all (sessions revoked on block).
    assert client.get("/api/v1/master/capabilities", headers=master.h).status_code == 401

    other = _master(client)
    client.post(f"/api/v1/admin/users/{other.user_id}/block", json={"reason": "Sūdzības"}, headers=fx.admin)
    assert _reject(client, fx, other.id).json()["user_status"] == "blocked"


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _decide(fx: Fx, master_id: uuid.UUID, action: str, version: int, reason: str | None = "Iemesls") -> None:
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        master_admin.decide_profile(db, admin, master_id, master_admin.Decision(action, version, reason))  # type: ignore[arg-type]


def test_parallel_opposite_decisions(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []

    def run(action: str) -> None:
        barrier.wait()
        try:
            _decide(fx, master.id, action, 1)
            results.append(action)
        except AppError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=run, args=("approve" if i % 2 else "reject",)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    winners = [r for r in results if r in ("approve", "reject")]
    assert len(winners) == 1 and results.count("VERSION_CONFLICT") == n - 1
    [entry] = _profile_log(master)
    assert entry.after is not None and entry.after["version"] == 2


@pytest.mark.parametrize(
    ("held", "attempt"), [("approve", "reject"), ("reject", "approve"), ("approve", "approve")]
)
def test_decision_waits_for_a_concurrent_profile_decision(
    client: TestClient, fx: Fx, held: str, attempt: str
) -> None:
    """Another admin's decision holds the master row; ours must wait, then see it — never overwrite it.

    Without `FOR UPDATE` in `lock_master` our read sees the old version, passes every check and overwrites the
    other decision once its transaction commits: this test then fails (verified by removing the lock).
    """
    master = _master(client)
    other_decision = {
        "approval_status": ALLOWED[("pending_approval", held)],
        "decided_by": fx.admin_id,
        "decided_at": datetime.now(UTC),
        "decision_reason": "Cits administrators" if held == "reject" else None,
        "version": 2,
    }
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == master.id).with_for_update())
        holder.execute(update(MasterProfile).where(MasterProfile.id == master.id).values(**other_decision))

        def run() -> None:
            try:
                _decide(fx, master.id, attempt, 1)
                outcome.append("ok")
            except AppError as exc:
                outcome.append(exc.code)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the decision must wait for the master row lock"
        holder.commit()
    thread.join(timeout=30)
    assert outcome == ["VERSION_CONFLICT"]
    with SessionLocal() as db:
        profile = db.get(MasterProfile, master.id)
        assert profile is not None
        assert {key: getattr(profile, key) for key in other_decision} == other_decision
    assert _profile_log(master) == []
