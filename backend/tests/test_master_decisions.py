"""Admin decision core (step 4.4.1): transitions, versions, reasons, history and concurrent decisions."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models import (
    AuditLog,
    DomainEvent,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.master import (
    APPROVAL_STATUSES,
    COMPETENCY_STATUSES,
    QUALIFICATION_STATUSES,
    SPECIALISATION_STATUSES,
)
from app.services import master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from app.services.master_admin import Decision
from tests.conftest import register

SPEC = seed_id("cm-s01")
SERVICE = seed_id("cm-s01-1")
NUMBER = "LV-CERT-123456"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

STATUSES = {
    "profile": APPROVAL_STATUSES,
    "specialisation": SPECIALISATION_STATUSES,
    "competency": COMPETENCY_STATUSES,
    "qualification": QUALIFICATION_STATUSES,
}
ACTIONS = ("approve", "reject", "revoke", "verify")
# Written independently of master_admin.TRANSITIONS, from the approved plan and owner decisions 2026-11-02.
ALLOWED = {
    ("profile", "pending_approval", "approve"): "approved",
    ("profile", "rejected", "approve"): "approved",
    ("profile", "pending_approval", "reject"): "rejected",
    ("specialisation", "requested", "approve"): "approved",
    ("specialisation", "requested", "reject"): "rejected",
    ("specialisation", "approved", "revoke"): "revoked",
    ("competency", "declared", "verify"): "verified",
    ("competency", "declared", "reject"): "rejected",
    ("competency", "verified", "revoke"): "revoked",
    ("qualification", "submitted", "verify"): "verified",
    ("qualification", "submitted", "reject"): "rejected",
    ("qualification", "verified", "revoke"): "revoked",
}
DECIDED = {"approved", "rejected", "revoked", "verified"}


@dataclass
class Fx:
    admin_id: uuid.UUID
    master_id: uuid.UUID
    master_user_id: uuid.UUID
    qualification_id: uuid.UUID


def _new_master(client: TestClient) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.UUID(register(client, "master")["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
    assert master_id is not None
    return master_id, user_id


@pytest.fixture
def fx(client: TestClient) -> Iterator[Fx]:
    master_id, user_id = _new_master(client)
    with SessionLocal() as db:
        seed_catalogue(db)
        admin = User(role="admin", email="adm@example.lv", password_hash="x", full_name="Admin")
        qualification = Qualification(name="Elektrodrošība", status="active")
        db.add_all([admin, qualification])
        db.commit()
        yield Fx(admin.id, master_id, user_id, qualification.id)


def _decider(fx: Fx, status: str) -> dict[str, Any]:
    return {"decided_by": fx.admin_id, "decided_at": NOW} if status in DECIDED else {}


def _make(fx: Fx, kind: str, status: str, master_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """A row of `kind` in `status` (version 1); returns its key."""
    master_id = master_id or fx.master_id
    with SessionLocal() as db:
        if kind == "profile":
            db.execute(
                update(MasterProfile)
                .where(MasterProfile.id == master_id)
                .values(approval_status=status, **_decider(fx, status))
            )
            db.commit()
            return None
        if kind == "specialisation":
            db.add(
                MasterSpecialisation(
                    master_id=master_id, specialisation_id=SPEC, status=status, **_decider(fx, status)
                )
            )
            db.commit()
            return SPEC
        if kind == "competency":
            db.add(MasterSpecialisation(master_id=master_id, specialisation_id=SPEC))
            db.add(
                MasterCompetency(
                    master_id=master_id, service_id=SERVICE, status=status, **_decider(fx, status)
                )
            )
            db.commit()
            return SERVICE
        row = MasterQualification(
            master_id=master_id,
            qualification_id=fx.qualification_id,
            status=status,
            document_number=NUMBER,
            valid_until=date(2030, 1, 31),
            **_decider(fx, status),
        )
        db.add(row)
        db.commit()
        return row.id


def _decide(
    fx: Fx,
    kind: str,
    key: uuid.UUID | None,
    action: str,
    version: int = 1,
    reason: str | None = "Iemesls",
    *,
    admin_id: uuid.UUID | None = None,
    master_id: uuid.UUID | None = None,
    precondition: master_admin.Precondition | None = None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        admin = db.get(User, admin_id or fx.admin_id)
        assert admin is not None
        row = master_admin.decide(
            db,
            admin,
            master_id or fx.master_id,
            kind,  # type: ignore[arg-type]
            key,
            Decision(action, version, reason),  # type: ignore[arg-type]
            precondition,
        )
        return svc.snapshot(row)


def _error(call: Any) -> AppError:
    with pytest.raises(AppError) as exc:
        call()
    return exc.value


def _state(fx: Fx) -> tuple[Any, ...]:
    """Every column of the master's profile and capability rows, plus the audit and event counts."""
    with SessionLocal() as db:
        rows = tuple(
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model, column in (
                (MasterProfile, MasterProfile.id),
                (MasterSpecialisation, MasterSpecialisation.master_id),
                (MasterCompetency, MasterCompetency.master_id),
                (MasterQualification, MasterQualification.master_id),
            )
            for row in db.scalars(select(model).where(column == fx.master_id))
        )
        return (
            rows,
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _audit(fx: Fx, action: str | None = None) -> list[AuditLog]:
    with SessionLocal() as db:
        # Only capability changes: registration writes its own entries.
        query = (
            select(AuditLog)
            .where(AuditLog.action.like("master.%"))
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        if action:
            query = query.where(AuditLog.action == action)
        return list(db.scalars(query))


# --- transitions --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status", "action"),
    [
        (kind, status, action)
        for kind, statuses in STATUSES.items()
        for status in statuses
        for action in ACTIONS
    ],
)
def test_every_transition(fx: Fx, kind: str, status: str, action: str) -> None:
    key = _make(fx, kind, status)
    expected = ALLOWED.get((kind, status, action))
    if expected is None:
        before = _state(fx)
        error = _error(lambda: _decide(fx, kind, key, action))
        assert (error.code, error.status_code) == ("INVALID_TRANSITION", 409)
        assert error.details == {"status": status, "version": 1, "action": action}
        assert _state(fx) == before
        return

    after = _decide(fx, kind, key, action)
    status_field = "approval_status" if kind == "profile" else "status"
    assert after[status_field] == expected
    assert after["decided_by"] == str(fx.admin_id)
    assert after["decided_at"] is not None and after["decision_reason"] == "Iemesls"
    assert after["version"] == 2
    [entry] = _audit(fx)
    assert entry.action == f"master.{kind}.{expected}"
    assert (entry.actor_type, entry.actor_id, entry.reason) == ("user", fx.admin_id, "Iemesls")
    assert entry.before is not None and entry.before[status_field] == status and entry.after == after
    with SessionLocal() as db:
        [event] = db.scalars(select(DomainEvent).where(DomainEvent.event_type.like("master.%"))).all()
    assert event.event_type == entry.action and "decision_reason" not in event.payload


def test_rejected_and_revoked_are_final_until_the_master_reapplies(fx: Fx) -> None:
    """Owner decision 2026-11-02: no rejected/revoked → approved; only a re-application reopens a review."""
    _make(fx, "specialisation", "requested")
    _decide(fx, "specialisation", SPEC, "reject", 1)
    assert _error(lambda: _decide(fx, "specialisation", SPEC, "approve", 2)).code == "INVALID_TRANSITION"
    with SessionLocal() as db:
        master_user = db.get(User, fx.master_user_id)
        assert master_user is not None
        svc.request_specialisation(db, master_user, SPEC)
    assert _decide(fx, "specialisation", SPEC, "approve", 3)["status"] == "approved"
    _decide(fx, "specialisation", SPEC, "revoke", 4)
    assert _error(lambda: _decide(fx, "specialisation", SPEC, "approve", 5)).code == "INVALID_TRANSITION"


# --- reasons ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status", "action"),
    [
        ("profile", "pending_approval", "reject"),
        ("specialisation", "requested", "reject"),
        ("specialisation", "approved", "revoke"),
        ("competency", "declared", "reject"),
        ("competency", "verified", "revoke"),
        ("qualification", "submitted", "reject"),
        ("qualification", "verified", "revoke"),
    ],
)
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_required(fx: Fx, kind: str, status: str, action: str, reason: str | None) -> None:
    key = _make(fx, kind, status)
    before = _state(fx)
    error = _error(lambda: _decide(fx, kind, key, action, reason=reason))
    assert (error.code, error.status_code) == ("REASON_REQUIRED", 422)
    assert _state(fx) == before


@pytest.mark.parametrize(
    ("kind", "status", "action"),
    [
        ("profile", "pending_approval", "approve"),
        ("specialisation", "requested", "approve"),
        ("competency", "declared", "verify"),
        ("qualification", "submitted", "verify"),
    ],
)
def test_reason_optional(fx: Fx, kind: str, status: str, action: str) -> None:
    key = _make(fx, kind, status)
    assert _decide(fx, kind, key, action, reason="  ")["decision_reason"] is None


# --- versions, repeats and access ---------------------------------------------------------------------------


def test_stale_or_repeated_decision_changes_nothing(fx: Fx) -> None:
    _make(fx, "specialisation", "requested")
    stale = _error(lambda: _decide(fx, "specialisation", SPEC, "approve", version=0))
    assert (stale.code, stale.status_code) == ("VERSION_CONFLICT", 409)
    assert stale.details == {"status": "requested", "version": 1}
    _decide(fx, "specialisation", SPEC, "approve")
    before = _state(fx)
    repeated = _error(lambda: _decide(fx, "specialisation", SPEC, "approve"))
    assert (repeated.code, repeated.details) == ("VERSION_CONFLICT", {"status": "approved", "version": 2})
    assert _state(fx) == before
    assert len(_audit(fx, "master.specialisation.approved")) == 1


def test_unknown_or_foreign_records_are_not_found(client: TestClient, fx: Fx) -> None:
    other_master, _ = _new_master(client)
    foreign = _make(fx, "qualification", "submitted", master_id=other_master)
    before = _state(fx)
    assert _error(lambda: _decide(fx, "profile", None, "approve", master_id=uuid.uuid4())).code == (
        "MASTER_NOT_FOUND"
    )
    assert _error(lambda: _decide(fx, "specialisation", SPEC, "approve")).code == "SPECIALISATION_NOT_FOUND"
    assert _error(lambda: _decide(fx, "competency", SERVICE, "verify")).code == "COMPETENCY_NOT_FOUND"
    # Another master's submission under this master's ID: same answer as an unknown one.
    assert _error(lambda: _decide(fx, "qualification", foreign, "verify")).code == "QUALIFICATION_NOT_FOUND"
    assert (
        _error(lambda: _decide(fx, "qualification", uuid.uuid4(), "verify")).code == "QUALIFICATION_NOT_FOUND"
    )
    assert _state(fx) == before
    with SessionLocal() as db:
        assert (
            db.scalar(select(MasterQualification.status).where(MasterQualification.id == foreign))
            == "submitted"
        )


def test_only_an_admin_other_than_the_master_decides(fx: Fx) -> None:
    key = _make(fx, "specialisation", "requested")
    before = _state(fx)
    # The master's own account.
    error = _error(lambda: _decide(fx, "specialisation", key, "approve", admin_id=fx.master_user_id))
    assert (error.code, error.status_code) == ("DECISION_FORBIDDEN", 403)
    # An admin account that is the master itself (not possible with exclusive roles today; guarded anyway).
    with SessionLocal() as db:
        impostor = User(
            id=fx.master_user_id, role="admin", email="x@example.lv", password_hash="x", full_name="X"
        )
        with pytest.raises(AppError) as exc:
            master_admin.decide(db, impostor, fx.master_id, "specialisation", key, Decision("approve", 1))
        assert exc.value.code == "DECISION_FORBIDDEN"
    assert _state(fx) == before


def test_failing_precondition_changes_nothing(fx: Fx) -> None:
    key = _make(fx, "competency", "declared")
    before = _state(fx)

    def blocked(master: MasterProfile, row: master_admin.Row) -> None:
        assert master.id == fx.master_id and isinstance(row, MasterCompetency)
        raise AppError("SPECIALISATION_NOT_APPROVED", "Blocked.", 409)

    assert _error(lambda: _decide(fx, "competency", key, "verify", precondition=blocked)).code == (
        "SPECIALISATION_NOT_APPROVED"
    )
    assert _state(fx) == before


# --- history ------------------------------------------------------------------------------------------------


def test_every_earlier_decision_stays_in_the_audit_trail(fx: Fx) -> None:
    """The row is reused on re-application; each decision's decider, time and reason survive in audit_log."""
    with SessionLocal() as db:
        master_user = db.get(User, fx.master_user_id)
        assert master_user is not None
        svc.request_specialisation(db, master_user, SPEC)
    approved = _decide(fx, "specialisation", SPEC, "approve", 1, reason=None)
    revoked = _decide(fx, "specialisation", SPEC, "revoke", 2, reason="Licence apturēta")
    with SessionLocal() as db:
        master_user = db.get(User, fx.master_user_id)
        assert master_user is not None
        svc.request_specialisation(db, master_user, SPEC)
    rejected = _decide(fx, "specialisation", SPEC, "reject", 4, reason="Nepietiek pieredzes")

    trail = [(e.action, e.before, e.after) for e in _audit(fx)]
    assert [action for action, _, _ in trail] == [
        "master.specialisation.requested",
        "master.specialisation.approved",
        "master.specialisation.revoked",
        "master.specialisation.requested",
        "master.specialisation.rejected",
    ]
    assert trail[1][2] == approved and trail[2] == (trail[2][0], approved, revoked)
    assert trail[3][1] == revoked  # the re-application keeps the revocation readable
    assert trail[4][2] == rejected
    assert revoked["decision_reason"] == "Licence apturēta" and revoked["decided_by"] == str(fx.admin_id)
    assert approved["decided_at"] is not None and approved["decided_at"] != revoked["decided_at"]


def test_qualification_is_decided_exactly_as_submitted(fx: Fx) -> None:
    """Owner decision 2026-11-02: verification never changes the document data."""
    key = _make(fx, "qualification", "submitted")

    def document(db: Any) -> tuple[Any, ...]:
        row = db.get(MasterQualification, key)
        return (row.document_number, row.valid_until, row.qualification_id, row.submitted_at)

    with SessionLocal() as db:
        original = document(db)
    _decide(fx, "qualification", key, "verify", reason=None)
    _decide(fx, "qualification", key, "revoke", 2, reason="Viltots")
    with SessionLocal() as db:
        assert document(db) == original
    for entry in _audit(fx):
        assert NUMBER not in str(entry.after) and entry.after["document_number_last4"] == "3456"


def test_profile_decisions_need_a_decider_in_the_database(fx: Fx) -> None:
    for status in ("approved", "rejected"):
        with SessionLocal() as db:
            with pytest.raises(IntegrityError, match="decision_recorded"):
                db.execute(
                    update(MasterProfile)
                    .where(MasterProfile.id == fx.master_id)
                    .values(approval_status=status)
                )
            db.rollback()


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "status", "actions"),
    [
        ("profile", "pending_approval", ("approve", "reject")),
        ("specialisation", "requested", ("approve", "reject")),
        ("competency", "declared", ("verify", "reject")),
        ("qualification", "submitted", ("verify", "reject")),
        ("qualification", "verified", ("revoke", "revoke")),
    ],
)
def test_parallel_decisions_on_one_record(fx: Fx, kind: str, status: str, actions: tuple[str, str]) -> None:
    key = _make(fx, kind, status)
    threads_n = 6
    barrier = threading.Barrier(threads_n)
    results: list[str] = []

    def run(action: str) -> None:
        barrier.wait()
        try:
            _decide(fx, kind, key, action)
            results.append(f"ok:{action}")
        except AppError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=run, args=(actions[i % 2],)) for i in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    winners = [r for r in results if r.startswith("ok:")]
    assert len(winners) == 1 and results.count("VERSION_CONFLICT") == threads_n - 1
    expected = ALLOWED[(kind, status, winners[0].removeprefix("ok:"))]
    [entry] = _audit(fx)
    assert entry.action == f"master.{kind}.{expected}"
    status_field = "approval_status" if kind == "profile" else "status"
    assert entry.after is not None and entry.after[status_field] == expected and entry.after["version"] == 2


def test_decision_waits_for_the_master_row_lock(fx: Fx) -> None:
    """A concurrent write of the master (a withdrawal under the same lock) is seen, never overwritten."""
    _make(fx, "specialisation", "requested")
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == fx.master_id).with_for_update())
        holder.execute(
            update(MasterSpecialisation)
            .where(MasterSpecialisation.master_id == fx.master_id)
            .values(status="withdrawn", version=2)
        )

        def run() -> None:
            try:
                _decide(fx, "specialisation", SPEC, "approve")
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
        row = db.get(MasterSpecialisation, (fx.master_id, SPEC))
        assert row is not None and (row.status, row.version, row.decided_by) == ("withdrawn", 2, None)
    assert _audit(fx) == []


def test_concurrent_decisions_on_different_records_of_one_master_all_apply(fx: Fx) -> None:
    _make(fx, "competency", "declared")  # also creates the requested specialisation
    submission = _make(fx, "qualification", "submitted")
    jobs = [
        ("profile", None, "approve"),
        ("specialisation", SPEC, "approve"),
        ("competency", SERVICE, "verify"),
        ("qualification", submission, "verify"),
    ]
    barrier = threading.Barrier(len(jobs))
    errors: list[Exception] = []

    def run(kind: str, key: uuid.UUID | None, action: str) -> None:
        barrier.wait()
        try:
            _decide(fx, kind, key, action)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(_audit(fx)) == 4
