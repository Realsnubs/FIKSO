"""Catalogue concurrency (step 4.5.3.1): row locks (FOR UPDATE / FOR SHARE, PostgreSQL) and expected_version
on every catalogue mutation. Lock order: category → specialisation → service → qualification types."""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models import (
    AuditLog,
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    DomainEvent,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications, specialisation_qualifications
from app.schemas.catalogue import ServiceUpdate
from app.services import catalogue as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth

CATEGORY = seed_id("cm-c1")
SPEC = seed_id("cm-s01")
OTHER_SPEC = seed_id("cm-s02")
SERVICE = seed_id("cm-s01-1")
SIBLING = seed_id("cm-s01-2")
BASE = "/api/v1/admin/catalogue"


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        qualification = Qualification(name="Elektrodrošība", status="active")
        db.add(qualification)
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([SERVICE, SIBLING]))
            .values(status="inactive")
        )
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, qualification.id)


def _version(model: Any, entity_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(model.version).where(model.id == entity_id)))


def _row(model: Any, entity_id: uuid.UUID) -> dict[str, Any]:
    with SessionLocal() as db:
        entity = db.get(model, entity_id)
        return {c.key: getattr(entity, c.key) for c in model.__table__.columns}


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            int(db.scalar(select(func.count()).select_from(AuditLog))),
            int(db.scalar(select(func.count()).select_from(DomainEvent))),
        )


def _as_admin(fx: Fx, call: Callable[..., Any], *args: Any) -> str:
    """Run one catalogue operation in its own session; returns "ok" or the error code."""
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        try:
            call(db, admin, *args)
            return "ok"
        except AppError as exc:
            return exc.code


def _parallel(jobs: list[Callable[[], str]]) -> list[str]:
    barrier = threading.Barrier(len(jobs))
    results: list[str] = [""] * len(jobs)

    def run(index: int) -> None:
        barrier.wait()
        try:
            results[index] = jobs[index]()
        except DBAPIError as exc:  # a deadlock or lock timeout would land here
            results[index] = f"db:{type(exc.orig).__name__}"

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def _waits_then(holder_work: Callable[[Any], None], attempt: Callable[[], str]) -> str:
    """`holder_work` runs in an open transaction; `attempt` must block on its lock, then see its result."""
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder_work(holder)
        thread = threading.Thread(target=lambda: outcome.append(attempt()))
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the operation must wait for the row lock"
        holder.commit()
    thread.join(timeout=30)
    return outcome[0]


# --- expected_version through the API -----------------------------------------------------------------------


MUTATIONS: dict[str, tuple[str, str, dict[str, Any], Any, uuid.UUID]] = {
    "category_patch": ("patch", f"/categories/{CATEGORY}", {"description": "x"}, CatalogueCategory, CATEGORY),
    "category_status": (
        "post",
        f"/categories/{CATEGORY}/status",
        {"status": "inactive"},
        CatalogueCategory,
        CATEGORY,
    ),
    "specialisation_patch": (
        "patch",
        f"/specialisations/{SPEC}",
        {"description": "x"},
        CatalogueSpecialisation,
        SPEC,
    ),
    "specialisation_status": (
        "post",
        f"/specialisations/{SPEC}/status",
        {"status": "planned"},
        CatalogueSpecialisation,
        SPEC,
    ),
    "specialisation_requirements": (
        "put",
        f"/specialisations/{SPEC}/qualifications",
        {"qualification_ids": []},
        CatalogueSpecialisation,
        SPEC,
    ),
    "service_patch": ("patch", f"/services/{SERVICE}", {"review_note": "x"}, CatalogueService, SERVICE),
    "service_status": (
        "post",
        f"/services/{SERVICE}/status",
        {"status": "planned"},
        CatalogueService,
        SERVICE,
    ),
    "service_requirements": (
        "put",
        f"/services/{SERVICE}/qualifications",
        {"qualification_ids": []},
        CatalogueService,
        SERVICE,
    ),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_stale_or_missing_version_changes_nothing(client: TestClient, fx: Fx, name: str) -> None:
    method, path, body, model, entity_id = MUTATIONS[name]
    current = _version(model, entity_id)
    before, counts = _row(model, entity_id), _counts()
    send = getattr(client, method)
    assert send(f"{BASE}{path}", json=body, headers=fx.admin).status_code == 422  # required, no way around it
    for stale in (current - 1 or 99, current + 1):
        resp = send(f"{BASE}{path}", json=body | {"expected_version": stale}, headers=fx.admin)
        assert resp.status_code == 409, resp.text
        error = resp.json()["error"]
        assert error["code"] == "VERSION_CONFLICT" and error["details"]["version"] == current
        assert error["details"]["status"] == before["status"]
    assert (_row(model, entity_id), _counts()) == (before, counts)  # no data, audit entry or event
    ok = send(f"{BASE}{path}", json=body | {"expected_version": current}, headers=fx.admin)
    assert ok.status_code == 200, ok.text
    assert _version(model, entity_id) == current + 1 == ok.json()["version"]


def test_hold_activation_and_qualification_status_need_the_current_version(
    client: TestClient, fx: Fx
) -> None:
    status_url = f"{BASE}/services/{SERVICE}/status"
    client.post(
        status_url, json={"status": "hold", "reason": "Risks", "expected_version": 1}, headers=fx.admin
    )
    hold = f"{BASE}/services/{SERVICE}/activate-hold"
    stale = client.post(
        hold, json={"confirm": True, "reason": "Pārbaudīts", "expected_version": 1}, headers=fx.admin
    )
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert _row(CatalogueService, SERVICE)["status"] == "hold"  # HOLD never activated by a stale request
    ok = client.post(
        hold, json={"confirm": True, "reason": "Pārbaudīts", "expected_version": 2}, headers=fx.admin
    )
    assert ok.json()["status"] == "active"
    url = f"{BASE}/qualifications/{fx.qualification_id}/status"
    assert (
        client.post(url, json={"status": "archived", "reason": "Vecs"}, headers=fx.admin).status_code == 422
    )
    stale = client.post(
        url, json={"status": "archived", "reason": "Vecs", "expected_version": 2}, headers=fx.admin
    )
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert (
        client.post(
            url, json={"status": "archived", "reason": "Vecs", "expected_version": 1}, headers=fx.admin
        ).json()["status"]
        == "archived"
    )


def test_sequential_changes_count_versions_from_the_current_value(client: TestClient, fx: Fx) -> None:
    url = f"{BASE}/services/{SERVICE}/status"
    for version, status in enumerate(("planned", "inactive", "planned", "active"), start=1):
        resp = client.post(url, json={"status": status, "expected_version": version}, headers=fx.admin)
        assert (resp.status_code, resp.json()["version"]) == (200, version + 1)
    with SessionLocal() as db:
        trail = db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_id == SERVICE, AuditLog.actor_type == "user")
            .order_by(AuditLog.created_at, AuditLog.id)
        ).all()
    assert [e.after["status"] for e in trail if e.after] == ["planned", "inactive", "planned", "active"]
    for previous, current in zip(trail, trail[1:], strict=False):
        assert previous.after == current.before  # no lost update: each change starts where the last ended


def test_change_after_a_stale_view_is_refused(client: TestClient, fx: Fx) -> None:
    """The admin loaded the tree, someone else changed the service, the admin's change is refused."""
    tree = client.get(f"{BASE}/tree", headers=fx.admin).json()
    seen = next(
        s["version"]
        for c in tree["categories"]
        for sp in c["specialisations"]
        for s in sp["services"]
        if s["id"] == str(SERVICE)
    )
    assert _as_admin(fx, svc.set_service_status, SERVICE, "planned", None, seen) == "ok"
    before, counts = _row(CatalogueService, SERVICE), _counts()
    resp = client.post(
        f"{BASE}/services/{SERVICE}/status",
        json={"status": "active", "expected_version": seen},
        headers=fx.admin,
    )
    assert resp.json()["error"] == {
        "code": "VERSION_CONFLICT",
        "message": "The entry changed since it was loaded.",
        "details": {"version": seen + 1, "status": "planned"},
    }
    assert (_row(CatalogueService, SERVICE), _counts()) == (before, counts)


# --- parallel changes (PostgreSQL) --------------------------------------------------------------------------


def test_parallel_changes_of_one_service(fx: Fx) -> None:
    jobs = [
        (lambda s=status: _as_admin(fx, svc.set_service_status, SERVICE, s, None, 1))
        for status in ("planned", "active", "planned", "active", "planned", "active")
    ]
    results = _parallel(jobs)
    assert results.count("ok") == 1 and results.count("VERSION_CONFLICT") == 5, results
    assert _version(CatalogueService, SERVICE) == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == SERVICE)) == 1


def test_parallel_changes_of_one_specialisation(fx: Fx) -> None:
    version = _version(CatalogueSpecialisation, SPEC)
    jobs = [
        (lambda s=status: _as_admin(fx, svc.set_specialisation_status, SPEC, s, None, version))
        for status in ("planned", "inactive", "planned", "inactive")
    ]
    results = _parallel(jobs)
    assert results.count("ok") == 1 and results.count("VERSION_CONFLICT") == 3, results
    assert _version(CatalogueSpecialisation, SPEC) == version + 1


def test_parent_category_and_child_service_change_together(fx: Fx) -> None:
    """Different rows: both changes apply, each exactly once, in either order; no deadlock."""
    category_version = _version(CatalogueCategory, CATEGORY)
    results = _parallel(
        [
            lambda: _as_admin(fx, svc.set_category_status, CATEGORY, "inactive", None, category_version),
            lambda: _as_admin(fx, svc.set_service_status, SERVICE, "active", None, 1),
            lambda: _as_admin(
                fx,
                svc.set_specialisation_status,
                SPEC,
                "planned",
                None,
                _version(CatalogueSpecialisation, SPEC),
            ),
        ]
    )
    assert results == ["ok", "ok", "ok"], results
    assert _version(CatalogueCategory, CATEGORY) == category_version + 1
    assert _row(CatalogueService, SERVICE)["status"] == "active"


def test_mixed_parallel_operations_never_deadlock(fx: Fx) -> None:
    """Every operation kind on overlapping entities at once: only domain outcomes, no deadlock or timeout."""
    versions = {
        "cat": _version(CatalogueCategory, CATEGORY),
        "spec": _version(CatalogueSpecialisation, SPEC),
        "other": _version(CatalogueSpecialisation, OTHER_SPEC),
    }
    q = fx.qualification_id
    jobs: list[Callable[[], str]] = [
        lambda: _as_admin(fx, svc.set_category_status, CATEGORY, "inactive", None, versions["cat"]),
        lambda: _as_admin(fx, svc.set_specialisation_status, SPEC, "planned", None, versions["spec"]),
        lambda: _as_admin(fx, svc.set_specialisation_requirements, SPEC, [q], versions["spec"]),
        lambda: _as_admin(fx, svc.set_specialisation_status, OTHER_SPEC, "inactive", None, versions["other"]),
        lambda: _as_admin(fx, svc.set_service_status, SERVICE, "active", None, 1),
        lambda: _as_admin(fx, svc.set_service_requirements, SERVICE, [q], 1),
        lambda: _as_admin(
            fx, svc.update_service, SERVICE, ServiceUpdate(expected_version=1, specialisation_id=OTHER_SPEC)
        ),
        lambda: _as_admin(
            fx, svc.update_service, SIBLING, ServiceUpdate(expected_version=1, specialisation_id=OTHER_SPEC)
        ),
        lambda: _as_admin(fx, svc.set_service_requirements, SIBLING, [q], 1),
        lambda: _as_admin(fx, svc.set_qualification_status, q, "archived", "Vecs", 1),
    ]
    for _ in range(5):
        with SessionLocal() as db:  # reset to the same starting point each round
            db.execute(
                update(CatalogueCategory).where(CatalogueCategory.id == CATEGORY).values(status="active")
            )
            db.execute(update(Qualification).where(Qualification.id == q).values(status="active", version=1))
            db.execute(service_qualifications.delete())
            db.execute(specialisation_qualifications.delete())
            db.execute(
                update(CatalogueService)
                .where(CatalogueService.id.in_([SERVICE, SIBLING]))
                .values(status="inactive", version=1, specialisation_id=SPEC)
            )
            db.execute(
                update(CatalogueSpecialisation)
                .where(CatalogueSpecialisation.id.in_([SPEC, OTHER_SPEC]))
                .values(status="active")
            )
            db.commit()
        versions |= {
            "cat": _version(CatalogueCategory, CATEGORY),
            "spec": _version(CatalogueSpecialisation, SPEC),
            "other": _version(CatalogueSpecialisation, OTHER_SPEC),
        }
        results = _parallel(jobs)
        assert not [r for r in results if r.startswith("db:") or r == ""], results
        assert set(results) <= {"ok", "VERSION_CONFLICT", "QUALIFICATION_IN_USE", "QUALIFICATION_ARCHIVED"}, (
            results
        )
        # Invariant: an archived type is never left in a requirement.
        with SessionLocal() as db:
            archived_required = db.scalar(
                select(func.count())
                .select_from(service_qualifications)
                .join(Qualification, Qualification.id == service_qualifications.c.qualification_id)
                .where(Qualification.status == "archived")
            )
        assert archived_required == 0


# --- each lock, proven by blocking (fails without it) -------------------------------------------------------


def test_changed_row_is_locked_for_update(fx: Fx) -> None:
    """Without FOR UPDATE the second change reads the old version, passes and overwrites the first."""

    def other_admin(db: Any) -> None:
        svc.prepare_service_status(db, db.get(User, fx.admin_id), SERVICE, "planned", None, 1)

    result = _waits_then(
        other_admin, lambda: _as_admin(fx, svc.set_service_status, SERVICE, "active", None, 1)
    )
    assert result == "VERSION_CONFLICT"
    assert (_row(CatalogueService, SERVICE)["status"], _version(CatalogueService, SERVICE)) == ("planned", 2)


def test_move_target_is_locked_for_share(fx: Fx) -> None:
    """Without FOR SHARE on the target, a service moves into a specialisation being archived right then."""

    def archive_target(db: Any) -> None:
        svc.prepare_specialisation_status(
            db,
            db.get(User, fx.admin_id),
            OTHER_SPEC,
            "archived",
            "Slēgts",
            _version(CatalogueSpecialisation, OTHER_SPEC),
        )

    move = ServiceUpdate(expected_version=1, specialisation_id=OTHER_SPEC)
    assert (
        _waits_then(archive_target, lambda: _as_admin(fx, svc.update_service, SERVICE, move))
        == "PARENT_ARCHIVED"
    )
    assert _row(CatalogueService, SERVICE)["specialisation_id"] == SPEC


def test_parent_requirements_are_locked_for_share(fx: Fx) -> None:
    """Without FOR SHARE on the parent, a regulated service activates as its last requirement is removed."""
    with SessionLocal() as db:
        db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == SPEC)
            .values(qualification_required=True)
        )
        db.execute(
            specialisation_qualifications.insert().values(
                specialisation_id=SPEC, qualification_id=fx.qualification_id
            )
        )
        db.commit()

    def remove_requirement(db: Any) -> None:
        svc.prepare_specialisation_requirements(
            db, db.get(User, fx.admin_id), SPEC, [], _version(CatalogueSpecialisation, SPEC)
        )

    activate = lambda: _as_admin(fx, svc.set_service_status, SERVICE, "active", None, 1)  # noqa: E731
    assert _waits_then(remove_requirement, activate) == "QUALIFICATION_NOT_CONFIGURED"
    assert _row(CatalogueService, SERVICE)["status"] == "inactive"


def test_required_type_is_locked_for_share(fx: Fx) -> None:
    """Without FOR SHARE on the type, it is required by a service while it is being archived."""

    def archive_type(db: Any) -> None:
        db.execute(
            text("SELECT 1 FROM qualifications WHERE id = :id FOR UPDATE"), {"id": fx.qualification_id}
        )
        db.execute(
            update(Qualification)
            .where(Qualification.id == fx.qualification_id)
            .values(status="archived", version=2)
        )

    add = lambda: _as_admin(fx, svc.set_service_requirements, SERVICE, [fx.qualification_id], 1)  # noqa: E731
    assert _waits_then(archive_type, add) == "QUALIFICATION_ARCHIVED"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(service_qualifications)) == 0


def test_type_status_is_locked_for_update(fx: Fx) -> None:
    """Without FOR UPDATE on the type, archiving reads 'not required' while a requirement is being added."""

    def add_requirement(db: Any) -> None:
        svc.prepare_service_requirements(db, db.get(User, fx.admin_id), SERVICE, [fx.qualification_id], 1)

    archive = lambda: _as_admin(fx, svc.set_qualification_status, fx.qualification_id, "archived", "Vecs", 1)  # noqa: E731
    assert _waits_then(add_requirement, archive) == "QUALIFICATION_IN_USE"
    assert _row(Qualification, fx.qualification_id)["status"] == "active"
