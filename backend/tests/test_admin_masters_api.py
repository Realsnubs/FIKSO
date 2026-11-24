"""Admin master views and review queue (step 4.4.2): access, filters, paging, history, reasons, no leaks."""

import base64
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
from app.models import (
    Attachment,
    AuditLog,
    CatalogueService,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications
from app.services import eligibility, master_admin
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register
from tests.files import PDF

SPEC = seed_id("cm-s01")
OTHER_SPEC = seed_id("cm-s02")
SERVICE = seed_id("cm-s01-1")
OTHER_SERVICE = seed_id("cm-s01-2")
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
NUMBER = "LV-ELEC-778899"
PATHS = ("/api/v1/admin/masters", "/api/v1/admin/review-queue")


@dataclass
class M:
    id: uuid.UUID
    user_id: uuid.UUID
    token: str


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID
    other_qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([SERVICE, OTHER_SERVICE]))
            .values(status="inactive")
        )
        electric = Qualification(
            name="Elektrodrošība",
            status="active",
            requires_document=True,
            requires_expiry_date=True,
            verifier_instructions="Pārbaudīt reģistrā",
        )
        gas = Qualification(
            name="Gāzes sertifikāts", status="active", verifier_instructions="Zvanīt izdevējam"
        )
        db.add_all([electric, gas])
        db.flush()
        db.execute(service_qualifications.insert().values(service_id=SERVICE, qualification_id=electric.id))
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, electric.id, gas.id)


def _master(client: TestClient) -> M:
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
    assert master_id is not None
    return M(master_id, user_id, body["access_token"])


def _decided(fx: Fx, at: datetime = T0) -> dict[str, Any]:
    return {"decided_by": fx.admin_id, "decided_at": at}


def _set(model: Any, where: Any, **values: Any) -> None:
    with SessionLocal() as db:
        db.execute(update(model).where(where).values(**values))
        db.commit()


def _add(*rows: Any) -> None:
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def _audit_count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AuditLog)) or 0


def _pages(client: TestClient, fx: Fx, path: str, limit: int, **params: Any) -> list[list[dict[str, Any]]]:
    pages, cursor = [], None
    while True:
        query = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        resp = client.get(path, params=query, headers=fx.admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages


# --- access -------------------------------------------------------------------------------------------------


def test_only_admins_read(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    customer = register(client, "client")["access_token"]
    paths = (*PATHS, f"/api/v1/admin/masters/{master.id}")
    for path in paths:
        assert client.get(path).status_code == 401
        for token in (master.token, customer):
            resp = client.get(path, headers=auth(token))
            assert resp.status_code == 403, path
        assert client.get(path, headers=fx.admin).status_code == 200


def test_reads_write_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    before = _audit_count()
    for path in (*PATHS, f"/api/v1/admin/masters/{master.id}"):
        client.get(path, headers=fx.admin)
    assert _audit_count() == before


# --- list ---------------------------------------------------------------------------------------------------


def test_list_counts_pending_items_and_filters(client: TestClient, fx: Fx) -> None:
    pending, approved, rejected, deleted = (_master(client) for _ in range(4))
    _add(
        MasterSpecialisation(master_id=pending.id, specialisation_id=SPEC),
        MasterSpecialisation(master_id=pending.id, specialisation_id=OTHER_SPEC),
        MasterCompetency(master_id=pending.id, service_id=SERVICE),
        MasterQualification(master_id=pending.id, qualification_id=fx.qualification_id),
        # Decided or withdrawn rows are history, not pending work.
        MasterSpecialisation(
            master_id=approved.id, specialisation_id=SPEC, status="approved", **_decided(fx)
        ),
        MasterSpecialisation(master_id=rejected.id, specialisation_id=SPEC, status="withdrawn"),
        MasterQualification(master_id=deleted.id, qualification_id=fx.qualification_id),
    )
    _set(MasterProfile, MasterProfile.id == approved.id, approval_status="approved", **_decided(fx))
    _set(MasterProfile, MasterProfile.id == rejected.id, approval_status="rejected", **_decided(fx))
    _set(User, User.id == deleted.user_id, deleted_at=T0)

    def ids(**params: Any) -> set[uuid.UUID]:
        resp = client.get("/api/v1/admin/masters", params=params, headers=fx.admin)
        assert resp.status_code == 200, resp.text
        return {uuid.UUID(i["id"]) for i in resp.json()["items"]}

    assert ids() == {pending.id, approved.id, rejected.id}  # deleted accounts are not listed
    assert ids(approval_status="approved") == {approved.id}
    assert ids(approval_status="rejected") == {rejected.id}
    assert ids(has_pending=True) == {pending.id}
    assert ids(has_pending=False) == {approved.id, rejected.id}
    assert ids(approval_status="approved", has_pending=True) == set()

    [item] = client.get("/api/v1/admin/masters", params={"has_pending": True}, headers=fx.admin).json()[
        "items"
    ]
    assert item["pending"] == {"specialisations": 2, "competencies": 1, "qualifications": 1}
    assert (item["user_id"], item["approval_status"], item["version"]) == (
        str(pending.user_id),
        "pending_approval",
        1,
    )
    assert item["email"] and item["full_name"] and item["user_status"] == "active"

    assert (
        client.get("/api/v1/admin/masters", params={"approval_status": "x"}, headers=fx.admin).status_code
        == 422
    )


def test_list_pages_newest_first_without_gaps(client: TestClient, fx: Fx) -> None:
    masters = [_master(client) for _ in range(5)]
    for n, master in enumerate(masters):
        # Two masters share a timestamp: the ID breaks the tie, so nothing is skipped or repeated.
        _set(MasterProfile, MasterProfile.id == master.id, created_at=T0 + timedelta(minutes=min(n, 3)))
    pages = _pages(client, fx, "/api/v1/admin/masters", 2)
    assert [len(p) for p in pages] == [2, 2, 1]
    listed = [uuid.UUID(i["id"]) for page in pages for i in page]
    assert sorted(listed) == sorted(m.id for m in masters)
    times = [i["registered_at"] for page in pages for i in page]
    assert times == sorted(times, reverse=True)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!",
        base64.urlsafe_b64encode(b"one-part").decode(),
        base64.urlsafe_b64encode(b"2026-01-01|not-a-uuid|x|y").decode(),
        base64.urlsafe_b64encode(b"yesterday|00000000-0000-0000-0000-000000000000").decode(),
        base64.urlsafe_b64encode(b"yesterday|competency|00000000-0000-0000-0000-000000000000").decode(),
    ],
)
def test_invalid_cursor(client: TestClient, fx: Fx, path: str, cursor: str) -> None:
    resp = client.get(path, params={"cursor": cursor}, headers=fx.admin)
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "INVALID_CURSOR"


# --- detail -------------------------------------------------------------------------------------------------


def test_detail_shows_full_history_reasons_and_verifier_data(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    with SessionLocal() as db:
        today = business_today(db)
    resp = client.post(
        "/api/v1/master/qualifications",
        data={"qualification_id": str(fx.qualification_id), "valid_until": str(today + timedelta(days=200))},
        files=[("files", ("a.pdf", PDF, "application/pdf"))],
        headers=auth(master.token),
    )
    assert resp.status_code == 201, resp.text
    renewal_id = uuid.UUID(resp.json()["id"])
    old_rejected = MasterQualification(
        master_id=master.id,
        qualification_id=fx.qualification_id,
        status="rejected",
        document_number=NUMBER,
        valid_until=today + timedelta(days=100),
        decision_reason="Neskaidrs skenējums",
        submitted_at=T0,
        **_decided(fx),
    )
    expired = MasterQualification(
        master_id=master.id,
        qualification_id=fx.qualification_id,
        status="verified",
        valid_until=today - timedelta(days=1),
        submitted_at=T0 + timedelta(days=1),
        **_decided(fx),
    )
    expiring = MasterQualification(
        master_id=master.id,
        qualification_id=fx.other_qualification_id,
        status="verified",
        valid_until=today + timedelta(days=5),
        **_decided(fx),
    )
    _add(
        old_rejected,
        expired,
        expiring,
        MasterSpecialisation(master_id=master.id, specialisation_id=SPEC, status="approved", **_decided(fx)),
        MasterSpecialisation(
            master_id=master.id, specialisation_id=OTHER_SPEC, status="withdrawn", version=2
        ),
        MasterCompetency(master_id=master.id, service_id=SERVICE, status="verified", **_decided(fx)),
        MasterCompetency(
            master_id=master.id,
            service_id=OTHER_SERVICE,
            status="revoked",
            decision_reason="Sūdzības",
            **_decided(fx),
        ),
    )
    _set(MasterProfile, MasterProfile.id == master.id, approval_status="approved", **_decided(fx), version=2)

    resp = client.get(f"/api/v1/admin/masters/{master.id}", headers=fx.admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["approval_status"], body["decided_by"], body["version"]) == ("approved", str(fx.admin_id), 2)
    assert body["user_id"] == str(master.user_id) and body["today"] == today.isoformat()

    specs = {s["specialisation_id"]: s for s in body["specialisations"]}
    assert specs[str(SPEC)]["status"] == "approved" and specs[str(SPEC)]["decided_by"] == str(fx.admin_id)
    assert (specs[str(OTHER_SPEC)]["status"], specs[str(OTHER_SPEC)]["version"]) == ("withdrawn", 2)

    # The same reasons as the shared eligibility rule (R-MST-12): never a separate admin computation.
    competencies = {c["service_id"]: c for c in body["competencies"]}
    with SessionLocal() as db:
        for service_id in (SERVICE, OTHER_SERVICE):
            expected = eligibility.explain(db, service_id, [master.id], today)[master.id]
            got = competencies[str(service_id)]
            assert got["eligible"] == expected.eligible
            assert got["reasons"] == [{"code": r.code, "details": r.details} for r in expected.reasons]
    assert [r["code"] for r in competencies[str(SERVICE)]["reasons"]] == ["QUALIFICATION_EXPIRED"]
    assert competencies[str(OTHER_SERVICE)]["decision_reason"] == "Sūdzības"

    submissions = {uuid.UUID(q["id"]): q for q in body["qualifications"]}
    assert set(submissions) == {renewal_id, old_rejected.id, expired.id, expiring.id}  # nothing hidden
    assert submissions[old_rejected.id]["document_number"] == NUMBER  # admins verify the full number
    assert submissions[old_rejected.id]["decision_reason"] == "Neskaidrs skenējums"
    assert (submissions[expired.id]["expired"], submissions[expired.id]["expires_soon"]) == (True, False)
    assert (submissions[expiring.id]["expired"], submissions[expiring.id]["expires_soon"]) == (False, True)
    assert (submissions[renewal_id]["status"], submissions[renewal_id]["version"]) == ("submitted", 1)
    assert len(submissions[renewal_id]["files"]) == 1
    rules = {r["name"]: r for r in body["qualification_types"]}
    assert rules["Elektrodrošība"]["verifier_instructions"] == "Pārbaudīt reģistrā"
    assert rules["Gāzes sertifikāts"]["verifier_instructions"] == "Zvanīt izdevējam"

    with SessionLocal() as db:
        [attachment] = db.scalars(select(Attachment).where(Attachment.entity_id == renewal_id)).all()
    for secret in (attachment.storage_key, attachment.sha256, "storage_key", "sha256"):
        assert secret not in resp.text


def test_detail_of_unknown_or_non_master_ids(client: TestClient, fx: Fx) -> None:
    master, gone = _master(client), _master(client)
    _set(User, User.id == gone.user_id, deleted_at=T0)
    for target in (uuid.uuid4(), master.user_id, fx.admin_id, gone.id):
        resp = client.get(f"/api/v1/admin/masters/{target}", headers=fx.admin)
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "MASTER_NOT_FOUND"
    assert client.get("/api/v1/admin/masters/not-a-uuid", headers=fx.admin).status_code == 422


# --- review queue -------------------------------------------------------------------------------------------


def test_queue_lists_only_pending_items_oldest_first(client: TestClient, fx: Fx) -> None:
    first, second, blocked = _master(client), _master(client), _master(client)
    submission = MasterQualification(
        master_id=second.id,
        qualification_id=fx.qualification_id,
        valid_until=date(2030, 1, 31),
        submitted_at=T0 + timedelta(hours=1),
    )
    _add(
        MasterSpecialisation(
            master_id=first.id, specialisation_id=SPEC, requested_at=T0 + timedelta(hours=3)
        ),
        MasterCompetency(master_id=first.id, service_id=SERVICE, declared_at=T0 + timedelta(hours=2)),
        submission,
        MasterSpecialisation(master_id=second.id, specialisation_id=SPEC, requested_at=T0, version=3),
        # Not pending: decided, withdrawn, and a verified qualification.
        MasterSpecialisation(
            master_id=second.id, specialisation_id=OTHER_SPEC, status="rejected", **_decided(fx)
        ),
        MasterCompetency(master_id=second.id, service_id=SERVICE, status="withdrawn"),
        MasterQualification(
            master_id=first.id, qualification_id=fx.qualification_id, status="verified", **_decided(fx)
        ),
        # A rejected profile's pending items stay queued (owner decision 2026-11-02), as do a blocked user's.
        MasterCompetency(master_id=blocked.id, service_id=OTHER_SERVICE, declared_at=T0 + timedelta(hours=4)),
    )
    _set(MasterProfile, MasterProfile.id == first.id, approval_status="rejected", **_decided(fx))
    _set(User, User.id == blocked.user_id, status="blocked")

    body = client.get("/api/v1/admin/review-queue", headers=fx.admin).json()
    items = [(i["kind"], i["master_id"], i["item_id"]) for i in body["items"]]
    assert items == [
        ("specialisation", str(second.id), str(SPEC)),
        ("qualification", str(second.id), str(submission.id)),
        ("competency", str(first.id), str(SERVICE)),
        ("specialisation", str(first.id), str(SPEC)),
        ("competency", str(blocked.id), str(OTHER_SERVICE)),
    ]
    by_key = {(i["kind"], i["master_id"], i["item_id"]): i for i in body["items"]}
    spec = by_key[("specialisation", str(second.id), str(SPEC))]
    assert spec["version"] == 3 and spec["name"] and spec["w_id"] is None
    competency = by_key[("competency", str(first.id), str(SERVICE))]
    assert competency["w_id"] == "W071" and competency["approval_status"] == "rejected"
    assert by_key[("qualification", str(second.id), str(submission.id))]["valid_until"] == "2030-01-31"
    assert by_key[("competency", str(blocked.id), str(OTHER_SERVICE))]["user_status"] == "blocked"

    kinds = client.get("/api/v1/admin/review-queue", params={"kind": "competency"}, headers=fx.admin).json()
    assert [i["item_id"] for i in kinds["items"]] == [str(SERVICE), str(OTHER_SERVICE)]
    assert client.get("/api/v1/admin/review-queue", params={"kind": "x"}, headers=fx.admin).status_code == 422

    # One item per page: every item exactly once, same order.
    pages = _pages(client, fx, "/api/v1/admin/review-queue", 1)
    assert [(i["kind"], i["master_id"], i["item_id"]) for page in pages for i in page] == items


def test_decided_item_leaves_the_queue(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    _add(MasterSpecialisation(master_id=master.id, specialisation_id=SPEC))
    [item] = client.get("/api/v1/admin/review-queue", headers=fx.admin).json()["items"]
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        master_admin.decide(
            db, admin, master.id, "specialisation", SPEC, master_admin.Decision("approve", item["version"])
        )
    assert client.get("/api/v1/admin/review-queue", headers=fx.admin).json()["items"] == []
    [listed] = client.get("/api/v1/admin/masters", headers=fx.admin).json()["items"]
    assert listed["pending"] == {"specialisations": 0, "competencies": 0, "qualifications": 0}
