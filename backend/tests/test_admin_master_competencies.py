"""Admin decisions on master competencies (step 4.4.6, R-MST-09/11/14, owner decisions 2026-11-02)."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.business_time import business_today
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
from app.models.catalogue import service_qualifications
from app.models.master import COMPETENCY_STATUSES
from app.services import eligibility, master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register

SPEC = seed_id("cm-s01")
SERVICE = seed_id("cm-s01-1")  # regulated through a configured requirement
PLAIN_SERVICE = seed_id("cm-s01-2")  # no requirement
FOREIGN_SERVICE = seed_id("cm-s02-1")  # another specialisation, never declared
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
ACTIONS = ("verify", "reject", "revoke")
ALLOWED = {
    ("declared", "verify"): "verified",
    ("declared", "reject"): "rejected",
    ("verified", "revoke"): "revoked",
}
DECIDED = ("verified", "rejected", "revoked")


@dataclass
class M:
    id: uuid.UUID
    user_id: uuid.UUID
    h: dict[str, str]


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID
    today: date


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([SERVICE, PLAIN_SERVICE, FOREIGN_SERVICE]))
            .values(status="inactive")
        )
        qualification = Qualification(name="Elektrodrošība", status="active", requires_expiry_date=True)
        db.add(qualification)
        db.flush()
        db.execute(
            service_qualifications.insert().values(service_id=SERVICE, qualification_id=qualification.id)
        )
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, qualification.id, business_today(db))


def _decided(fx: Fx) -> dict[str, Any]:
    return {"decided_by": fx.admin_id, "decided_at": T0}


def _master(client: TestClient, fx: Fx, *, ready: bool = True) -> M:
    """A master that meets every verification condition for SERVICE (unless `ready` is False)."""
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
        assert master_id is not None
        if ready:
            db.execute(
                update(MasterProfile)
                .where(MasterProfile.id == master_id)
                .values(approval_status="approved", **_decided(fx))
            )
            db.add(
                MasterSpecialisation(
                    master_id=master_id, specialisation_id=SPEC, status="approved", **_decided(fx)
                )
            )
            db.add(
                MasterQualification(
                    master_id=master_id,
                    qualification_id=fx.qualification_id,
                    status="verified",
                    valid_until=fx.today + timedelta(days=100),
                    **_decided(fx),
                )
            )
        db.commit()
    return M(master_id, user_id, auth(body["access_token"]))


def _competency(fx: Fx, master: M, status: str = "declared", service_id: uuid.UUID = SERVICE) -> None:
    with SessionLocal() as db:
        db.add(
            MasterCompetency(
                master_id=master.id,
                service_id=service_id,
                status=status,
                decision_reason="Vecs iemesls" if status in ("rejected", "revoked") else None,
                **(_decided(fx) if status in DECIDED else {}),
            )
        )
        db.commit()


def _url(master_id: Any, service_id: Any, action: str) -> str:
    return f"/api/v1/admin/masters/{master_id}/competencies/{service_id}/{action}"


def _post(
    client: TestClient,
    fx: Fx,
    action: str,
    master_id: Any,
    service_id: Any = SERVICE,
    version: int = 1,
    reason: str = "Pamatojums",
) -> Any:
    body: dict[str, Any] = {"expected_version": version}
    if action != "verify":
        body["reason"] = reason
    return client.post(_url(master_id, service_id, action), json=body, headers=fx.admin)


def _state() -> tuple[Any, ...]:
    """Every master row (all columns) plus all audit entries and events: any change shows up here."""
    with SessionLocal() as db:
        rows = [
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (MasterProfile, MasterSpecialisation, MasterCompetency, MasterQualification)
            for row in db.scalars(select(model))
        ]
        return (
            sorted(rows, key=repr),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _log(master: M) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "master_competency", AuditLog.entity_id == master.id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _error(resp: Any) -> tuple[int, str]:
    return resp.status_code, resp.json()["error"]["code"]


def _competency_out(body: dict[str, Any], service_id: uuid.UUID = SERVICE) -> dict[str, Any]:
    [found] = [c for c in body["competencies"] if c["service_id"] == str(service_id)]
    return found


def _set(model: Any, where: Any, **values: Any) -> None:
    with SessionLocal() as db:
        db.execute(update(model).where(where).values(**values))
        db.commit()


# --- access and identifiers ---------------------------------------------------------------------------------


def test_only_admins_decide(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    customer = auth(register(client, "client")["access_token"])
    before = _state()
    for action in ACTIONS:
        body = {"expected_version": 1, **({"reason": "x"} if action != "verify" else {})}
        url = _url(master.id, SERVICE, action)
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers=master.h).status_code == 403  # not on their own competency
        assert client.post(url, json=body, headers=customer).status_code == 403
    assert _state() == before


def test_unknown_foreign_or_deleted(client: TestClient, fx: Fx) -> None:
    owner, other, gone = _master(client, fx), _master(client, fx), _master(client, fx)
    _competency(fx, owner)
    _competency(fx, other, service_id=PLAIN_SERVICE)
    _competency(fx, gone)
    _set(User, User.id == gone.user_id, deleted_at=T0)
    before = _state()
    attempts = [
        (other.id, SERVICE, "COMPETENCY_NOT_FOUND"),  # the owner's competency under another master
        (owner.id, PLAIN_SERVICE, "COMPETENCY_NOT_FOUND"),  # another master's competency under the owner
        (owner.id, FOREIGN_SERVICE, "COMPETENCY_NOT_FOUND"),  # a real service the master never declared
        (owner.id, uuid.uuid4(), "COMPETENCY_NOT_FOUND"),  # no such service
        (uuid.uuid4(), SERVICE, "MASTER_NOT_FOUND"),
        (owner.user_id, SERVICE, "MASTER_NOT_FOUND"),  # user ID instead of master ID
        (gone.id, SERVICE, "MASTER_NOT_FOUND"),  # deleted account
    ]
    for master_id, service_id, code in attempts:
        for action in ACTIONS:
            assert _error(_post(client, fx, action, master_id, service_id)) == (404, code), (
                master_id,
                service_id,
            )
    assert (
        client.post(_url(owner.id, "x", "verify"), json={"expected_version": 1}, headers=fx.admin).status_code
        == 422
    )
    assert _state() == before


# --- transitions and input ----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", COMPETENCY_STATUSES)
@pytest.mark.parametrize("action", ACTIONS)
def test_every_transition(client: TestClient, fx: Fx, status: str, action: str) -> None:
    master = _master(client, fx)
    _competency(fx, master, status)
    before = _state()
    resp = _post(client, fx, action, master.id)
    expected = ALLOWED.get((status, action))
    if expected is None:  # rejected/revoked are final; repeats and withdrawn rows are refused too
        assert _error(resp) == (409, "INVALID_TRANSITION")
        assert resp.json()["error"]["details"] == {"status": status, "version": 1, "action": action}
        assert _state() == before
        return
    assert resp.status_code == 200, resp.text
    out = _competency_out(resp.json())
    assert (out["status"], out["version"], out["decided_by"]) == (expected, 2, str(fx.admin_id))
    assert out["decision_reason"] == (None if action == "verify" else "Pamatojums")
    assert out["eligible"] is (expected == "verified")
    [entry] = _log(master)
    assert entry.action == f"master.competency.{expected}" and entry.actor_id == fx.admin_id
    assert entry.before is not None and entry.after is not None
    assert (entry.before["status"], entry.after["status"]) == (status, expected)
    assert entry.after["service_id"] == str(SERVICE)
    assert entry.after["decision_reason"] == entry.reason == (None if action == "verify" else "Pamatojums")
    with SessionLocal() as db:
        [event] = db.scalars(
            select(DomainEvent).where(DomainEvent.event_type.like("master.competency.%"))
        ).all()
    assert event.event_type == entry.action and event.aggregate_id == master.id
    assert "decision_reason" not in event.payload and "Pamatojums" not in str(event.payload)


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
        {"expected_version": 1, "reason": "Pamatojums", "status": "verified"},
    ],
)
def test_reject_and_revoke_need_a_reason(
    client: TestClient, fx: Fx, action: str, body: dict[str, Any]
) -> None:
    master = _master(client, fx)
    _competency(fx, master, "declared" if action == "reject" else "verified")
    before = _state()
    assert client.post(_url(master.id, SERVICE, action), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


def test_reason_is_trimmed_and_may_be_1000_chars(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    resp = _post(client, fx, "reject", master.id, reason="  " + "ā" * 1000 + "  ")
    assert resp.status_code == 200 and _competency_out(resp.json())["decision_reason"] == "ā" * 1000


@pytest.mark.parametrize(
    "body", [{"expected_version": 1, "reason": "x"}, {}, {"expected_version": 1, "x": 1}]
)
def test_verify_takes_no_reason(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    before = _state()
    assert client.post(_url(master.id, SERVICE, "verify"), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


def test_stale_or_repeated_decisions_change_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    stale = _post(client, fx, "verify", master.id, version=3)
    assert _error(stale) == (409, "VERSION_CONFLICT")
    assert stale.json()["error"]["details"] == {"status": "declared", "version": 1}
    assert _post(client, fx, "verify", master.id).status_code == 200
    before = _state()
    for action in ACTIONS:  # repeating with the old version
        assert _error(_post(client, fx, action, master.id)) == (409, "VERSION_CONFLICT")
    assert _error(_post(client, fx, "verify", master.id, version=2)) == (409, "INVALID_TRANSITION")
    assert _state() == before
    assert _post(client, fx, "revoke", master.id, version=2).status_code == 200
    before = _state()
    for action in ACTIONS:  # no second revocation, no re-verification
        assert _error(_post(client, fx, action, master.id, version=3)) == (409, "INVALID_TRANSITION")
    assert _state() == before
    assert [e.action for e in _log(master)] == ["master.competency.verified", "master.competency.revoked"]


# --- verification conditions --------------------------------------------------------------------------------


def _not_ready(fx: Fx, master: M, case: str) -> uuid.UUID:
    """Break exactly one verification condition; returns the service to verify."""
    profile, spec, submission = (
        MasterProfile.id == master.id,
        MasterSpecialisation.master_id == master.id,
        (MasterQualification.master_id == master.id),
    )
    match case:
        case "profile_pending":
            _set(MasterProfile, profile, approval_status="pending_approval", decided_by=None, decided_at=None)
        case "profile_rejected":
            _set(MasterProfile, profile, approval_status="rejected")
        case "specialisation_requested":
            _set(MasterSpecialisation, spec, status="requested", decided_by=None, decided_at=None)
        case "specialisation_revoked":
            _set(MasterSpecialisation, spec, status="revoked")
        case "service_draft" | "service_rejected" | "service_archived":
            _set(CatalogueService, CatalogueService.id == SERVICE, status=case.removeprefix("service_"))
        case "qualification_missing":
            _set(MasterQualification, submission, status="submitted", decided_by=None, decided_at=None)
        case "qualification_rejected":
            _set(MasterQualification, submission, status="rejected")
        case "qualification_expired":
            _set(MasterQualification, submission, valid_until=fx.today - timedelta(days=1))
        case "qualification_revoked":
            _set(MasterQualification, submission, status="revoked")
        case "qualification_type_archived":
            _set(Qualification, Qualification.id == fx.qualification_id, status="archived")
        case "service_not_configured":
            _set(CatalogueService, CatalogueService.id == PLAIN_SERVICE, qualification_required=True)
            return PLAIN_SERVICE
        case "specialisation_not_configured":
            _set(CatalogueSpecialisation, CatalogueSpecialisation.id == SPEC, qualification_required=True)
            return PLAIN_SERVICE
    return SERVICE


BLOCKERS = {
    "profile_pending": ("PROFILE_NOT_APPROVED", {"approval_status": "pending_approval"}),
    "profile_rejected": ("PROFILE_NOT_APPROVED", {"approval_status": "rejected"}),
    "specialisation_requested": (
        "SPECIALISATION_NOT_APPROVED",
        {"specialisation_id": str(SPEC), "status": "requested"},
    ),
    "specialisation_revoked": (
        "SPECIALISATION_NOT_APPROVED",
        {"specialisation_id": str(SPEC), "status": "revoked"},
    ),
    "service_draft": ("SERVICE_NOT_AVAILABLE", {"catalogue_status": "draft"}),
    "service_rejected": ("SERVICE_NOT_AVAILABLE", {"catalogue_status": "rejected"}),
    "service_archived": ("SERVICE_NOT_AVAILABLE", {"catalogue_status": "archived"}),
    "qualification_missing": ("QUALIFICATION_MISSING", None),
    "qualification_rejected": ("QUALIFICATION_MISSING", None),
    "qualification_expired": ("QUALIFICATION_EXPIRED", None),
    "qualification_revoked": ("QUALIFICATION_REVOKED", None),
    "qualification_type_archived": ("QUALIFICATION_TYPE_NOT_ACTIVE", None),
    "service_not_configured": ("QUALIFICATION_NOT_CONFIGURED", None),
    "specialisation_not_configured": ("QUALIFICATION_NOT_CONFIGURED", None),
}


@pytest.mark.parametrize("case", BLOCKERS)
def test_verification_is_refused_unless_every_condition_holds(client: TestClient, fx: Fx, case: str) -> None:
    master = _master(client, fx)
    service_id = _not_ready(fx, master, case)
    _competency(fx, master, service_id=service_id)
    before = _state()
    resp = _post(client, fx, "verify", master.id, service_id)
    code, details = BLOCKERS[case]
    assert _error(resp) == (409, code)
    [reason] = resp.json()["error"]["details"]["reasons"]
    assert reason["code"] == code
    if details is not None:
        assert reason["details"] == details
    assert _state() == before
    # The refusal uses the shared rule: the same reason as eligibility.explain (besides the competency).
    if code != "SERVICE_NOT_AVAILABLE":
        with SessionLocal() as db:
            explained = eligibility.explain(db, service_id, [master.id])[master.id].reasons
        assert [r.code for r in explained] == ["COMPETENCY_NOT_VERIFIED", code] or [
            r.code for r in explained
        ] == [
            code,
            "COMPETENCY_NOT_VERIFIED",
        ]
    # Rejecting stays possible, so a blocked declaration does not stay pending forever.
    assert _post(client, fx, "reject", master.id, service_id).status_code == 200


def test_every_failing_condition_is_reported(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx, ready=False)  # pending profile, no specialisation, no qualification
    _competency(fx, master)
    before = _state()
    resp = _post(client, fx, "verify", master.id)
    assert _error(resp) == (409, "PROFILE_NOT_APPROVED")
    assert [r["code"] for r in resp.json()["error"]["details"]["reasons"]] == [
        "PROFILE_NOT_APPROVED",
        "SPECIALISATION_NOT_APPROVED",
        "QUALIFICATION_MISSING",
    ]
    assert _state() == before


@pytest.mark.parametrize("service_status", ["inactive", "planned", "hold", "active"])
def test_verification_succeeds_when_every_condition_holds(
    client: TestClient, fx: Fx, service_status: str
) -> None:
    """Not-yet-orderable services are verifiable: R-CAT-03 needs verified capacity before ordering."""
    master = _master(client, fx)
    _competency(fx, master)
    _competency(fx, master, service_id=PLAIN_SERVICE)
    _set(CatalogueService, CatalogueService.id.in_([SERVICE, PLAIN_SERVICE]), status=service_status)
    for service_id in (SERVICE, PLAIN_SERVICE):  # regulated with a valid qualification, and non-regulated
        resp = _post(client, fx, "verify", master.id, service_id)
        assert resp.status_code == 200, resp.text
        out = _competency_out(resp.json(), service_id)
        assert (out["status"], out["eligible"], out["reasons"]) == ("verified", True, [])
    with SessionLocal() as db:
        assert eligibility.eligible_master_ids(db, SERVICE) == [master.id]
        # Verification never changes or activates the service (HOLD stays HOLD).
        statuses = db.scalars(
            select(CatalogueService.status).where(CatalogueService.id.in_([SERVICE, PLAIN_SERVICE]))
        ).all()
        assert statuses == [service_status, service_status]


def test_qualification_valid_through_its_last_day(client: TestClient, fx: Fx) -> None:
    """`valid_until` is inclusive in Europe/Riga: today is still valid."""
    master = _master(client, fx)
    _set(MasterQualification, MasterQualification.master_id == master.id, valid_until=fx.today)
    _competency(fx, master)
    assert _post(client, fx, "verify", master.id).status_code == 200


def test_blocked_user_does_not_block_verification(client: TestClient, fx: Fx) -> None:
    """Blocking is the separate user mechanism: the competency is verified, the master stays ineligible."""
    master = _master(client, fx)
    _competency(fx, master)
    assert (
        client.post(
            f"/api/v1/admin/users/{master.user_id}/block", json={"reason": "Sūdzības"}, headers=fx.admin
        ).status_code
        == 200
    )
    resp = _post(client, fx, "verify", master.id).json()
    out = _competency_out(resp)
    assert (out["status"], out["eligible"]) == ("verified", False)
    assert [r["code"] for r in out["reasons"]] == ["USER_NOT_ACTIVE"]
    assert resp["user_status"] == "blocked"  # the verification does not lift the block
    with SessionLocal() as db:
        assert eligibility.eligible_master_ids(db, SERVICE) == []


# --- effects and history ------------------------------------------------------------------------------------


def test_revocation_excludes_at_once_and_history_is_kept(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    assert (
        client.post(
            "/api/v1/master/competencies", json={"service_id": str(SERVICE)}, headers=master.h
        ).status_code
        == 201
    )
    _post(client, fx, "reject", master.id, reason="Nav pieredzes")
    assert (
        client.post(
            "/api/v1/master/competencies", json={"service_id": str(SERVICE)}, headers=master.h
        ).status_code
        == 201
    )  # re-declaration starts a new review
    _post(client, fx, "verify", master.id, version=3)
    with SessionLocal() as db:
        assert eligibility.eligible_master_ids(db, SERVICE) == [master.id]
    revoked = _post(client, fx, "revoke", master.id, version=4, reason="Sūdzības").json()
    out = _competency_out(revoked)
    assert (out["status"], out["eligible"], out["decision_reason"]) == ("revoked", False, "Sūdzības")
    with SessionLocal() as db:
        assert eligibility.eligible_master_ids(db, SERVICE) == []
        # Nothing else moved: specialisation and qualification keep their own decisions.
        assert db.scalar(
            select(MasterSpecialisation.status).where(MasterSpecialisation.master_id == master.id)
        ) == ("approved")
        assert db.scalar(
            select(MasterQualification.status).where(MasterQualification.master_id == master.id)
        ) == ("verified")
        events = db.scalars(
            select(DomainEvent)
            .where(DomainEvent.aggregate_type == "master_competency")
            .order_by(DomainEvent.created_at, DomainEvent.id)
        ).all()
    trail = [(e.action, e.before, e.after) for e in _log(master)]
    assert [t[0] for t in trail] == [
        "master.competency.declared",
        "master.competency.rejected",
        "master.competency.declared",
        "master.competency.verified",
        "master.competency.revoked",
    ]
    assert [e.event_type for e in events] == [t[0] for t in trail]  # one event per change
    for previous, current in zip(trail, trail[1:], strict=False):
        assert previous[2] == current[1]  # an unbroken chain
    assert trail[2][1] is not None and trail[2][1]["decision_reason"] == "Nav pieredzes"
    assert all("decision_reason" not in e.payload for e in events)


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _decide(fx: Fx, master_id: uuid.UUID, action: str, version: int, service_id: uuid.UUID = SERVICE) -> None:
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        reason = None if action == "verify" else "Pamatojums"
        decision = master_admin.Decision(action, version, reason)  # type: ignore[arg-type]
        master_admin.decide_competency(db, admin, master_id, service_id, decision)


def _run(target: Any, results: list[str], *args: Any) -> None:
    try:
        target(*args)
        results.append("ok")
    except AppError as exc:
        results.append(exc.code)


def test_parallel_opposite_decisions(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []

    def run(action: str) -> None:
        barrier.wait()
        _run(_decide, results, fx, master.id, action, 1)

    threads = [threading.Thread(target=run, args=("verify" if i % 2 else "reject",)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results.count("ok") == 1 and results.count("VERSION_CONFLICT") == n - 1
    [entry] = _log(master)
    assert entry.after is not None and entry.after["version"] == 2


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        ("qualification_revoked", "QUALIFICATION_REVOKED"),  # another admin revokes the qualification
        ("specialisation_revoked", "SPECIALISATION_NOT_APPROVED"),  # another admin revokes the specialisation
        ("competency_withdrawn", "VERSION_CONFLICT"),  # the master withdraws the declaration
    ],
)
def test_verification_waits_for_the_master_row_lock(
    client: TestClient, fx: Fx, held: str, expected: str
) -> None:
    """A concurrent change that breaks a condition is seen, never raced.

    Without `FOR UPDATE` the verification reads the old, valid state and verifies the competency although the
    qualification or specialisation was revoked (or the declaration withdrawn) at the same time: this fails.
    """
    master = _master(client, fx)
    _competency(fx, master)
    before = _log(master)
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == master.id).with_for_update())
        if held == "qualification_revoked":
            holder.execute(
                update(MasterQualification)
                .where(MasterQualification.master_id == master.id)
                .values(status="revoked")
            )
        elif held == "specialisation_revoked":
            holder.execute(
                update(MasterSpecialisation)
                .where(MasterSpecialisation.master_id == master.id)
                .values(status="revoked")
            )
        else:
            holder.execute(
                update(MasterCompetency)
                .where(MasterCompetency.master_id == master.id)
                .values(status="withdrawn", version=2)
            )
        thread = threading.Thread(target=_run, args=(_decide, outcome, fx, master.id, "verify", 1))
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the verification must wait for the master row lock"
        holder.commit()
    thread.join(timeout=30)
    assert outcome == [expected]
    with SessionLocal() as db:
        row = db.get(MasterCompetency, (master.id, SERVICE))
        assert row is not None and row.status != "verified" and row.decided_by is None
    assert _log(master) == before


def test_master_withdrawal_and_admin_verification_serialise(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _competency(fx, master)
    barrier = threading.Barrier(2)
    admin_result: list[str] = []
    master_result: list[str] = []

    def admin() -> None:
        barrier.wait()
        _run(_decide, admin_result, fx, master.id, "verify", 1)

    def owner() -> None:
        barrier.wait()
        with SessionLocal() as db:
            user = db.get(User, master.user_id)
            assert user is not None
            _run(svc.withdraw_competency, master_result, db, user, SERVICE)

    threads = [threading.Thread(target=admin), threading.Thread(target=owner)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    with SessionLocal() as db:
        row = db.get(MasterCompetency, (master.id, SERVICE))
        assert row is not None
    if admin_result == ["ok"]:
        assert (master_result, row.status) == (["CANNOT_WITHDRAW"], "verified")
    else:
        assert (admin_result, master_result, row.status) == (["VERSION_CONFLICT"], ["ok"], "withdrawn")
    assert row.version == 2 and len(_log(master)) == 1
