"""Admin decisions on qualification submissions (step 4.4.7, R-MST-09/15/16, owner decisions 2026-11-02)."""

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
    Attachment,
    AuditLog,
    CatalogueService,
    DomainEvent,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications
from app.models.master import QUALIFICATION_STATUSES
from app.services import eligibility, master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register
from tests.files import PDF, PNG

SPEC = seed_id("cm-s01")
SERVICE = seed_id("cm-s01-1")
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
NUMBER = "LV-ELEC-778899"
ACTIONS = ("verify", "reject", "revoke")
ALLOWED = {
    ("submitted", "verify"): "verified",
    ("submitted", "reject"): "rejected",
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
    electric: uuid.UUID
    gas: uuid.UUID
    today: date


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        db.execute(update(CatalogueService).where(CatalogueService.id == SERVICE).values(status="inactive"))
        electric = Qualification(
            name="Elektrodrošība",
            status="active",
            requires_document=True,
            requires_document_number=True,
            requires_expiry_date=True,
        )
        gas = Qualification(name="Gāzes iekārtas", status="active")
        db.add_all([electric, gas])
        db.flush()
        db.execute(service_qualifications.insert().values(service_id=SERVICE, qualification_id=electric.id))
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, electric.id, gas.id, business_today(db))


def _decided(fx: Fx) -> dict[str, Any]:
    return {"decided_by": fx.admin_id, "decided_at": T0}


def _master(client: TestClient, fx: Fx) -> M:
    """A master that holds everything for SERVICE except the electric qualification."""
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
        assert master_id is not None
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
        db.add(MasterCompetency(master_id=master_id, service_id=SERVICE, status="verified", **_decided(fx)))
        db.commit()
    return M(master_id, user_id, auth(body["access_token"]))


def _row(
    fx: Fx, master: M, status: str, *, valid_until: date | None = None, qualification: Any = None
) -> uuid.UUID:
    with SessionLocal() as db:
        row = MasterQualification(
            master_id=master.id,
            qualification_id=qualification or fx.electric,
            status=status,
            document_number=NUMBER,
            valid_until=valid_until or fx.today + timedelta(days=200),
            submitted_at=T0,
            decision_reason="Vecs iemesls" if status in ("rejected", "revoked") else None,
            **(_decided(fx) if status in DECIDED else {}),
        )
        db.add(row)
        db.commit()
        return row.id


def _submit(client: TestClient, fx: Fx, master: M, valid_until: date | None = None) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/master/qualifications",
        data={
            "qualification_id": str(fx.electric),
            "document_number": NUMBER,
            "valid_until": str(valid_until or fx.today + timedelta(days=200)),
        },
        files=[("files", ("a.pdf", PDF, "application/pdf")), ("files", ("b.png", PNG, "image/png"))],
        headers=master.h,
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _url(master_id: Any, submission_id: Any, action: str) -> str:
    return f"/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/{action}"


def _post(
    client: TestClient,
    fx: Fx,
    action: str,
    master_id: Any,
    submission_id: Any,
    version: int = 1,
    reason: str = "Iemesls",
) -> Any:
    body: dict[str, Any] = {"expected_version": version}
    if action != "verify":
        body["reason"] = reason
    return client.post(_url(master_id, submission_id, action), json=body, headers=fx.admin)


def _state() -> tuple[Any, ...]:
    """Every master row and attachment (all columns), plus all audit entries and events."""
    with SessionLocal() as db:
        rows = [
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (
                MasterProfile,
                MasterSpecialisation,
                MasterCompetency,
                MasterQualification,
                Attachment,
            )
            for row in db.scalars(select(model))
        ]
        return (
            sorted(rows, key=repr),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _log(submission_id: Any) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.entity_type == "master_qualification",
                    AuditLog.entity_id == uuid.UUID(str(submission_id)),
                )
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _error(resp: Any) -> tuple[int, str]:
    return resp.status_code, resp.json()["error"]["code"]


def _submission(body: dict[str, Any], submission_id: Any) -> dict[str, Any]:
    [found] = [q for q in body["qualifications"] if q["id"] == str(submission_id)]
    return found


def _eligible(master: M) -> bool:
    with SessionLocal() as db:
        return eligibility.eligible_master_ids(db, SERVICE) == [master.id]


# --- access and identifiers ---------------------------------------------------------------------------------


def test_only_admins_decide(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted")
    customer = auth(register(client, "client")["access_token"])
    before = _state()
    for action in ACTIONS:
        body = {"expected_version": 1, **({"reason": "x"} if action != "verify" else {})}
        url = _url(master.id, submission, action)
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers=master.h).status_code == 403  # not on their own submission
        assert client.post(url, json=body, headers=customer).status_code == 403
    assert _state() == before


def test_unknown_foreign_or_deleted(client: TestClient, fx: Fx) -> None:
    owner, other, gone = _master(client, fx), _master(client, fx), _master(client, fx)
    mine = _row(fx, owner, "submitted")
    theirs = _row(fx, other, "submitted")
    deleted = _row(fx, gone, "submitted")
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == gone.user_id).values(deleted_at=T0))
        db.commit()
    before = _state()
    attempts = [
        (other.id, mine, "QUALIFICATION_NOT_FOUND"),  # the owner's submission under another master
        (owner.id, theirs, "QUALIFICATION_NOT_FOUND"),  # another master's submission under the owner
        (owner.id, uuid.uuid4(), "QUALIFICATION_NOT_FOUND"),
        (
            owner.id,
            fx.electric,
            "QUALIFICATION_NOT_FOUND",
        ),  # the qualification type ID instead of a submission
        (uuid.uuid4(), mine, "MASTER_NOT_FOUND"),
        (owner.user_id, mine, "MASTER_NOT_FOUND"),  # user ID instead of master ID
        (gone.id, deleted, "MASTER_NOT_FOUND"),  # deleted account
    ]
    for master_id, submission_id, code in attempts:
        for action in ACTIONS:
            assert _error(_post(client, fx, action, master_id, submission_id)) == (404, code), (
                master_id,
                action,
            )
    assert (
        client.post(_url(owner.id, "x", "verify"), json={"expected_version": 1}, headers=fx.admin).status_code
        == 422
    )
    assert _state() == before


# --- transitions and reasons --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", QUALIFICATION_STATUSES)
@pytest.mark.parametrize("action", ACTIONS)
def test_every_transition(client: TestClient, fx: Fx, status: str, action: str) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, status)
    before = _state()
    resp = _post(client, fx, action, master.id, submission)
    expected = ALLOWED.get((status, action))
    if expected is None:  # rejected/revoked/withdrawn are final; repeats are refused too
        assert _error(resp) == (409, "INVALID_TRANSITION")
        assert resp.json()["error"]["details"] == {"status": status, "version": 1, "action": action}
        assert _state() == before
        return
    assert resp.status_code == 200, resp.text
    out = _submission(resp.json(), submission)
    assert (out["status"], out["version"], out["decided_by"]) == (expected, 2, str(fx.admin_id))
    assert out["decision_reason"] == (None if action == "verify" else "Iemesls")
    assert (out["document_number"], out["valid_until"]) == (NUMBER, str(fx.today + timedelta(days=200)))
    [entry] = _log(submission)
    assert entry.action == f"master.qualification.{expected}" and entry.actor_id == fx.admin_id
    assert entry.before is not None and entry.after is not None
    assert (entry.before["status"], entry.after["status"]) == (status, expected)
    assert entry.after["document_number_last4"] == "8899" and NUMBER not in str(entry.after)
    assert entry.after["decision_reason"] == entry.reason == (None if action == "verify" else "Iemesls")
    with SessionLocal() as db:
        [event] = db.scalars(
            select(DomainEvent).where(DomainEvent.event_type.like("master.qualification.%"))
        ).all()
    assert event.event_type == entry.action and event.aggregate_id == submission
    assert "decision_reason" not in event.payload and "Iemesls" not in str(event.payload)
    assert _eligible(master) is (expected == "verified")


@pytest.mark.parametrize("action", ["reject", "revoke"])
@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": 1},
        {"expected_version": 1, "reason": ""},
        {"expected_version": 1, "reason": "   "},
        {"expected_version": 1, "reason": None},
        {"expected_version": 1, "reason": "x" * 1001},
        {"reason": "Iemesls"},
        {"expected_version": 0, "reason": "Iemesls"},
        {"expected_version": 1, "reason": "Iemesls", "status": "verified"},
    ],
)
def test_reject_and_revoke_need_a_reason(
    client: TestClient, fx: Fx, action: str, body: dict[str, Any]
) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted" if action == "reject" else "verified")
    before = _state()
    assert client.post(_url(master.id, submission, action), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


@pytest.mark.parametrize("action", ["reject", "revoke"])
def test_reason_of_1000_chars_is_trimmed_and_kept(client: TestClient, fx: Fx, action: str) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted" if action == "reject" else "verified")
    resp = _post(client, fx, action, master.id, submission, reason="  " + "š" * 1000 + "  ")
    assert resp.status_code == 200 and _submission(resp.json(), submission)["decision_reason"] == "š" * 1000


@pytest.mark.parametrize(
    "body",
    [
        {"expected_version": 1, "reason": "x"},
        {"expected_version": 1, "valid_until": "2030-01-01"},  # the admin never edits document data
        {"expected_version": 1, "document_number": "LV-OTHER"},
        {},
    ],
)
def test_verify_takes_no_reason_or_document_data(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted")
    before = _state()
    assert client.post(_url(master.id, submission, "verify"), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


def test_stale_or_repeated_decisions_change_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted")
    stale = _post(client, fx, "verify", master.id, submission, version=5)
    assert _error(stale) == (409, "VERSION_CONFLICT")
    assert stale.json()["error"]["details"] == {"status": "submitted", "version": 1}
    assert _post(client, fx, "verify", master.id, submission).status_code == 200
    before = _state()
    for action in ACTIONS:  # repeating with the old version
        assert _error(_post(client, fx, action, master.id, submission)) == (409, "VERSION_CONFLICT")
    for action in ("verify", "reject"):
        assert _error(_post(client, fx, action, master.id, submission, version=2)) == (
            409,
            "INVALID_TRANSITION",
        )
    assert _state() == before
    assert _post(client, fx, "revoke", master.id, submission, version=2).status_code == 200
    before = _state()
    for action in ACTIONS:  # no second revocation, no re-verification
        assert _error(_post(client, fx, action, master.id, submission, version=3)) == (
            409,
            "INVALID_TRANSITION",
        )
    assert _state() == before
    assert [e.action for e in _log(submission)] == [
        "master.qualification.verified",
        "master.qualification.revoked",
    ]


# --- verification conditions --------------------------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 30])
def test_an_expired_document_is_never_verified(client: TestClient, fx: Fx, days: int) -> None:
    master = _master(client, fx)
    expired = fx.today - timedelta(days=days)
    submission = _row(fx, master, "submitted", valid_until=expired)
    before = _state()
    resp = _post(client, fx, "verify", master.id, submission)
    assert _error(resp) == (409, "QUALIFICATION_EXPIRED")
    assert resp.json()["error"]["details"]["reasons"] == [
        {"code": "QUALIFICATION_EXPIRED", "details": {"valid_until": expired.isoformat()}}
    ]
    assert _state() == before
    assert _post(client, fx, "reject", master.id, submission).status_code == 200  # rejection stays possible


def test_document_valid_through_its_last_day(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted", valid_until=fx.today)
    assert _post(client, fx, "verify", master.id, submission).status_code == 200
    assert _eligible(master)


@pytest.mark.parametrize("type_status", ["draft", "archived"])
def test_inactive_qualification_type_is_not_verified(client: TestClient, fx: Fx, type_status: str) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted", valid_until=fx.today - timedelta(days=1))
    with SessionLocal() as db:
        db.execute(update(Qualification).where(Qualification.id == fx.electric).values(status=type_status))
        db.commit()
    before = _state()
    resp = _post(client, fx, "verify", master.id, submission)
    assert _error(resp) == (409, "QUALIFICATION_TYPE_NOT_ACTIVE")
    assert [r["code"] for r in resp.json()["error"]["details"]["reasons"]] == [
        "QUALIFICATION_TYPE_NOT_ACTIVE",
        "QUALIFICATION_EXPIRED",
    ]
    assert _state() == before


# --- documents ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [("verify",), ("reject",), ("verify", "revoke")])
def test_documents_stay_bound_unchanged_and_reachable(
    client: TestClient, fx: Fx, path: tuple[str, ...]
) -> None:
    master = _master(client, fx)
    body = _submit(client, fx, master)
    submission = body["id"]
    with SessionLocal() as db:
        files_before = [
            tuple(sorted((c.key, getattr(a, c.key)) for c in Attachment.__table__.columns))
            for a in db.scalars(select(Attachment).order_by(Attachment.id))
        ]
        keys = [a.storage_key for a in db.scalars(select(Attachment))]
        hashes = [a.sha256 for a in db.scalars(select(Attachment))]
    for version, action in enumerate(path, start=1):
        resp = _post(client, fx, action, master.id, submission, version=version)
        assert resp.status_code == 200, resp.text
        out = _submission(resp.json(), submission)
        assert (out["document_number"], out["valid_until"]) == (NUMBER, body["valid_until"])
        assert [f["id"] for f in out["files"]] == [f["id"] for f in body["files"]]
        assert not any(secret in resp.text for secret in (*keys, *hashes, "storage_key", "sha256"))
    with SessionLocal() as db:
        files_after = [
            tuple(sorted((c.key, getattr(a, c.key)) for c in Attachment.__table__.columns))
            for a in db.scalars(select(Attachment).order_by(Attachment.id))
        ]
        row = db.get(MasterQualification, uuid.UUID(submission))
        assert row is not None and (row.document_number, row.valid_until.isoformat()) == (
            NUMBER,
            body["valid_until"],
        )
    assert files_after == files_before
    for file in body["files"]:  # both existing routes still serve the files, under the same rules
        own = f"/api/v1/master/qualifications/{submission}/files/{file['id']}"
        admin = f"/api/v1/admin/masters/{master.id}/qualifications/{submission}/files/{file['id']}"
        assert client.get(own, headers=master.h).status_code == 200
        assert client.get(admin, headers=fx.admin).status_code == 200
        assert client.get(admin, headers=master.h).status_code == 403


# --- eligibility --------------------------------------------------------------------------------------------


def test_eligibility_follows_each_decision(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    first = _submit(client, fx, master)["id"]
    assert not _eligible(master)  # submitted never counts
    _post(client, fx, "reject", master.id, first, reason="Neskaidrs skenējums")
    assert not _eligible(master)
    second = _submit(client, fx, master)["id"]  # resubmission after rejection: a new row
    _post(client, fx, "verify", master.id, second)
    assert _eligible(master)
    revoked = _post(client, fx, "revoke", master.id, second, version=2, reason="Viltots").json()
    assert not _eligible(master)  # at once
    [competency] = revoked["competencies"]
    assert competency["status"] == "verified"  # the competency row itself is unchanged
    assert [r["code"] for r in competency["reasons"]] == ["QUALIFICATION_REVOKED"]
    with SessionLocal() as db:
        rows = {r.id: r.status for r in db.scalars(select(MasterQualification))}
    assert rows == {uuid.UUID(first): "rejected", uuid.UUID(second): "revoked"}  # both kept in history


def test_renewal_leaves_the_expired_verified_row_unchanged(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    old = _row(fx, master, "verified", valid_until=fx.today - timedelta(days=1))
    with SessionLocal() as db:
        old_row = db.get(MasterQualification, old)
        assert old_row is not None
        old_columns = {c.key: getattr(old_row, c.key) for c in MasterQualification.__table__.columns}
    assert not _eligible(master)  # expired
    renewal = _submit(client, fx, master)["id"]
    assert not _eligible(master)  # a pending renewal admits nobody
    _post(client, fx, "verify", master.id, renewal)
    assert _eligible(master)
    with SessionLocal() as db:
        old_row = db.get(MasterQualification, old)
        assert old_row is not None
        assert {c.key: getattr(old_row, c.key) for c in MasterQualification.__table__.columns} == old_columns
    assert _log(old) == []


def test_every_required_qualification_must_hold(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    with SessionLocal() as db:
        db.execute(service_qualifications.insert().values(service_id=SERVICE, qualification_id=fx.gas))
        db.commit()
    electric = _submit(client, fx, master)["id"]
    gas = _row(fx, master, "submitted", qualification=fx.gas)
    _post(client, fx, "verify", master.id, electric)
    assert not _eligible(master)  # gas still missing
    _post(client, fx, "verify", master.id, gas)
    assert _eligible(master)
    _post(client, fx, "revoke", master.id, gas, version=2)
    assert not _eligible(master)  # one revoked requirement is enough to exclude


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _decide(fx: Fx, master_id: uuid.UUID, submission_id: uuid.UUID, action: str, version: int) -> None:
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        reason = None if action == "verify" else "Iemesls"
        decision = master_admin.Decision(action, version, reason)  # type: ignore[arg-type]
        master_admin.decide_qualification(db, admin, master_id, submission_id, decision)


def _run(target: Any, results: list[str], *args: Any) -> None:
    try:
        target(*args)
        results.append("ok")
    except AppError as exc:
        results.append(exc.code)


def test_parallel_opposite_decisions(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted")
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []

    def run(action: str) -> None:
        barrier.wait()
        _run(_decide, results, fx, master.id, submission, action, 1)

    threads = [threading.Thread(target=run, args=("verify" if i % 2 else "reject",)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results.count("ok") == 1 and results.count("VERSION_CONFLICT") == n - 1
    [entry] = _log(submission)
    assert entry.after is not None and entry.after["version"] == 2


@pytest.mark.parametrize(
    ("status", "held", "attempt"),
    [
        ("submitted", "withdrawn", "verify"),  # the master withdraws while we verify
        ("submitted", "rejected", "verify"),  # another admin rejects while we verify
        ("verified", "revoked", "revoke"),  # two admins revoke at once
    ],
)
def test_decision_waits_for_the_master_row_lock(
    client: TestClient, fx: Fx, status: str, held: str, attempt: str
) -> None:
    """Without `FOR UPDATE` the decision reads the old version and overwrites the other change: this fails."""
    master = _master(client, fx)
    submission = _row(fx, master, status)
    other_change: dict[str, Any] = {"status": held, "version": 2, "decision_reason": "Cits"}
    if held != "withdrawn":
        other_change |= {"decided_by": fx.admin_id, "decided_at": datetime.now(UTC)}
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == master.id).with_for_update())
        holder.execute(
            update(MasterQualification).where(MasterQualification.id == submission).values(**other_change)
        )
        thread = threading.Thread(target=_run, args=(_decide, outcome, fx, master.id, submission, attempt, 1))
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the decision must wait for the master row lock"
        holder.commit()
    thread.join(timeout=30)
    assert outcome == ["VERSION_CONFLICT"]
    with SessionLocal() as db:
        row = db.get(MasterQualification, submission)
        assert row is not None and {key: getattr(row, key) for key in other_change} == other_change
    assert _log(submission) == []


def test_master_withdrawal_and_admin_verification_serialise(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    submission = _row(fx, master, "submitted")
    barrier = threading.Barrier(2)
    admin_result: list[str] = []
    master_result: list[str] = []

    def admin() -> None:
        barrier.wait()
        _run(_decide, admin_result, fx, master.id, submission, "verify", 1)

    def owner() -> None:
        barrier.wait()
        with SessionLocal() as db:
            user = db.get(User, master.user_id)
            assert user is not None
            _run(svc.withdraw_qualification, master_result, db, user, submission)

    threads = [threading.Thread(target=admin), threading.Thread(target=owner)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    with SessionLocal() as db:
        row = db.get(MasterQualification, submission)
        assert row is not None
    if admin_result == ["ok"]:
        assert (master_result, row.status) == (["CANNOT_WITHDRAW"], "verified")
    else:
        assert (admin_result, master_result, row.status) == (["VERSION_CONFLICT"], ["ok"], "withdrawn")
    assert row.version == 2 and len(_log(submission)) == 1
