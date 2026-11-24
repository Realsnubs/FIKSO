"""Master API: applications, competencies, qualification submissions, renewal and files (step 4.3)."""

import json
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
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.integrations.storage import LocalStorage, get_storage
from app.models import (
    Attachment,
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
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from app.services.uploads import ValidFile
from tests.conftest import auth, register
from tests.files import HEIC, JPEG, PDF, PNG, WEBP

SPEC = seed_id("cm-s01")
SERVICE = seed_id("cm-s01-1")  # W071
OTHER_SERVICE = seed_id("cm-s01-2")  # W072
SECRET_NUMBER = "LV-ELEC-778899"


@dataclass
class Master:
    token: str
    user_id: uuid.UUID
    master_id: uuid.UUID

    @property
    def h(self) -> dict[str, str]:
        return auth(self.token)


def _master(client: TestClient) -> Master:
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
    assert master_id is not None
    return Master(body["access_token"], user_id, master_id)


@pytest.fixture
def setup(client: TestClient) -> Iterator[dict[str, Any]]:
    with SessionLocal() as db:
        seed_catalogue(db)
        admin = User(role="admin", email="adm@example.lv", password_hash="x", full_name="Admin")
        db.add(admin)
        # Seeded services are drafts (not declarable); make the two used here declarable.
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([SERVICE, OTHER_SERVICE]))
            .values(status="inactive")
        )
        qualification = Qualification(
            name="Elektrodrošība",
            status="active",
            requires_document=True,
            requires_document_number=True,
            requires_expiry_date=True,
            max_validity_months=60,
            verifier_instructions="internal: check the register",
        )
        db.add(qualification)
        db.flush()
        db.execute(
            service_qualifications.insert().values(service_id=SERVICE, qualification_id=qualification.id)
        )
        db.commit()
        yield {"admin_id": admin.id, "qualification_id": qualification.id}


def _decide(row_filter: Any, model: type, status: str, admin_id: uuid.UUID, **values: Any) -> None:
    """Admin decisions arrive in step 4.4; tests set them directly."""
    with SessionLocal() as db:
        db.execute(
            update(model)
            .where(row_filter)
            .values(status=status, decided_by=admin_id, decided_at=datetime.now(UTC), **values)
        )
        db.commit()


def _today() -> date:
    with SessionLocal() as db:
        return business_today(db)


def _submit(
    client: TestClient,
    master: Master,
    qualification_id: uuid.UUID,
    *,
    files: list[tuple[str, bytes, str]] | None = None,
    number: str | None = SECRET_NUMBER,
    valid_until: date | None | str = "default",
) -> Any:
    data: dict[str, str] = {"qualification_id": str(qualification_id)}
    if number is not None:
        data["document_number"] = number
    until = _today() + timedelta(days=365) if valid_until == "default" else valid_until
    if until is not None:
        data["valid_until"] = str(until)
    upload = [("files", f) for f in (files if files is not None else [("cert.pdf", PDF, "application/pdf")])]
    return client.post("/api/v1/master/qualifications", data=data, files=upload, headers=master.h)


def _objects() -> list[str]:
    return [key for key, _ in get_storage().objects()]


def _count(model: type, *where: Any) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


# --- access -------------------------------------------------------------------------------------------------


def test_only_masters_reach_the_master_api(client: TestClient, setup: dict[str, Any]) -> None:
    customer = register(client, "client")["access_token"]
    sub = uuid.uuid4()
    calls = [
        ("get", "/api/v1/master/capabilities", {}),
        ("get", "/api/v1/master/catalogue", {}),
        ("post", "/api/v1/master/specialisations", {"json": {"specialisation_id": str(SPEC)}}),
        ("post", f"/api/v1/master/specialisations/{SPEC}/withdraw", {}),
        ("post", "/api/v1/master/competencies", {"json": {"service_id": str(SERVICE)}}),
        ("post", f"/api/v1/master/competencies/{SERVICE}/withdraw", {}),
        ("post", "/api/v1/master/qualifications", {"data": {"qualification_id": str(sub)}}),
        ("post", f"/api/v1/master/qualifications/{sub}/withdraw", {}),
        ("get", f"/api/v1/master/qualifications/{sub}/files/{uuid.uuid4()}", {}),
    ]
    for method, url, kwargs in calls:
        assert getattr(client, method)(url, **kwargs).status_code == 401, url
        resp = getattr(client, method)(url, headers=auth(customer), **kwargs)
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "FORBIDDEN", url


def test_catalogue_lists_what_a_master_may_apply_for(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    body = client.get("/api/v1/master/catalogue", headers=master.h).json()
    assert {s["status"] for s in body["specialisations"]} <= {"active", "planned"}
    services = [svc for s in body["specialisations"] for svc in s["services"]]
    assert {s["w_id"] for s in services} == {"W071", "W072"}  # all other seeded services are drafts
    w071 = next(s for s in services if s["w_id"] == "W071")
    assert w071["qualification_ids"] == [str(setup["qualification_id"])]
    [rule] = body["qualification_types"]
    assert rule["requires_document_number"] and "verifier_instructions" not in rule


# --- specialisations and competencies -----------------------------------------------------------------------


def test_specialisation_requests_and_reapplication_keep_history(
    client: TestClient, setup: dict[str, Any]
) -> None:
    master = _master(client)
    url = "/api/v1/master/specialisations"
    assert (
        client.post(url, json={"specialisation_id": str(uuid.uuid4())}, headers=master.h).status_code == 404
    )
    resp = client.post(url, json={"specialisation_id": str(SPEC)}, headers=master.h)
    assert resp.status_code == 201 and resp.json()["status"] == "requested"
    again = client.post(url, json={"specialisation_id": str(SPEC)}, headers=master.h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "SPECIALISATION_ALREADY_EXISTS"
    assert client.post(f"{url}/{SPEC}/withdraw", headers=master.h).json()["status"] == "withdrawn"
    assert (
        client.post(url, json={"specialisation_id": str(SPEC)}, headers=master.h).json()["status"]
        == "requested"
    )
    _decide(
        MasterSpecialisation.master_id == master.master_id,
        MasterSpecialisation,
        "rejected",
        setup["admin_id"],
        decision_reason="Nepietiek pieredzes",
    )
    # A rejection is reapplied for; the last decision stays on the row and every step is in the audit trail.
    assert client.post(url, json={"specialisation_id": str(SPEC)}, headers=master.h).status_code == 201
    with SessionLocal() as db:
        row = db.get(MasterSpecialisation, (master.master_id, SPEC))
        assert row is not None
        assert (row.status, row.version, row.decision_reason) == ("requested", 4, "Nepietiek pieredzes")
        actions = db.scalars(
            select(AuditLog.action).where(AuditLog.actor_id == master.user_id).order_by(AuditLog.created_at)
        ).all()
        assert actions == [
            "master.specialisation.requested",
            "master.specialisation.withdrawn",
            "master.specialisation.requested",
            "master.specialisation.requested",
        ]
    _decide(
        MasterSpecialisation.master_id == master.master_id,
        MasterSpecialisation,
        "approved",
        setup["admin_id"],
    )
    blocked = client.post(f"{url}/{SPEC}/withdraw", headers=master.h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CANNOT_WITHDRAW"
    with SessionLocal() as db:
        db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == seed_id("cm-s02"))
            .values(status="inactive")
        )
        db.commit()
    unavailable = client.post(url, json={"specialisation_id": str(seed_id("cm-s02"))}, headers=master.h)
    assert unavailable.json()["error"]["code"] == "SPECIALISATION_NOT_AVAILABLE"


def test_competency_needs_a_requested_specialisation_and_a_declarable_service(
    client: TestClient, setup: dict[str, Any]
) -> None:
    master = _master(client)
    url = "/api/v1/master/competencies"
    first = client.post(url, json={"service_id": str(SERVICE)}, headers=master.h)
    assert first.status_code == 409 and first.json()["error"]["code"] == "SPECIALISATION_NOT_REQUESTED"
    client.post("/api/v1/master/specialisations", json={"specialisation_id": str(SPEC)}, headers=master.h)
    draft = client.post(url, json={"service_id": str(seed_id("cm-s01-3"))}, headers=master.h)
    assert draft.json()["error"]["code"] == "SERVICE_NOT_AVAILABLE"
    assert client.post(url, json={"service_id": str(uuid.uuid4())}, headers=master.h).status_code == 404
    resp = client.post(url, json={"service_id": str(SERVICE)}, headers=master.h)
    assert resp.status_code == 201 and resp.json() == {"service_id": str(SERVICE), "status": "declared"}
    assert client.post(url, json={"service_id": str(SERVICE)}, headers=master.h).status_code == 409
    assert client.post(f"{url}/{SERVICE}/withdraw", headers=master.h).json()["status"] == "withdrawn"
    assert client.post(url, json={"service_id": str(SERVICE)}, headers=master.h).status_code == 201
    _decide(MasterCompetency.master_id == master.master_id, MasterCompetency, "verified", setup["admin_id"])
    assert (
        client.post(f"{url}/{SERVICE}/withdraw", headers=master.h).json()["error"]["code"]
        == "CANNOT_WITHDRAW"
    )
    # Declaring never grants anything: the capability view explains what is still missing.
    caps = client.get("/api/v1/master/capabilities", headers=master.h).json()
    [competency] = caps["competencies"]
    assert competency["eligible"] is False
    assert [r["code"] for r in competency["reasons"]] == [
        "PROFILE_NOT_APPROVED",
        "SPECIALISATION_NOT_APPROVED",
        "QUALIFICATION_MISSING",
    ]


def _set_profile(master: Master, status: str, admin_id: uuid.UUID, reason: str | None = None) -> None:
    """Profile decisions arrive in step 4.4.4; tests set them directly, with the decider the DB requires."""
    with SessionLocal() as db:
        db.execute(
            update(MasterProfile)
            .where(MasterProfile.id == master.master_id)
            .values(
                approval_status=status,
                decided_by=admin_id,
                decided_at=datetime.now(UTC),
                decision_reason=reason,
            )
        )
        db.commit()


def test_rejected_profile_reads_but_cannot_apply(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    _set_profile(master, "rejected", setup["admin_id"], "Nepilnīgi dati")
    resp = client.post(
        "/api/v1/master/specialisations", json={"specialisation_id": str(SPEC)}, headers=master.h
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "MASTER_PROFILE_REJECTED"
    assert (
        _submit(client, master, setup["qualification_id"]).json()["error"]["code"]
        == "MASTER_PROFILE_REJECTED"
    )
    caps = client.get("/api/v1/master/capabilities", headers=master.h).json()
    assert (caps["approval_status"], caps["rejection_reason"]) == ("rejected", "Nepilnīgi dati")


def _history(master: Master) -> tuple[Any, ...]:
    """Every capability row of the master (all columns) plus the audit and event counts."""
    with SessionLocal() as db:
        rows = tuple(
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (MasterSpecialisation, MasterCompetency, MasterQualification)
            for row in db.scalars(select(model).where(model.master_id == master.master_id))
        )
        return (
            rows,
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _pending_items(client: TestClient, master: Master, qualification_id: uuid.UUID) -> str:
    url = "/api/v1/master"
    for path, body in (
        ("specialisations", {"specialisation_id": str(SPEC)}),
        ("competencies", {"service_id": str(SERVICE)}),
    ):
        assert client.post(f"{url}/{path}", json=body, headers=master.h).status_code == 201
    resp = _submit(client, master, qualification_id)
    assert resp.status_code == 201
    return str(resp.json()["id"])


@pytest.mark.parametrize(
    ("path", "status"),
    [
        (f"specialisations/{SPEC}/withdraw", "requested"),
        (f"competencies/{SERVICE}/withdraw", "declared"),
        ("qualifications/{submission}/withdraw", "submitted"),
    ],
    ids=["specialisation", "competency", "qualification"],
)
def test_rejected_profile_cannot_withdraw_pending_items(
    client: TestClient, setup: dict[str, Any], path: str, status: str
) -> None:
    """Owner decision: a rejected profile is read-only, so even pending items stay as they are."""
    master = _master(client)
    submission = _pending_items(client, master, setup["qualification_id"])
    _set_profile(master, "rejected", setup["admin_id"], "Nepilnīgi dati")
    before = _history(master)
    resp = client.post(f"/api/v1/master/{path.format(submission=submission)}", headers=master.h)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "MASTER_PROFILE_REJECTED"
    assert _history(master) == before
    caps = client.get("/api/v1/master/capabilities", headers=master.h).json()
    statuses = [i["status"] for i in caps["specialisations"] + caps["competencies"] + caps["qualifications"]]
    assert statuses == ["requested", "declared", "submitted"] and status in statuses


# --- qualification submissions ------------------------------------------------------------------------------


def test_submission_stores_files_and_logs_no_personal_data(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    files = [
        ("a.pdf", PDF, "application/pdf"),
        ("b.jpg", JPEG, "image/jpeg"),
        ("c.png", PNG, "image/png"),
        ("d.webp", WEBP, "image/webp"),
        ("e.heic", HEIC, "image/heic"),
    ]
    resp = _submit(client, master, setup["qualification_id"], files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "submitted" and body["document_number"] == SECRET_NUMBER
    assert sorted(f["mime_type"] for f in body["files"]) == [
        "application/pdf",
        "image/heic",
        "image/jpeg",
        "image/png",
        "image/webp",
    ]
    assert all(set(f) == {"id", "mime_type", "size_bytes", "uploaded_at"} for f in body["files"])
    assert len(_objects()) == 5
    with SessionLocal() as db:
        stored = {a.storage_key for a in db.scalars(select(Attachment))}
        assert stored == set(_objects())
        assert all(a.owner_user_id == master.user_id for a in db.scalars(select(Attachment)))
        logs = json.dumps([[a.before, a.after] for a in db.scalars(select(AuditLog))])
        events = json.dumps([e.payload for e in db.scalars(select(DomainEvent))])
    assert SECRET_NUMBER not in logs and SECRET_NUMBER not in events and "8899" in logs
    assert "cert.pdf" not in logs and "a.pdf" not in logs


@pytest.mark.parametrize(
    ("kwargs", "code", "http"),
    [
        ({"files": []}, "DOCUMENT_REQUIRED", 400),
        ({"number": None}, "DOCUMENT_NUMBER_REQUIRED", 400),
        ({"number": "   "}, "DOCUMENT_NUMBER_REQUIRED", 400),
        ({"valid_until": None}, "EXPIRY_DATE_REQUIRED", 400),
        ({"valid_until": "yesterday"}, "VALID_UNTIL_IN_PAST", 400),
        ({"valid_until": "too_long"}, "VALIDITY_TOO_LONG", 400),
        ({"files": [("x.pdf", b"MZ\x90 not a pdf", "application/pdf")]}, "UNSUPPORTED_FILE_TYPE", 415),
        ({"files": [("x.pdf", PDF, "application/pdf")] * 6}, "TOO_MANY_FILES", 400),
        ({"files": [("x.pdf", PDF + b"0" * (10 * 1024 * 1024), "application/pdf")]}, "FILE_TOO_LARGE", 413),
        ({"files": [("x.pdf", PDF, "application/pdf"), ("y.png", b"", "image/png")]}, "FILE_EMPTY", 400),
    ],
)
def test_invalid_submissions_store_nothing(
    client: TestClient, setup: dict[str, Any], kwargs: dict[str, Any], code: str, http: int
) -> None:
    master = _master(client)
    today = _today()
    if kwargs.get("valid_until") == "yesterday":
        kwargs["valid_until"] = today - timedelta(days=1)
    if kwargs.get("valid_until") == "too_long":
        kwargs["valid_until"] = date(today.year + 5, today.month, min(today.day, 28)) + timedelta(days=4)
    resp = _submit(client, master, setup["qualification_id"], **kwargs)
    assert (resp.status_code, resp.json()["error"]["code"]) == (http, code)
    assert _count(MasterQualification) == 0 and _count(Attachment) == 0 and _objects() == []


def test_valid_until_today_and_maximum_validity_are_accepted(
    client: TestClient, setup: dict[str, Any]
) -> None:
    today = _today()
    assert _submit(client, _master(client), setup["qualification_id"], valid_until=today).status_code == 201
    longest = svc._add_months(today, 60)
    assert _submit(client, _master(client), setup["qualification_id"], valid_until=longest).status_code == 201


def test_only_active_qualification_types_accept_submissions(
    client: TestClient, setup: dict[str, Any]
) -> None:
    master = _master(client)
    assert _submit(client, master, uuid.uuid4()).status_code == 404
    for type_status in ("draft", "archived"):
        with SessionLocal() as db:
            db.execute(update(Qualification).values(status=type_status))
            db.commit()
        resp = _submit(client, master, setup["qualification_id"])
        assert resp.json()["error"]["code"] == "QUALIFICATION_TYPE_NOT_ACTIVE"
    assert _objects() == []


# --- renewal (owner decision 2026-11-02) --------------------------------------------------------------------


def _rows(master: Master) -> list[tuple[str, date | None, int]]:
    with SessionLocal() as db:
        return [
            (r.status, r.valid_until, r.version)
            for r in db.scalars(
                select(MasterQualification)
                .where(MasterQualification.master_id == master.master_id)
                .order_by(MasterQualification.submitted_at)
            )
        ]


def test_first_submission_then_repeat_is_refused_while_pending(
    client: TestClient, setup: dict[str, Any]
) -> None:
    master = _master(client)
    assert _submit(client, master, setup["qualification_id"]).status_code == 201
    repeat = _submit(client, master, setup["qualification_id"])  # e.g. a retried request
    assert (repeat.status_code, repeat.json()["error"]["code"]) == (409, "QUALIFICATION_SUBMISSION_PENDING")
    assert len(_rows(master)) == 1 and len(_objects()) == 1


@pytest.mark.parametrize(
    ("offset", "allowed"), [(None, False), (30, False), (0, False), (-1, True), (-400, True)]
)
def test_renewal_only_after_the_verified_qualification_expired(
    client: TestClient, setup: dict[str, Any], offset: int | None, allowed: bool
) -> None:
    master = _master(client)
    assert _submit(client, master, setup["qualification_id"]).status_code == 201
    today = _today()
    until = None if offset is None else today + timedelta(days=offset)
    _decide(
        MasterQualification.master_id == master.master_id,
        MasterQualification,
        "verified",
        setup["admin_id"],
        valid_until=until,
    )
    before = _rows(master)
    resp = _submit(client, master, setup["qualification_id"])
    if not allowed:
        assert (resp.status_code, resp.json()["error"]["code"]) == (409, "QUALIFICATION_STILL_VALID")
        assert resp.json()["error"]["details"] == {"valid_until": until.isoformat() if until else None}
        assert _rows(master) == before
        return
    assert resp.status_code == 201
    # The expired verified row is untouched; the renewal is a new pending row.
    assert _rows(master) == [*before, ("submitted", today + timedelta(days=365), 1)]
    second = _submit(client, master, setup["qualification_id"])
    assert second.json()["error"]["code"] == "QUALIFICATION_SUBMISSION_PENDING"


@pytest.mark.parametrize("previous", ["rejected", "revoked", "withdrawn"])
def test_resubmission_after_a_closed_submission(
    client: TestClient, setup: dict[str, Any], previous: str
) -> None:
    master = _master(client)
    assert _submit(client, master, setup["qualification_id"]).status_code == 201
    if previous == "withdrawn":
        sub_id = client.get("/api/v1/master/capabilities", headers=master.h).json()["qualifications"][0]["id"]
        assert (
            client.post(f"/api/v1/master/qualifications/{sub_id}/withdraw", headers=master.h).status_code
            == 200
        )
    else:
        _decide(
            MasterQualification.master_id == master.master_id,
            MasterQualification,
            previous,
            setup["admin_id"],
        )
    assert _submit(client, master, setup["qualification_id"]).status_code == 201
    assert [r[0] for r in _rows(master)] == [previous, "submitted"]


def test_renewal_does_not_admit_until_verified(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    admin_id = setup["admin_id"]
    client.post("/api/v1/master/specialisations", json={"specialisation_id": str(SPEC)}, headers=master.h)
    client.post("/api/v1/master/competencies", json={"service_id": str(SERVICE)}, headers=master.h)
    _submit(client, master, setup["qualification_id"])
    _set_profile(master, "approved", admin_id)
    _decide(MasterSpecialisation.master_id == master.master_id, MasterSpecialisation, "approved", admin_id)
    _decide(MasterCompetency.master_id == master.master_id, MasterCompetency, "verified", admin_id)
    _decide(
        MasterQualification.master_id == master.master_id,
        MasterQualification,
        "verified",
        admin_id,
        valid_until=_today() - timedelta(days=1),
    )

    def competency() -> dict[str, Any]:
        result: dict[str, Any] = client.get("/api/v1/master/capabilities", headers=master.h).json()[
            "competencies"
        ][0]
        return result

    assert [r["code"] for r in competency()["reasons"]] == ["QUALIFICATION_EXPIRED"]
    assert _submit(client, master, setup["qualification_id"]).status_code == 201
    assert [r["code"] for r in competency()["reasons"]] == ["QUALIFICATION_EXPIRED"]
    _decide(MasterQualification.status == "submitted", MasterQualification, "verified", admin_id)
    assert competency() == competency() | {"eligible": True, "reasons": []}
    quals = client.get("/api/v1/master/capabilities", headers=master.h).json()["qualifications"]
    assert sorted((q["status"], q["expired"]) for q in quals) == [("verified", False), ("verified", True)]


def test_concurrent_submissions_create_exactly_one(client: TestClient, setup: dict[str, Any]) -> None:
    """Parallel requests of one master serialise on the master row lock: one wins, the rest see it pending."""
    master = _master(client)
    _submit(client, master, setup["qualification_id"])
    _decide(
        MasterQualification.master_id == master.master_id,
        MasterQualification,
        "verified",
        setup["admin_id"],
        valid_until=_today() - timedelta(days=1),
    )
    storage = get_storage()
    files = [ValidFile(PDF, "application/pdf", "0" * 64)]
    data = svc.SubmissionIn(setup["qualification_id"], SECRET_NUMBER, _today() + timedelta(days=30))
    barrier = threading.Barrier(6)
    outcomes: list[str] = []

    def attempt() -> None:
        with SessionLocal() as db:
            user = db.get(User, master.user_id)
            assert user is not None
            barrier.wait()
            try:
                svc.submit_qualification(db, storage, user, data, files)
                outcomes.append("created")
            except AppError as exc:
                outcomes.append(exc.code)

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["QUALIFICATION_SUBMISSION_PENDING"] * 5 + ["created"]
    assert [r[0] for r in _rows(master)] == ["verified", "submitted"]
    # Only the winner's file was kept: the original submission's file plus one.
    assert len(_objects()) == 2 == _count(Attachment)


class _FailingStorage(LocalStorage):
    def __init__(self, root: Any, fail_on: int) -> None:
        super().__init__(root)
        self.calls, self.fail_on = 0, fail_on

    def put(self, key: str, data: bytes) -> None:
        self.calls += 1
        if self.calls == self.fail_on:
            raise OSError("disk full")
        super().put(key, data)


def test_failed_storage_or_commit_leaves_no_record_and_no_file(
    client: TestClient, setup: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = _master(client)
    files = [ValidFile(PDF, "application/pdf", "0" * 64), ValidFile(PNG, "image/png", "1" * 64)]
    data = svc.SubmissionIn(setup["qualification_id"], SECRET_NUMBER, _today() + timedelta(days=30))
    storage = _FailingStorage(tmp_path, fail_on=2)
    with SessionLocal() as db:
        user = db.get(User, master.user_id)
        assert user is not None
        with pytest.raises(OSError, match="disk full"):
            svc.submit_qualification(db, storage, user, data, files)
    assert list(storage.objects()) == [] and _count(MasterQualification) == 0

    storage = _FailingStorage(tmp_path, fail_on=0)
    with SessionLocal() as db:
        user = db.get(User, master.user_id)
        assert user is not None

        def broken_commit() -> None:
            raise RuntimeError("connection lost")

        monkeypatch.setattr(db, "commit", broken_commit)
        with pytest.raises(RuntimeError, match="connection lost"):
            svc.submit_qualification(db, storage, user, data, files)
    assert list(storage.objects()) == [] and _count(MasterQualification) == 0 and _count(Attachment) == 0


# --- evidence files -----------------------------------------------------------------------------------------


def _file_url(sub_id: str, file_id: str) -> str:
    return f"/api/v1/master/qualifications/{sub_id}/files/{file_id}"


def test_owner_downloads_and_views_own_files_with_logging(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    body = _submit(client, master, setup["qualification_id"], files=[("a.png", PNG, "image/png")]).json()
    sub_id, file_id = body["id"], body["files"][0]["id"]
    download = client.get(_file_url(sub_id, file_id), headers=master.h)
    assert download.status_code == 200 and download.content == PNG
    assert download.headers["content-type"] == "image/png"
    assert download.headers["content-disposition"] == f'attachment; filename="{file_id}.png"'
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in download.headers["cache-control"]
    view = client.get(_file_url(sub_id, file_id), params={"mode": "view"}, headers=master.h)
    assert view.headers["content-disposition"].startswith("inline")
    assert view.headers["content-security-policy"].startswith("sandbox")
    assert client.get(_file_url(sub_id, file_id), params={"mode": "raw"}, headers=master.h).status_code == 422
    with SessionLocal() as db:
        logs = db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "attachment").order_by(AuditLog.created_at)
        ).all()
    assert [(log.action, log.actor_id, str(log.entity_id)) for log in logs] == [
        ("attachment.downloaded", master.user_id, file_id),
        ("attachment.viewed", master.user_id, file_id),
    ]
    assert logs[0].after == {"submission_id": sub_id, "master_id": str(master.master_id), "mode": "download"}


def test_files_of_other_masters_or_other_submissions_are_never_served(
    client: TestClient, setup: dict[str, Any]
) -> None:
    owner, intruder = _master(client), _master(client)
    other = Qualification(name="Gāzes iekārtas", status="active", requires_document=True)
    with SessionLocal() as db:
        db.add(other)
        db.commit()
        other_id = other.id
    mine = _submit(client, owner, setup["qualification_id"]).json()
    second = _submit(client, owner, other_id, files=[("b.pdf", PDF, "application/pdf")]).json()
    theirs = _submit(client, intruder, setup["qualification_id"]).json()
    sub, file = mine["id"], mine["files"][0]["id"]
    # Other masters' IDs look exactly like random IDs (no existence leak).
    attempts = [
        (intruder, sub, file, "SUBMISSION_NOT_FOUND"),  # someone else's submission and file
        (intruder, theirs["id"], file, "FILE_NOT_FOUND"),  # own submission, someone else's file ID
        (owner, sub, second["files"][0]["id"], "FILE_NOT_FOUND"),  # own file, but of another submission
        (owner, second["id"], file, "FILE_NOT_FOUND"),
        (owner, sub, str(uuid.uuid4()), "FILE_NOT_FOUND"),
        (owner, str(uuid.uuid4()), file, "SUBMISSION_NOT_FOUND"),
    ]
    for actor, sub_id, file_id, code in attempts:
        resp = client.get(_file_url(sub_id, file_id), headers=actor.h)
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, code)
    assert client.post(f"/api/v1/master/qualifications/{sub}/withdraw", headers=intruder.h).status_code == 404
    assert _count(AuditLog, AuditLog.entity_type == "attachment") == 0
    with SessionLocal() as db:
        assert (
            db.scalar(select(MasterQualification.status).where(MasterQualification.id == uuid.UUID(sub)))
            == "submitted"
        )


def test_withdrawn_submission_keeps_its_files(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    body = _submit(client, master, setup["qualification_id"]).json()
    withdrawn = client.post(f"/api/v1/master/qualifications/{body['id']}/withdraw", headers=master.h).json()
    assert withdrawn["status"] == "withdrawn" and withdrawn["files"] == body["files"]
    again = client.post(f"/api/v1/master/qualifications/{body['id']}/withdraw", headers=master.h)
    assert again.json()["error"]["code"] == "CANNOT_WITHDRAW"
    assert client.get(_file_url(body["id"], body["files"][0]["id"]), headers=master.h).status_code == 200
    assert len(_objects()) == 1


def test_capabilities_flag_expiring_and_expired_qualifications(
    client: TestClient, setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    master = _master(client)
    _submit(client, master, setup["qualification_id"])
    today = _today()
    expected = {29: (False, True), 30: (False, True), 31: (False, False), 0: (False, True), -1: (True, False)}
    for offset, flags in expected.items():
        _decide(
            MasterQualification.master_id == master.master_id,
            MasterQualification,
            "verified",
            setup["admin_id"],
            valid_until=today + timedelta(days=offset),
        )
        [q] = client.get("/api/v1/master/capabilities", headers=master.h).json()["qualifications"]
        assert (q["expired"], q["expires_soon"]) == flags, offset


def test_uploads_are_rate_limited(
    client: TestClient, setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_upload", 2)
    first, second = _master(client), _master(client)
    # Failed attempts count too, and the window is per client IP (shared by masters behind one address).
    assert _submit(client, first, uuid.uuid4()).status_code == 404
    assert _submit(client, second, setup["qualification_id"]).status_code == 201
    limited = _submit(client, second, setup["qualification_id"])
    assert (limited.status_code, limited.json()["error"]["code"]) == (429, "RATE_LIMITED")
    assert _count(MasterQualification) == 1 and len(_objects()) == 1
    # Other master endpoints are not upload-limited.
    assert client.get("/api/v1/master/capabilities", headers=first.h).status_code == 200


# --- final checks (step 4.3 review) -------------------------------------------------------------------------


def _full_rows(master: Master) -> dict[uuid.UUID, dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(MasterQualification).where(MasterQualification.master_id == master.master_id)
        )
        return {
            r.id: {c.name: getattr(r, c.name) for c in MasterQualification.__table__.columns} for r in rows
        }


def _attachment_rows() -> dict[uuid.UUID, dict[str, Any]]:
    with SessionLocal() as db:
        return {
            a.id: {c.name: getattr(a, c.name) for c in Attachment.__table__.columns}
            for a in db.scalars(select(Attachment))
        }


def test_renewal_leaves_every_earlier_row_and_file_unchanged(
    client: TestClient, setup: dict[str, Any]
) -> None:
    master, admin_id, qid = _master(client), setup["admin_id"], setup["qualification_id"]
    today = _today()
    history = [
        ("rejected", today + timedelta(days=100), "Neskaidrs skenējums"),
        ("revoked", today + timedelta(days=200), "Sertifikāts anulēts"),
        ("withdrawn", today + timedelta(days=300), None),
        ("verified", today - timedelta(days=1), None),
    ]
    for status, until, reason in history:
        assert _submit(client, master, qid).status_code == 201
        values: dict[str, Any] = {"status": status, "decision_reason": reason, "valid_until": until}
        if status != "withdrawn":
            values |= {"decided_by": admin_id, "decided_at": datetime.now(UTC)}
        with SessionLocal() as db:
            db.execute(
                update(MasterQualification).where(MasterQualification.status == "submitted").values(**values)
            )
            db.commit()
    rows_before, files_before = _full_rows(master), _attachment_rows()
    objects_before = set(_objects())
    resp = _submit(client, master, qid)
    assert resp.status_code == 201
    rows_after, files_after = _full_rows(master), _attachment_rows()
    new_id = uuid.UUID(resp.json()["id"])
    assert {k: v for k, v in rows_after.items() if k != new_id} == rows_before
    assert (rows_after[new_id]["status"], rows_after[new_id]["version"]) == ("submitted", 1)
    assert {k: v for k, v in files_after.items() if v["entity_id"] != new_id} == files_before
    assert objects_before < set(_objects())


def _submit_in_thread(master: Master, qid: uuid.UUID, outcome: list[str]) -> threading.Thread:
    data = svc.SubmissionIn(qid, SECRET_NUMBER, _today() + timedelta(days=30))

    def run() -> None:
        with SessionLocal() as db:
            user = db.get(User, master.user_id)
            assert user is not None
            try:
                svc.submit_qualification(
                    db, get_storage(), user, data, [ValidFile(PDF, "application/pdf", "0" * 64)]
                )
                outcome.append("created")
            except AppError as exc:
                outcome.append(exc.code)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


@pytest.mark.parametrize("change", ["verified_becomes_valid", "pending_submission_appears"])
def test_master_row_lock_makes_the_check_see_concurrent_changes(
    client: TestClient, setup: dict[str, Any], change: str
) -> None:
    """PostgreSQL row lock: a submission waits for a concurrent writer of the same master and then re-reads.

    Without `FOR UPDATE` the submission would check the old state (expired verified, nothing pending) and
    create a row next to a now-valid qualification.
    """
    master, qid = _master(client), setup["qualification_id"]
    _submit(client, master, qid)
    _decide(
        MasterQualification.master_id == master.master_id,
        MasterQualification,
        "verified",
        setup["admin_id"],
        valid_until=_today() - timedelta(days=1),
    )
    holder = SessionLocal()
    holder.execute(select(MasterProfile).where(MasterProfile.id == master.master_id).with_for_update())
    outcome: list[str] = []
    thread = _submit_in_thread(master, qid, outcome)
    thread.join(timeout=1.0)
    assert thread.is_alive() and outcome == []  # blocked on the master row
    if change == "verified_becomes_valid":
        # E.g. an admin correcting the expiry date under the same lock (step 4.4 locks the master row too).
        holder.execute(update(MasterQualification).values(valid_until=_today() + timedelta(days=30)))
    else:
        holder.add(MasterQualification(master_id=master.master_id, qualification_id=qid))
    holder.commit()
    holder.close()
    thread.join(timeout=10)
    expected = (
        "QUALIFICATION_STILL_VALID"
        if change == "verified_becomes_valid"
        else "QUALIFICATION_SUBMISSION_PENDING"
    )
    assert outcome == [expected]
    assert _count(MasterQualification, MasterQualification.status == "submitted") == (
        0 if change == "verified_becomes_valid" else 1
    )


@pytest.mark.parametrize(("state", "created"), [("first", 1), ("valid_verified", 0), ("expired_verified", 1)])
def test_parallel_http_submissions(
    client: TestClient, setup: dict[str, Any], state: str, created: int
) -> None:
    master, qid = _master(client), setup["qualification_id"]
    if state != "first":
        _submit(client, master, qid)
        offset = 30 if state == "valid_verified" else -1
        _decide(
            MasterQualification.master_id == master.master_id,
            MasterQualification,
            "verified",
            setup["admin_id"],
            valid_until=_today() + timedelta(days=offset),
        )
    before = _count(MasterQualification)
    barrier = threading.Barrier(6)
    statuses: list[int] = []

    def run() -> None:
        local = TestClient(client.app)
        barrier.wait()
        statuses.append(_submit(local, master, qid).status_code)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201] * created + [409] * (6 - created)
    assert _count(MasterQualification) == before + created
    assert _count(MasterQualification, MasterQualification.status == "submitted") == created
    assert len(_objects()) == _count(Attachment)  # losers left no files behind


def test_spoofed_extensions_are_judged_by_content(client: TestClient, setup: dict[str, Any]) -> None:
    master = _master(client)
    body = _submit(
        client, master, setup["qualification_id"], files=[("cert.pdf", PNG, "application/pdf")]
    ).json()
    assert body["files"][0]["mime_type"] == "image/png"
    download = client.get(_file_url(body["id"], body["files"][0]["id"]), headers=master.h)
    assert download.headers["content-type"] == "image/png" and download.headers[
        "content-disposition"
    ].endswith('.png"')
    for name, data in [
        ("evil.jpg", b"<?php system($_GET[1]); ?>"),
        ("x.heic", b"\x00\x00\x00\x18ftypavif" + b"\x00" * 8),
    ]:
        other = _master(client)
        resp = _submit(client, other, setup["qualification_id"], files=[(name, data, "image/jpeg")])
        assert (resp.status_code, resp.json()["error"]["code"]) == (415, "UNSUPPORTED_FILE_TYPE")


def test_documents_are_reachable_only_through_the_owner_route(
    client: TestClient, setup: dict[str, Any], admin_token: str
) -> None:
    master = _master(client)
    body = _submit(client, master, setup["qualification_id"]).json()
    sub_id, file_id = body["id"], body["files"][0]["id"]
    with SessionLocal() as db:
        storage_key = db.scalar(select(Attachment.storage_key))
    # Admins read documents through the admin API (step 4.4), not through the master's own routes.
    assert client.get(_file_url(sub_id, file_id), headers=auth(admin_token)).status_code == 403
    # The storage key is never an identifier (it parses as a UUID but matches no file); no response shows it.
    resp = client.get(_file_url(sub_id, str(storage_key)), headers=master.h)
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "FILE_NOT_FOUND")
    caps = client.get("/api/v1/master/capabilities", headers=master.h).text
    assert str(storage_key) not in caps and str(storage_key) not in json.dumps(body)
    assert _count(AuditLog, AuditLog.entity_type == "attachment") == 0
