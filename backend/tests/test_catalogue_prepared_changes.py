"""Catalogue mutations split into prepare + record (step 4.5.3): the public operations behave as before,
and `prepare_*` inside `dry_run` writes nothing, logs nothing and leaves no lock behind."""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

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
from app.schemas.catalogue import ServiceUpdate, SpecialisationUpdate
from app.services import catalogue as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, versioned

CATEGORY = seed_id("cm-c1")
OTHER_CATEGORY = seed_id("cm-c2")
SPEC = seed_id("cm-s01")
OTHER_SPEC = seed_id("cm-s02")
SERVICE = seed_id("cm-s01-1")
BASE = "/api/v1/admin/catalogue"


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID
    draft_qualification_id: uuid.UUID
    archived_qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        active = Qualification(name="Elektrodrošība", status="active")
        draft = Qualification(name="Gāze", status="draft")
        archived = Qualification(name="Vecs", status="archived")
        db.add_all([active, draft, archived])
        db.execute(update(CatalogueService).where(CatalogueService.id == SERVICE).values(status="inactive"))
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, active.id, draft.id, archived.id)


def _state() -> tuple[Any, ...]:
    """Every catalogue row and requirement link (all columns), plus all audit entries and events."""
    with SessionLocal() as db:
        rows = [
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (CatalogueCategory, CatalogueSpecialisation, CatalogueService, Qualification)
            for row in db.scalars(select(model))
        ]
        links = [
            tuple(r)
            for table in (service_qualifications, specialisation_qualifications)
            for r in db.execute(select(table))
        ]
        audit = [(a.action, a.entity_id, a.before, a.after, a.reason) for a in db.scalars(select(AuditLog))]
        events = [(e.event_type, e.aggregate_id, e.payload) for e in db.scalars(select(DomainEvent))]
    return sorted(rows, key=repr), sorted(links, key=repr), sorted(audit, key=repr), sorted(events, key=repr)


def _content(model: Any, entity_id: uuid.UUID) -> dict[str, Any]:
    with SessionLocal() as db:
        return svc.content(db.get(model, entity_id))


def _version(model: Any, entity_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(model.version).where(model.id == entity_id)))


def _requirements(model: Any, entity_id: uuid.UUID) -> list[str]:
    with SessionLocal() as db:
        return sorted(str(q.id) for q in db.get(model, entity_id).qualifications)


def _catalogue_log() -> list[AuditLog]:
    """Entries written by an admin (the seed writes its own system entry)."""
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action.like("catalogue.%"), AuditLog.actor_type == "user")
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _catalogue_events() -> list[DomainEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type.like("catalogue.%"), DomainEvent.actor_type == "user")
                .order_by(DomainEvent.created_at, DomainEvent.id)
            )
        )


# --- the public operations behave as before -----------------------------------------------------------------


SUCCESSES: dict[str, tuple[str, str, dict[str, Any], Any, uuid.UUID, str]] = {
    # name: (method, path, body, model, entity, audited action)
    "category_status": (
        "post",
        f"/categories/{CATEGORY}/status",
        {"status": "inactive"},
        CatalogueCategory,
        CATEGORY,
        "catalogue.category.status_changed",
    ),
    "specialisation_status": (
        "post",
        f"/specialisations/{SPEC}/status",
        {"status": "planned"},
        CatalogueSpecialisation,
        SPEC,
        "catalogue.specialisation.status_changed",
    ),
    "specialisation_move": (
        "patch",
        f"/specialisations/{SPEC}",
        {"category_id": str(OTHER_CATEGORY)},
        CatalogueSpecialisation,
        SPEC,
        "catalogue.specialisation.updated",
    ),
    "specialisation_flag": (
        "patch",
        f"/specialisations/{SPEC}",
        {"qualification_required": True},
        CatalogueSpecialisation,
        SPEC,
        "catalogue.specialisation.updated",
    ),
    "service_status": (
        "post",
        f"/services/{SERVICE}/status",
        {"status": "hold", "reason": "Risks"},
        CatalogueService,
        SERVICE,
        "catalogue.service.status_changed",
    ),
    "service_move": (
        "patch",
        f"/services/{SERVICE}",
        {"specialisation_id": str(OTHER_SPEC)},
        CatalogueService,
        SERVICE,
        "catalogue.service.updated",
    ),
    "service_flag": (
        "patch",
        f"/services/{SERVICE}",
        {"qualification_required": True},
        CatalogueService,
        SERVICE,
        "catalogue.service.updated",
    ),
}


@pytest.mark.parametrize("name", SUCCESSES)
def test_changes_are_applied_audited_and_announced_once(client: TestClient, fx: Fx, name: str) -> None:
    method, path, body, model, entity_id, action = SUCCESSES[name]
    before, version = _content(model, entity_id), _version(model, entity_id)
    url = f"{BASE}{path}"
    resp = getattr(client, method)(url, json=versioned(url, body), headers=fx.admin)
    assert resp.status_code == 200, resp.text
    after = _content(model, entity_id)
    assert _version(model, entity_id) == version + 1 == resp.json()["version"]
    [entry] = _catalogue_log()
    assert (entry.action, entry.entity_id, entry.actor_id) == (action, entity_id, fx.admin_id)
    assert (entry.before, entry.after) == (before, after)
    assert entry.reason == body.get("reason")
    [event] = _catalogue_events()
    assert (event.event_type, event.aggregate_id) == (action, entity_id)
    assert event.payload["status"] == after["status"]


@pytest.mark.parametrize(
    ("model", "entity_id", "path"),
    [(CatalogueService, SERVICE, "services"), (CatalogueSpecialisation, SPEC, "specialisations")],
)
def test_requirement_changes_are_audited_once(
    client: TestClient, fx: Fx, model: Any, entity_id: Any, path: str
) -> None:
    url = f"{BASE}/{path}/{entity_id}/qualifications"
    resp = client.put(
        url, json=versioned(url, {"qualification_ids": [str(fx.qualification_id)]}), headers=fx.admin
    )
    assert resp.status_code == 200, resp.text
    kind = "service" if model is CatalogueService else "specialisation"
    [entry] = _catalogue_log()
    assert entry.action == f"catalogue.{kind}.requirements_changed"
    assert (entry.before, entry.after) == (
        {"qualification_ids": []},
        {"qualification_ids": [str(fx.qualification_id)]},
    )
    [event] = _catalogue_events()
    assert (event.event_type, event.payload) == (entry.action, entry.after)


def test_hold_activation_is_unchanged(client: TestClient, fx: Fx) -> None:
    status_url, hold_url = f"{BASE}/services/{SERVICE}/status", f"{BASE}/services/{SERVICE}/activate-hold"
    client.post(
        status_url, json=versioned(status_url, {"status": "hold", "reason": "Risks"}), headers=fx.admin
    )
    refused = client.post(status_url, json=versioned(status_url, {"status": "active"}), headers=fx.admin)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "HOLD_ACTIVATION_REQUIRED")
    resp = client.post(
        hold_url, json=versioned(hold_url, {"confirm": True, "reason": "Pārbaudīts"}), headers=fx.admin
    )
    assert resp.status_code == 200 and resp.json()["status"] == "active"
    assert [e.action for e in _catalogue_log()] == [
        "catalogue.service.status_changed",
        "catalogue.service.hold_activated",
    ]
    with SessionLocal() as db:
        service = db.get(CatalogueService, SERVICE)
        assert (
            service is not None and service.activated_by == fx.admin_id and service.activated_at is not None
        )


def _break(fx: Fx, case: str) -> None:
    with SessionLocal() as db:
        if case == "archived_parent":
            db.execute(
                update(CatalogueSpecialisation)
                .where(CatalogueSpecialisation.id == OTHER_SPEC)
                .values(status="archived")
            )
        if case == "archived_category":
            db.execute(
                update(CatalogueCategory)
                .where(CatalogueCategory.id == OTHER_CATEGORY)
                .values(status="archived")
            )
        if case in ("regulated_active", "requirement_removed"):
            db.execute(update(CatalogueService).where(CatalogueService.id == SERVICE).values(status="active"))
        if case == "requirement_removed":
            db.execute(
                update(CatalogueService)
                .where(CatalogueService.id == SERVICE)
                .values(qualification_required=True)
            )
            db.execute(
                service_qualifications.insert().values(
                    service_id=SERVICE, qualification_id=fx.qualification_id
                )
            )
        db.commit()


ERRORS: dict[str, tuple[str, str, Callable[[Fx], dict[str, Any]], int, str]] = {
    "invalid_transition": (
        "post",
        f"/services/{SERVICE}/status",
        lambda fx: {"status": "rejected", "reason": "Iemesls"},
        409,
        "INVALID_STATUS_TRANSITION",
    ),
    "reason_required": (
        "post",
        f"/services/{SERVICE}/status",
        lambda fx: {"status": "archived"},
        422,
        "REASON_REQUIRED",
    ),
    "group_reason_required": (
        "post",
        f"/specialisations/{SPEC}/status",
        lambda fx: {"status": "archived"},
        422,
        "REASON_REQUIRED",
    ),
    "category_transition": (
        "post",
        f"/categories/{CATEGORY}/status",
        lambda fx: {"status": "rejected"},
        409,
        "INVALID_STATUS_TRANSITION",
    ),
    "not_on_hold": (
        "post",
        f"/services/{SERVICE}/activate-hold",
        lambda fx: {"confirm": True, "reason": "Iemesls"},
        409,
        "NOT_ON_HOLD",
    ),
    "archived_parent": (
        "patch",
        f"/services/{SERVICE}",
        lambda fx: {"specialisation_id": str(OTHER_SPEC)},
        409,
        "PARENT_ARCHIVED",
    ),
    "archived_category": (
        "patch",
        f"/specialisations/{SPEC}",
        lambda fx: {"category_id": str(OTHER_CATEGORY)},
        409,
        "PARENT_ARCHIVED",
    ),
    "regulated_active": (
        "patch",
        f"/services/{SERVICE}",
        lambda fx: {"qualification_required": True},
        409,
        "QUALIFICATION_NOT_CONFIGURED",
    ),
    "requirement_removed": (
        "put",
        f"/services/{SERVICE}/qualifications",
        lambda fx: {"qualification_ids": []},
        409,
        "QUALIFICATION_NOT_CONFIGURED",
    ),
    "draft_requirement": (
        "put",
        f"/services/{SERVICE}/qualifications",
        lambda fx: {"qualification_ids": [str(fx.draft_qualification_id)]},
        200,
        "",
    ),
    "archived_requirement": (
        "put",
        f"/services/{SERVICE}/qualifications",
        lambda fx: {"qualification_ids": [str(fx.archived_qualification_id)]},
        409,
        "QUALIFICATION_ARCHIVED",
    ),
    "unknown_requirement": (
        "put",
        f"/specialisations/{SPEC}/qualifications",
        lambda fx: {"qualification_ids": [str(uuid.uuid4())]},
        404,
        "QUALIFICATION_NOT_FOUND",
    ),
    "unknown_service": (
        "post",
        f"/services/{uuid.uuid4()}/status",
        lambda fx: {"status": "inactive"},
        404,
        "SERVICE_NOT_FOUND",
    ),
    "name_taken": ("patch", f"/services/{SERVICE}", lambda fx: {"name": "__other_name__"}, 409, "NAME_TAKEN"),
}


@pytest.mark.parametrize("case", ERRORS)
def test_refused_changes_leave_everything_unchanged(client: TestClient, fx: Fx, case: str) -> None:
    method, path, body, code, error = ERRORS[case]
    _break(fx, case)
    if case == "name_taken":
        with SessionLocal() as db:
            other = db.scalar(select(CatalogueService.name).where(CatalogueService.id == seed_id("cm-s01-2")))
        payload: dict[str, Any] = {"name": other}
    else:
        payload = body(fx)
    before = _state()
    url = f"{BASE}{path}"
    resp = getattr(client, method)(url, json=versioned(url, payload), headers=fx.admin)
    assert resp.status_code == code, resp.text
    if code == 200:  # a draft (not archived) qualification may be required on a non-active service, as before
        return
    assert resp.json()["error"]["code"] == error
    assert _state() == before


# --- prepare_* and dry_run ----------------------------------------------------------------------------------


def _prepares(fx: Fx) -> dict[str, Callable[[Session, User], Any]]:
    cat, spec, service = (
        _version(CatalogueCategory, CATEGORY),
        _version(CatalogueSpecialisation, SPEC),
        _version(CatalogueService, SERVICE),
    )
    return {
        "category_status": lambda db, a: svc.prepare_category_status(db, a, CATEGORY, "inactive", None, cat),
        "specialisation_status": lambda db, a: svc.prepare_specialisation_status(
            db, a, SPEC, "planned", None, spec
        ),
        "specialisation_update": lambda db, a: svc.prepare_specialisation_update(
            db,
            a,
            SPEC,
            SpecialisationUpdate(
                expected_version=spec, category_id=OTHER_CATEGORY, qualification_required=True
            ),
        ),
        "specialisation_requirements": lambda db, a: svc.prepare_specialisation_requirements(
            db, a, SPEC, [fx.qualification_id], spec
        ),
        "service_status": lambda db, a: svc.prepare_service_status(db, a, SERVICE, "active", None, service),
        "service_update": lambda db, a: svc.prepare_service_update(
            db, a, SERVICE, ServiceUpdate(expected_version=service, specialisation_id=OTHER_SPEC)
        ),
        "service_requirements": lambda db, a: svc.prepare_service_requirements(
            db, a, SERVICE, [fx.qualification_id], service
        ),
    }


@pytest.mark.parametrize(
    "name",
    [
        "category_status",
        "specialisation_status",
        "specialisation_update",
        "specialisation_requirements",
        "service_status",
        "service_update",
        "service_requirements",
    ],
)
def test_prepare_in_dry_run_writes_and_logs_nothing(
    client: TestClient, fx: Fx, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a prepared change must not log or commit")

    monkeypatch.setattr(svc, "record_audit", forbidden)
    monkeypatch.setattr(svc, "record_event", forbidden)
    before = _state()
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        db.commit()  # end the read transaction; dry_run starts clean
        monkeypatch.setattr(db, "commit", forbidden)
        with svc.dry_run(db):
            change = _prepares(fx)[name](db, admin)
            # The change is visible inside the transaction (flushed, constraints checked) ...
            seen = db.execute(
                text("SELECT version FROM catalogue_categories WHERE id = :id"), {"id": CATEGORY}
            )
            assert change.entity.version >= 2 and seen.scalar() is not None
    assert _state() == before  # ... and gone afterwards


def test_dry_run_rolls_back_a_refused_change(client: TestClient, fx: Fx) -> None:
    _break(fx, "requirement_removed")
    before = _state()
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        db.commit()
        with pytest.raises(AppError) as exc, svc.dry_run(db):
            svc.prepare_service_requirements(db, admin, SERVICE, [], _version(CatalogueService, SERVICE))
        assert exc.value.code == "QUALIFICATION_NOT_CONFIGURED"
    assert _state() == before


def test_dry_run_needs_a_clean_session(client: TestClient, fx: Fx) -> None:
    with SessionLocal() as db:
        service = db.get(CatalogueService, SERVICE)
        assert service is not None
        service.review_note = "pending"
        with pytest.raises(RuntimeError), svc.dry_run(db):
            pass


def _update_with_timeout(results: list[str]) -> None:
    with SessionLocal() as other:
        other.execute(text("SET LOCAL lock_timeout = '300ms'"))
        try:
            other.execute(
                update(CatalogueService).where(CatalogueService.id == SERVICE).values(review_note="other")
            )
            other.rollback()
            results.append("updated")
        except OperationalError:
            results.append("blocked")


def test_dry_run_holds_its_row_locks_only_until_it_ends(client: TestClient, fx: Fx) -> None:
    """A full rollback, not a savepoint: every row lock taken by the flushed change is released at the end."""
    results: list[str] = []
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        db.commit()
        with svc.dry_run(db):
            svc.prepare_service_status(
                db, admin, SERVICE, "planned", None, _version(CatalogueService, SERVICE)
            )
            inside = threading.Thread(target=_update_with_timeout, args=(results,))
            inside.start()
            inside.join()
        after = threading.Thread(target=_update_with_timeout, args=(results,))
        after.start()
        after.join()
    assert results == ["blocked", "updated"]


def test_a_real_change_waits_for_a_dry_run_and_is_applied_intact(client: TestClient, fx: Fx) -> None:
    before, version = _content(CatalogueService, SERVICE), _version(CatalogueService, SERVICE)
    outcome: list[str] = []

    def real_change() -> None:
        with SessionLocal() as db:
            admin = db.get(User, fx.admin_id)
            assert admin is not None
            svc.set_service_status(db, admin, SERVICE, "planned", None, version)
            outcome.append("ok")

    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        db.commit()
        with svc.dry_run(db):
            svc.prepare_service_status(db, admin, SERVICE, "hold", "Iemesls", version)
            thread = threading.Thread(target=real_change)
            thread.start()
            thread.join(timeout=0.5)
            assert thread.is_alive()  # waits for the dry run's row lock
    thread.join(timeout=30)
    assert outcome == ["ok"]
    after = _content(CatalogueService, SERVICE)
    assert (after["status"], _version(CatalogueService, SERVICE)) == ("planned", version + 1)
    [entry] = _catalogue_log()
    assert entry.before == before  # the dry run left no trace in the real change's history
