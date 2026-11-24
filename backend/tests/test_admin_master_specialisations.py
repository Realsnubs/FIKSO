"""Admin decisions on master specialisations (step 4.4.5, R-MST-08, owner decisions 2026-11-02)."""

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
from app.models import (
    AuditLog,
    CatalogueService,
    CatalogueSpecialisation,
    DomainEvent,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.master import SPECIALISATION_STATUSES
from app.services import eligibility, master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register

SPEC = seed_id("cm-s01")
OTHER_SPEC = seed_id("cm-s02")
SERVICE = seed_id("cm-s01-1")
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
ACTIONS = ("approve", "reject", "revoke")
ALLOWED = {
    ("requested", "approve"): "approved",
    ("requested", "reject"): "rejected",
    ("approved", "revoke"): "revoked",
}
DECIDED = ("approved", "rejected", "revoked")


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


def _row(fx: Fx, master: M, status: str, spec_id: uuid.UUID = SPEC, version: int = 1) -> None:
    decided = {"decided_by": fx.admin_id, "decided_at": T0} if status in DECIDED else {}
    with SessionLocal() as db:
        db.add(
            MasterSpecialisation(
                master_id=master.id,
                specialisation_id=spec_id,
                status=status,
                version=version,
                decision_reason="Vecs iemesls" if status in ("rejected", "revoked") else None,
                **decided,
            )
        )
        db.commit()


def _url(master_id: Any, spec_id: Any, action: str) -> str:
    return f"/api/v1/admin/masters/{master_id}/specialisations/{spec_id}/{action}"


def _post(
    client: TestClient,
    fx: Fx,
    action: str,
    master_id: Any,
    spec_id: Any = SPEC,
    version: int = 1,
    reason: str | None = "Pamatojums",
) -> Any:
    body: dict[str, Any] = {"expected_version": version}
    if action != "approve" and reason is not None:
        body["reason"] = reason
    return client.post(_url(master_id, spec_id, action), json=body, headers=fx.admin)


def _state() -> tuple[Any, ...]:
    """Every capability row and profile (all columns), plus all audit entries and events."""
    with SessionLocal() as db:
        rows = tuple(
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (MasterProfile, MasterSpecialisation, MasterCompetency, MasterQualification)
            for row in db.scalars(select(model))
        )
        return (
            sorted(rows),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _log(master: M) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "master_specialisation", AuditLog.entity_id == master.id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _error(resp: Any) -> tuple[int, str]:
    return resp.status_code, resp.json()["error"]["code"]


def _spec(body: dict[str, Any], spec_id: uuid.UUID = SPEC) -> dict[str, Any]:
    [found] = [s for s in body["specialisations"] if s["specialisation_id"] == str(spec_id)]
    return found


# --- access -------------------------------------------------------------------------------------------------


def test_only_admins_decide(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    _row(fx, master, "requested")
    customer = auth(register(client, "client")["access_token"])
    before = _state()
    for action in ACTIONS:
        url = _url(master.id, SPEC, action)
        body = {"expected_version": 1, **({"reason": "x"} if action != "approve" else {})}
        assert client.post(url, json=body).status_code == 401
        assert (
            client.post(url, json=body, headers=master.h).status_code == 403
        )  # not on their own application
        assert client.post(url, json=body, headers=customer).status_code == 403
    assert _state() == before


# --- transitions --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", SPECIALISATION_STATUSES)
@pytest.mark.parametrize("action", ACTIONS)
def test_every_transition(client: TestClient, fx: Fx, status: str, action: str) -> None:
    master = _master(client)
    _row(fx, master, status)
    before = _state()
    resp = _post(client, fx, action, master.id)
    expected = ALLOWED.get((status, action))
    if expected is None:  # rejected/revoked are final; withdrawn and repeats are refused too
        assert _error(resp) == (409, "INVALID_TRANSITION")
        assert resp.json()["error"]["details"] == {"status": status, "version": 1, "action": action}
        assert _state() == before
        return
    assert resp.status_code == 200, resp.text
    spec = _spec(resp.json())
    assert (spec["status"], spec["version"], spec["decided_by"]) == (expected, 2, str(fx.admin_id))
    assert spec["decision_reason"] == (None if action == "approve" else "Pamatojums")
    [entry] = _log(master)
    assert entry.action == f"master.specialisation.{expected}" and entry.actor_id == fx.admin_id
    assert entry.before is not None and entry.after is not None
    assert (entry.before["status"], entry.after["status"]) == (status, expected)
    assert entry.after["specialisation_id"] == str(SPEC) and entry.after["decided_by"] == str(fx.admin_id)
    with SessionLocal() as db:
        [event] = db.scalars(
            select(DomainEvent).where(DomainEvent.event_type.like("master.specialisation.%"))
        ).all()
    assert event.event_type == entry.action and event.aggregate_id == master.id
    assert "decision_reason" not in event.payload


# --- input --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["reject", "revoke"])
@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": 1},
        {"expected_version": 1, "reason": ""},
        {"expected_version": 1, "reason": "   "},
        {"expected_version": 1, "reason": None},
        {"expected_version": 1, "reason": "x" * 1001},
        {"reason": "Pamatojums"},
        {"expected_version": 0, "reason": "Pamatojums"},
        {"expected_version": 1, "reason": "Pamatojums", "status": "approved"},
    ],
)
def test_reject_and_revoke_need_a_reason(
    client: TestClient, fx: Fx, action: str, body: dict[str, Any]
) -> None:
    master = _master(client)
    _row(fx, master, "requested" if action == "reject" else "approved")
    before = _state()
    assert client.post(_url(master.id, SPEC, action), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


@pytest.mark.parametrize(
    "body", [{"expected_version": 1, "reason": "x"}, {}, {"expected_version": 1, "x": 1}]
)
def test_approve_takes_no_reason(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client)
    _row(fx, master, "requested")
    before = _state()
    assert client.post(_url(master.id, SPEC, "approve"), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


# --- versions, repeats, ownership ---------------------------------------------------------------------------


def test_stale_or_repeated_decisions_change_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    _row(fx, master, "requested")
    stale = _post(client, fx, "approve", master.id, version=4)
    assert _error(stale) == (409, "VERSION_CONFLICT")
    assert stale.json()["error"]["details"] == {"status": "requested", "version": 1}
    assert _post(client, fx, "approve", master.id).status_code == 200
    before = _state()
    for action in ACTIONS:  # repeating with the old version
        assert _error(_post(client, fx, action, master.id)) == (409, "VERSION_CONFLICT")
    assert _error(_post(client, fx, "approve", master.id, version=2)) == (409, "INVALID_TRANSITION")
    assert _state() == before
    assert _post(client, fx, "revoke", master.id, version=2).status_code == 200
    before = _state()
    for action in ACTIONS:  # no second revocation, no re-approval
        assert _error(_post(client, fx, action, master.id, version=3)) == (409, "INVALID_TRANSITION")
    assert _state() == before
    assert [e.action for e in _log(master)] == [
        "master.specialisation.approved",
        "master.specialisation.revoked",
    ]


def test_unknown_foreign_or_deleted(client: TestClient, fx: Fx) -> None:
    owner, other, gone = _master(client), _master(client), _master(client)
    _row(fx, owner, "requested")
    _row(fx, other, "requested", OTHER_SPEC)
    _row(fx, gone, "requested")
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == gone.user_id).values(deleted_at=T0))
        db.commit()
    before = _state()
    attempts = [
        (other.id, SPEC, "SPECIALISATION_NOT_FOUND"),  # the owner's application under another master
        (owner.id, OTHER_SPEC, "SPECIALISATION_NOT_FOUND"),  # another master's application under the owner
        (owner.id, uuid.uuid4(), "SPECIALISATION_NOT_FOUND"),
        (owner.id, seed_id("cm-s03"), "SPECIALISATION_NOT_FOUND"),  # a real catalogue entry never requested
        (uuid.uuid4(), SPEC, "MASTER_NOT_FOUND"),
        (owner.user_id, SPEC, "MASTER_NOT_FOUND"),  # user ID instead of master ID
        (gone.id, SPEC, "MASTER_NOT_FOUND"),  # deleted account
    ]
    for master_id, spec_id, code in attempts:
        for action in ACTIONS:
            assert _error(_post(client, fx, action, master_id, spec_id)) == (404, code), (master_id, spec_id)
    assert (
        client.post(
            _url(owner.id, "x", "approve"), json={"expected_version": 1}, headers=fx.admin
        ).status_code
        == 422
    )
    assert _state() == before


@pytest.mark.parametrize("catalogue_status", ["inactive", "archived"])
def test_approval_needs_the_specialisation_still_offered(
    client: TestClient, fx: Fx, catalogue_status: str
) -> None:
    master = _master(client)
    _row(fx, master, "requested")
    with SessionLocal() as db:
        db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == SPEC)
            .values(status=catalogue_status)
        )
        db.commit()
    before = _state()
    resp = _post(client, fx, "approve", master.id)
    assert _error(resp) == (409, "SPECIALISATION_NOT_AVAILABLE")
    assert resp.json()["error"]["details"] == {"catalogue_status": catalogue_status}
    assert _state() == before
    # Rejecting stays possible, so the application does not stay pending forever.
    assert _post(client, fx, "reject", master.id).status_code == 200


# --- effects and history ------------------------------------------------------------------------------------


def test_approval_grants_nothing_else_and_revocation_excludes_at_once(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    with SessionLocal() as db:
        qualification = Qualification(name="Sertifikāts", status="active")
        db.add(qualification)
        db.execute(update(CatalogueService).where(CatalogueService.id == SERVICE).values(status="inactive"))
        db.execute(
            update(MasterProfile)
            .where(MasterProfile.id == master.id)
            .values(approval_status="approved", decided_by=fx.admin_id, decided_at=T0)
        )
        db.commit()
    _row(fx, master, "requested")
    with SessionLocal() as db:
        db.add(MasterCompetency(master_id=master.id, service_id=SERVICE))
        db.add(MasterQualification(master_id=master.id, qualification_id=qualification.id))
        db.commit()

    approved = _post(client, fx, "approve", master.id).json()
    [competency] = approved["competencies"]
    [submission] = approved["qualifications"]
    assert (competency["status"], competency["version"], competency["decided_by"]) == ("declared", 1, None)
    assert (submission["status"], submission["version"]) == ("submitted", 1)
    assert [r["code"] for r in competency["reasons"]] == ["COMPETENCY_NOT_VERIFIED"]

    with SessionLocal() as db:
        db.execute(
            update(MasterCompetency)
            .where(MasterCompetency.master_id == master.id)
            .values(status="verified", decided_by=fx.admin_id, decided_at=T0)
        )
        db.commit()
        assert eligibility.eligible_master_ids(db, SERVICE) == [master.id]

    revoked = _post(client, fx, "revoke", master.id, version=2, reason="Licence apturēta").json()
    [competency] = revoked["competencies"]
    assert competency["status"] == "verified" and competency["eligible"] is False  # row unchanged, excluded
    assert [r["code"] for r in competency["reasons"]] == ["SPECIALISATION_NOT_APPROVED"]
    with SessionLocal() as db:
        assert eligibility.eligible_master_ids(db, SERVICE) == []


def test_history_survives_reapplication(client: TestClient, fx: Fx) -> None:
    """Rejected/revoked are final for the row; only the master's re-application starts a new review."""
    master = _master(client)
    request = {"specialisation_id": str(SPEC)}
    assert client.post("/api/v1/master/specialisations", json=request, headers=master.h).status_code == 201
    _post(client, fx, "reject", master.id, reason="Nepietiek pieredzes")
    assert client.post("/api/v1/master/specialisations", json=request, headers=master.h).status_code == 201
    _post(client, fx, "approve", master.id, version=3)
    revoked = _post(client, fx, "revoke", master.id, version=4, reason="Sūdzības")
    assert _spec(revoked.json())["decision_reason"] == "Sūdzības"

    trail = [(e.action, e.before, e.after, e.reason) for e in _log(master)]
    assert [t[0] for t in trail] == [
        "master.specialisation.requested",
        "master.specialisation.rejected",
        "master.specialisation.requested",
        "master.specialisation.approved",
        "master.specialisation.revoked",
    ]
    for previous, current in zip(trail, trail[1:], strict=False):
        assert previous[2] == current[1]  # an unbroken chain: nothing changed between logged states
    assert trail[1][2]["decision_reason"] == "Nepietiek pieredzes" and trail[1][3] == "Nepietiek pieredzes"
    assert trail[2][1]["decision_reason"] == "Nepietiek pieredzes"  # the rejection is still readable
    assert trail[4][2]["decision_reason"] == "Sūdzības" and trail[3][2]["decision_reason"] is None


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _decide(fx: Fx, master_id: uuid.UUID, action: str, version: int) -> None:
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        decision = master_admin.Decision(action, version, "Pamatojums")  # type: ignore[arg-type]
        master_admin.decide_specialisation(db, admin, master_id, SPEC, decision)


def test_parallel_opposite_decisions(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    _row(fx, master, "requested")
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
    assert len([r for r in results if r in ACTIONS]) == 1 and results.count("VERSION_CONFLICT") == n - 1
    [entry] = _log(master)
    assert entry.after is not None and entry.after["version"] == 2


@pytest.mark.parametrize(
    ("status", "held", "attempt"),
    [
        ("requested", "rejected", "approve"),  # another admin rejects while we approve
        ("requested", "withdrawn", "approve"),  # the master withdraws while we approve
        ("approved", "revoked", "revoke"),  # two admins revoke at once
    ],
)
def test_decision_waits_for_the_master_row_lock(
    client: TestClient, fx: Fx, status: str, held: str, attempt: str
) -> None:
    """Without `FOR UPDATE` the decision reads the old version and overwrites the other change: this fails."""
    master = _master(client)
    _row(fx, master, status)
    other_change: dict[str, Any] = {"status": held, "version": 2, "decision_reason": "Cits"}
    if held != "withdrawn":
        other_change |= {"decided_by": fx.admin_id, "decided_at": datetime.now(UTC)}
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == master.id).with_for_update())
        holder.execute(
            update(MasterSpecialisation)
            .where(MasterSpecialisation.master_id == master.id)
            .values(**other_change)
        )

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
        row = db.get(MasterSpecialisation, (master.id, SPEC))
        assert row is not None and {key: getattr(row, key) for key in other_change} == other_change
    assert _log(master) == []


def test_master_withdrawal_and_admin_decision_serialise(client: TestClient, fx: Fx) -> None:
    """The master's own write takes the same lock; whichever runs second sees the first."""
    master = _master(client)
    _row(fx, master, "requested")
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def admin() -> None:
        barrier.wait()
        try:
            _decide(fx, master.id, "approve", 1)
            results["admin"] = "ok"
        except AppError as exc:
            results["admin"] = exc.code

    def owner() -> None:
        barrier.wait()
        with SessionLocal() as db:
            user = db.get(User, master.user_id)
            assert user is not None
            try:
                svc.withdraw_specialisation(db, user, SPEC)
                results["master"] = "ok"
            except AppError as exc:
                results["master"] = exc.code

    threads = [threading.Thread(target=admin), threading.Thread(target=owner)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    with SessionLocal() as db:
        row = db.get(MasterSpecialisation, (master.id, SPEC))
        assert row is not None
    if results["admin"] == "ok":
        assert (results["master"], row.status) == ("CANNOT_WITHDRAW", "approved")
    else:
        assert (results, row.status) == ({"admin": "VERSION_CONFLICT", "master": "ok"}, "withdrawn")
    assert row.version == 2 and len(_log(master)) == 1
