"""Block 4.4 as one system (step 4.4.9): route-wide access rules, the full master lifecycle through the API,
audit/event pairing, and regressions found in the final review."""

import re
import uuid
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.integrations.storage import get_storage
from app.main import app
from app.models import (
    AuditLog,
    CatalogueService,
    DomainEvent,
    MasterCompetency,
    MasterProfile,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications
from app.services import eligibility, master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register
from tests.files import PDF

SPEC = seed_id("cm-s01")
REGULATED = seed_id("cm-s01-1")
PLAIN = seed_id("cm-s01-2")
ADMIN_MASTER_ROUTES = {
    ("GET", "/api/v1/admin/masters"),
    ("GET", "/api/v1/admin/masters/{master_id}"),
    ("GET", "/api/v1/admin/masters/{master_id}/work"),
    ("GET", "/api/v1/admin/review-queue"),
    ("POST", "/api/v1/admin/masters/{master_id}/approve"),
    ("POST", "/api/v1/admin/masters/{master_id}/reject"),
    ("POST", "/api/v1/admin/masters/{master_id}/specialisations/{specialisation_id}/approve"),
    ("POST", "/api/v1/admin/masters/{master_id}/specialisations/{specialisation_id}/reject"),
    ("POST", "/api/v1/admin/masters/{master_id}/specialisations/{specialisation_id}/revoke"),
    ("POST", "/api/v1/admin/masters/{master_id}/competencies/{service_id}/verify"),
    ("POST", "/api/v1/admin/masters/{master_id}/competencies/{service_id}/reject"),
    ("POST", "/api/v1/admin/masters/{master_id}/competencies/{service_id}/revoke"),
    ("POST", "/api/v1/admin/masters/{master_id}/competencies/bulk-verify/preview"),
    ("POST", "/api/v1/admin/masters/{master_id}/competencies/bulk-verify"),
    ("POST", "/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/verify"),
    ("POST", "/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/reject"),
    ("POST", "/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/revoke"),
    ("GET", "/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/files/{file_id}"),
}


@pytest.fixture
def ids(client: TestClient, admin_token: str) -> Iterator[dict[str, Any]]:
    with SessionLocal() as db:
        seed_catalogue(db)
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([REGULATED, PLAIN]))
            .values(status="inactive")
        )
        qualification = Qualification(name="Elektrodrošība", status="active", requires_document=True)
        db.add(qualification)
        db.flush()
        db.execute(
            service_qualifications.insert().values(service_id=REGULATED, qualification_id=qualification.id)
        )
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        yield {"admin": auth(admin_token), "admin_id": admin_id, "qualification_id": qualification.id}


def _admin_master_routes() -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(("/api/v1/admin/masters", "/api/v1/admin/review-queue"))
        for method in operations
    }


# --- access, route-wide -------------------------------------------------------------------------------------


def test_every_admin_master_route_is_known() -> None:
    """A new admin route must be added here, so it is covered by the access test below."""
    assert _admin_master_routes() == ADMIN_MASTER_ROUTES


@pytest.mark.parametrize(("method", "path"), sorted(ADMIN_MASTER_ROUTES))
def test_every_admin_master_route_requires_an_admin(
    client: TestClient, ids: dict[str, Any], method: str, path: str
) -> None:
    master = register(client, "master")
    customer = register(client, "client")
    url = re.sub(r"\{[a-z_]+\}", lambda _: str(uuid.uuid4()), path)
    before = _counts()
    for headers, expected in (
        ({}, 401),
        ({"Authorization": "Bearer not-a-token"}, 401),
        (auth(master["access_token"]), 403),
        (auth(customer["access_token"]), 403),
    ):
        resp = client.request(method, url, json={}, headers=headers)
        assert resp.status_code == expected, (method, path, headers)
    # A blocked admin is refused like an anonymous caller (status re-checked on every request).
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == ids["admin_id"]).values(status="blocked"))
        db.commit()
    assert client.request(method, url, json={}, headers=ids["admin"]).status_code == 401
    assert _counts() == before


# --- regressions from the final review ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "service_ids",
    [[], [PLAIN, PLAIN], [uuid.uuid4() for _ in range(master_admin.BULK_VERIFY_MAX + 1)]],
    ids=["empty", "duplicate", "over_limit"],
)
def test_bulk_selection_is_enforced_by_the_service_too(
    client: TestClient, ids: dict[str, Any], service_ids: list[uuid.UUID]
) -> None:
    """Regression: the limit, emptiness and uniqueness were enforced only by the API schema; a direct service
    call with a duplicate item decided the same row twice."""
    master = _ready_master(client, ids)
    before = _counts()
    with SessionLocal() as db:
        admin = db.get(User, ids["admin_id"])
        assert admin is not None
        for call in (
            lambda: master_admin.bulk_verify_preview(db, master["id"], service_ids),
            lambda: master_admin.bulk_verify(db, admin, master["id"], [(s, 1) for s in service_ids]),
        ):
            with pytest.raises(AppError) as exc:
                call()
            assert (exc.value.code, exc.value.status_code) == ("BULK_VERIFY_INVALID", 422)
    assert _counts() == before
    with SessionLocal() as db:
        assert db.scalar(select(MasterCompetency.version).where(MasterCompetency.service_id == PLAIN)) == 1


def test_file_is_closed_when_its_access_cannot_be_logged(
    client: TestClient, ids: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a failing access log left the opened stored file open; nothing is served unlogged."""
    master = _ready_master(client, ids)
    body = client.post(
        "/api/v1/master/qualifications",
        data={"qualification_id": str(ids["qualification_id"])},
        files=[("files", ("a.pdf", PDF, "application/pdf"))],
        headers=master["h"],
    ).json()
    storage = get_storage()
    opened: list[Any] = []
    real_open = storage.open

    def tracking_open(key: str) -> Any:
        handle = real_open(key)
        opened.append(handle)
        return handle

    def failing_log(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit log unavailable")

    monkeypatch.setattr(storage, "open", tracking_open)
    monkeypatch.setattr(svc, "log_file_access", failing_log)
    before = _counts()
    url = f"/api/v1/admin/masters/{master['id']}/qualifications/{body['id']}/files/{body['files'][0]['id']}"
    with pytest.raises(RuntimeError):
        client.get(url, headers=ids["admin"])
    assert len(opened) == 1 and opened[0].closed
    assert _counts() == before


# --- the whole lifecycle through the API --------------------------------------------------------------------


def _ready_master(client: TestClient, ids: dict[str, Any]) -> dict[str, Any]:
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
        db.add(MasterCompetency(master_id=master_id, service_id=PLAIN))
        db.commit()
    return {"id": master_id, "user_id": user_id, "h": auth(body["access_token"])}


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.scalar(select(func.count()).select_from(AuditLog)) or 0,
            db.scalar(select(func.count()).select_from(DomainEvent)) or 0,
        )


def _eligible(master_id: uuid.UUID, service_id: uuid.UUID) -> bool:
    with SessionLocal() as db:
        return master_id in eligibility.eligible_master_ids(db, service_id)


def test_full_lifecycle(client: TestClient, ids: dict[str, Any]) -> None:
    admin, base = ids["admin"], "/api/v1/admin"
    body = register(client, "master")
    master_h = auth(body["access_token"])
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))

    def version(detail: dict[str, Any], key: str, field: str, value: str) -> int:
        return int(next(item["version"] for item in detail[key] if item[field] == value))

    # The master applies while the profile is pending (Q-25).
    assert (
        client.post(
            "/api/v1/master/specialisations", json={"specialisation_id": str(SPEC)}, headers=master_h
        ).status_code
        == 201
    )
    for service_id in (REGULATED, PLAIN):
        assert (
            client.post(
                "/api/v1/master/competencies", json={"service_id": str(service_id)}, headers=master_h
            ).status_code
            == 201
        )
    submission = client.post(
        "/api/v1/master/qualifications",
        data={"qualification_id": str(ids["qualification_id"])},
        files=[("files", ("a.pdf", PDF, "application/pdf"))],
        headers=master_h,
    ).json()
    queue = client.get(f"{base}/review-queue", headers=admin).json()["items"]
    assert sorted(i["kind"] for i in queue) == ["competency", "competency", "qualification", "specialisation"]
    listed = client.get(f"{base}/masters", params={"has_pending": True}, headers=admin).json()["items"]
    assert [m["id"] for m in listed] == [str(master_id)]

    # Nothing is verifiable before the profile and specialisation are approved.
    resp = client.post(
        f"{base}/masters/{master_id}/competencies/{PLAIN}/verify", json={"expected_version": 1}, headers=admin
    )
    assert resp.status_code == 409
    assert [r["code"] for r in resp.json()["error"]["details"]["reasons"]] == [
        "PROFILE_NOT_APPROVED",
        "SPECIALISATION_NOT_APPROVED",
    ]
    detail = client.post(
        f"{base}/masters/{master_id}/approve", json={"expected_version": 1}, headers=admin
    ).json()
    detail = client.post(
        f"{base}/masters/{master_id}/specialisations/{SPEC}/approve",
        json={"expected_version": version(detail, "specialisations", "specialisation_id", str(SPEC))},
        headers=admin,
    ).json()

    # Bulk: the regulated competency is refused as a whole set; alone, the plain one passes.
    preview = client.post(
        f"{base}/masters/{master_id}/competencies/bulk-verify/preview",
        json={"service_ids": [str(PLAIN), str(REGULATED)]},
        headers=admin,
    ).json()
    assert preview["applicable"] is False
    items = [
        {"service_id": i["service_id"], "expected_version": i["expected_version"]} for i in preview["items"]
    ]
    refused = client.post(
        f"{base}/masters/{master_id}/competencies/bulk-verify",
        json={"items": items, "confirm": True},
        headers=admin,
    )
    assert refused.status_code == 409 and not _eligible(master_id, PLAIN)
    detail = client.post(
        f"{base}/masters/{master_id}/competencies/bulk-verify",
        json={"items": [items[0]], "confirm": True},
        headers=admin,
    ).json()
    assert _eligible(master_id, PLAIN)

    # The regulated competency needs the verified qualification first (shared eligibility rule).
    resp = client.post(
        f"{base}/masters/{master_id}/competencies/{REGULATED}/verify",
        json={"expected_version": 1},
        headers=admin,
    )
    assert resp.json()["error"]["code"] == "QUALIFICATION_MISSING"
    file_url = (
        f"{base}/masters/{master_id}/qualifications/{submission['id']}/files/{submission['files'][0]['id']}"
    )
    assert client.get(file_url, params={"mode": "view"}, headers=admin).status_code == 200
    client.post(
        f"{base}/masters/{master_id}/qualifications/{submission['id']}/verify",
        json={"expected_version": 1},
        headers=admin,
    )
    detail = client.post(
        f"{base}/masters/{master_id}/competencies/{REGULATED}/verify",
        json={"expected_version": 1},
        headers=admin,
    ).json()
    assert _eligible(master_id, REGULATED)
    assert client.get(f"{base}/review-queue", headers=admin).json()["items"] == []

    # Revoking the qualification excludes at once; the competency row stays verified; renewal restores.
    client.post(
        f"{base}/masters/{master_id}/qualifications/{submission['id']}/revoke",
        json={"expected_version": 2, "reason": "Viltots"},
        headers=admin,
    )
    assert not _eligible(master_id, REGULATED) and _eligible(master_id, PLAIN)
    with SessionLocal() as db:
        assert (
            db.scalar(select(MasterCompetency.status).where(MasterCompetency.service_id == REGULATED))
            == "verified"
        )
    renewal = client.post(
        "/api/v1/master/qualifications",
        data={"qualification_id": str(ids["qualification_id"])},
        files=[("files", ("b.pdf", PDF, "application/pdf"))],
        headers=master_h,
    ).json()
    client.post(
        f"{base}/masters/{master_id}/qualifications/{renewal['id']}/verify",
        json={"expected_version": 1},
        headers=admin,
    )
    assert _eligible(master_id, REGULATED)

    # Revoking the specialisation excludes from both services; no competency row changes.
    detail = client.get(f"{base}/masters/{master_id}", headers=admin).json()
    client.post(
        f"{base}/masters/{master_id}/specialisations/{SPEC}/revoke",
        json={
            "expected_version": version(detail, "specialisations", "specialisation_id", str(SPEC)),
            "reason": "Sūdzības",
        },
        headers=admin,
    )
    assert not _eligible(master_id, REGULATED) and not _eligible(master_id, PLAIN)
    final = client.get(f"{base}/masters/{master_id}", headers=admin).json()
    assert {c["status"] for c in final["competencies"]} == {"verified"}
    assert {(q["status"], q["expired"]) for q in final["qualifications"]} == {
        ("revoked", False),
        ("verified", False),
    }

    # Every recorded change has exactly one audit entry and one event, and vice versa.
    with SessionLocal() as db:
        audit = Counter(
            (a.action, a.entity_id)
            for a in db.scalars(select(AuditLog).where(AuditLog.action.like("master.%")))
        )
        events = Counter(
            (e.event_type, e.aggregate_id)
            for e in db.scalars(select(DomainEvent).where(DomainEvent.event_type.like("master.%")))
        )
        reads = db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "attachment.viewed")
        )
    assert audit == events
    assert sum(audit.values()) == 13  # 5 master actions (incl. the renewal) + 8 admin decisions
    assert reads == 1
