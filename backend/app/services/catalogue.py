"""Catalogue administration (R-CAT, ARCHITECTURE §6a).

Every mutation: one transaction, `audit_log` entry with before/after, `catalogue.*` domain event.
IDs and W-IDs are assigned here or by the DB and never changed; nothing is deleted.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import CatalogueCategory, CatalogueService, CatalogueSpecialisation, Qualification, User
from app.models.catalogue import W_ID_SEQUENCE, CatalogueEntry
from app.schemas.catalogue import (
    CategoryCreate,
    CategoryUpdate,
    QualificationCreate,
    QualificationUpdate,
    ServiceCreate,
    ServiceUpdate,
    SpecialisationCreate,
    SpecialisationUpdate,
)
from app.services import eligibility
from app.services.events import record_audit, record_event

Entity = CatalogueCategory | CatalogueSpecialisation | CatalogueService | Qualification

KIND: dict[type, str] = {
    CatalogueCategory: "category",
    CatalogueSpecialisation: "specialisation",
    CatalogueService: "service",
    Qualification: "qualification",
}

# Allowed status transitions per level. HOLD → active is only possible through activate_hold().
GROUP_TRANSITIONS = {
    "active": {"inactive", "planned", "archived"},
    "inactive": {"active", "planned", "archived"},
    "planned": {"active", "inactive", "archived"},
    "archived": {"inactive"},
}
SERVICE_TRANSITIONS = {
    "draft": {"active", "inactive", "planned", "rejected"},
    "active": {"inactive", "planned", "hold", "archived"},
    "inactive": {"active", "planned", "hold", "archived"},
    "planned": {"active", "inactive", "hold", "archived"},
    "hold": {"inactive", "planned", "archived"},
    "rejected": set(),
    "archived": {"inactive"},
}
QUALIFICATION_TRANSITIONS = {"draft": {"active", "archived"}, "active": {"archived"}, "archived": {"active"}}
REASON_REQUIRED = {"rejected", "archived", "hold"}
# Statuses whose siblings take part in display ordering.
HIDDEN_FROM_ORDER = {"archived", "rejected"}
# Aggregate ID for events about the top level (category ordering), which has no parent row.
ROOT_ID = uuid.UUID(int=0)


# ---------------------------------------------------------------- content, hashing


def content(entity: Entity) -> dict[str, Any]:
    """Business content of an entry: used for audit snapshots, export packages and sync hashes."""
    if isinstance(entity, Qualification):
        return {
            "name": entity.name,
            "description": entity.description,
            "status": entity.status,
            "requires_document": entity.requires_document,
            "requires_document_number": entity.requires_document_number,
            "requires_expiry_date": entity.requires_expiry_date,
            "max_validity_months": entity.max_validity_months,
            "verifier_instructions": entity.verifier_instructions,
        }
    data: dict[str, Any] = {
        "name": entity.name,
        "description": entity.description,
        "status": entity.status,
        "sort_order": entity.sort_order,
        "source": entity.source,
        "source_ref": entity.source_ref,
    }
    if isinstance(entity, CatalogueSpecialisation):
        data |= {
            "category_id": str(entity.category_id),
            "qualification_required": entity.qualification_required,
        }
    elif isinstance(entity, CatalogueService):
        data |= {
            "specialisation_id": str(entity.specialisation_id),
            "w_id": entity.w_id,
            "risk_level": entity.risk_level,
            "qualification_required": entity.qualification_required,
            "restrictions": entity.restrictions,
            "review_note": entity.review_note,
            "source_status": entity.source_status,
        }
    return data


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


# ---------------------------------------------------------------- shared helpers


def require_can_create() -> None:
    """R-CAT-16: staging only receives production exports and never creates catalogue entries itself."""
    if get_settings().catalogue_role == "receiver":
        raise AppError(
            "W_ID_AUTHORITY_REQUIRED",
            "Catalogue entries are created only in production; import them from a production export.",
            status.HTTP_409_CONFLICT,
        )


def next_w_id(db: Session) -> str:
    return f"W{db.scalar(text(f"SELECT nextval('{W_ID_SEQUENCE}')")):03d}"


def advance_w_id_sequence(db: Session, w_ids: Iterable[str]) -> None:
    """Move the sequence past explicitly inserted W071+ IDs. GREATEST keeps it from ever moving backwards."""
    numbers = [int(w[1:]) for w in w_ids if int(w[1:]) > 70]
    if not numbers:
        return
    db.execute(
        text(
            # Sequence name is a module constant, not input.
            f"SELECT setval('{W_ID_SEQUENCE}', GREATEST((SELECT last_value FROM {W_ID_SEQUENCE}), :n), true)"  # noqa: S608
        ),
        {"n": max(numbers)},
    )


def _get[T: Entity](db: Session, model: type[T], entity_id: uuid.UUID) -> T:
    entity = db.get(model, entity_id)
    if entity is None:
        kind = KIND[model]
        raise AppError(f"{kind.upper()}_NOT_FOUND", f"Catalogue {kind} not found.", status.HTTP_404_NOT_FOUND)
    return entity


def _lock[T: Entity](db: Session, model: type[T], entity_id: uuid.UUID, *, share: bool = False) -> T:
    """Lock the row (FOR UPDATE, or FOR SHARE for a parent that is only checked) and reload it, so every check
    below sees the current committed state, never an earlier read (step 4.5.3.1).

    Lock order, the same in every operation: category → specialisation → service → qualification types, and
    by ascending ID within one level. A parent is always locked before its child, never after.
    """
    entity = db.scalar(
        select(model)
        .where(model.id == entity_id)
        .with_for_update(read=share)
        .execution_options(populate_existing=True)
    )
    if entity is None:
        kind = KIND[model]
        raise AppError(f"{kind.upper()}_NOT_FOUND", f"Catalogue {kind} not found.", status.HTTP_404_NOT_FOUND)
    return entity


def _check_version(entity: Entity, expected_version: int) -> None:
    """Optimistic concurrency on top of the row lock: the admin decided on the version they saw."""
    if entity.version != expected_version:
        raise AppError(
            "VERSION_CONFLICT",
            "The entry changed since it was loaded.",
            status.HTTP_409_CONFLICT,
            {"version": entity.version, "status": entity.status},
        )


def _lock_specialisations(db: Session, ids: Iterable[uuid.UUID]) -> None:
    for spec_id in sorted(set(ids)):
        _lock(db, CatalogueSpecialisation, spec_id, share=True)


def _parent_not_archived(parent: CatalogueEntry) -> None:
    if parent.status == "archived":
        raise AppError("PARENT_ARCHIVED", "The parent entry is archived.", status.HTTP_409_CONFLICT)


def _touch(entity: Entity, admin: User) -> None:
    entity.version += 1
    entity.updated_by = admin.id


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if constraint.endswith("_name"):
            raise AppError(
                "NAME_TAKEN", "An entry with this name already exists here.", status.HTTP_409_CONFLICT
            ) from exc
        raise AppError(
            "CATALOGUE_CONFLICT",
            "The change conflicts with existing catalogue data.",
            status.HTTP_409_CONFLICT,
            {"constraint": constraint},
        ) from exc


def log_change(
    db: Session,
    admin: User,
    action: str,
    entity: Entity,
    before: dict[str, Any] | None,
    reason: str | None = None,
) -> None:
    kind = KIND[type(entity)]
    after = content(entity)
    record_audit(
        db,
        f"catalogue.{kind}.{action}",
        f"catalogue_{kind}",
        entity.id,
        "user",
        admin.id,
        before,
        after,
        reason,
    )
    payload: dict[str, Any] = {"status": after["status"]}
    if isinstance(entity, CatalogueService):
        payload["w_id"] = entity.w_id
    record_event(db, f"catalogue.{kind}.{action}", f"catalogue_{kind}", entity.id, "user", admin.id, payload)


def _next_sort_order(db: Session, column: Any, parent_column: Any = None, parent_id: Any = None) -> int:
    query = select(func.coalesce(func.max(column), -1))
    if parent_column is not None:
        query = query.where(parent_column == parent_id)
    return int(db.scalar(query) or 0) + 1


def qualifications_ready(service: CatalogueService) -> bool:
    """Regulated-service gate (Q-21): a regulated service needs ≥1 requirement and all of them active."""
    if not (service.qualification_required or service.specialisation.qualification_required):
        return True
    required = {q.id: q for q in [*service.qualifications, *service.specialisation.qualifications]}
    return bool(required) and all(q.status == "active" for q in required.values())


def assert_active_services_ready(services: Iterable[CatalogueService]) -> None:
    not_ready = [s.w_id for s in services if s.status == "active" and not qualifications_ready(s)]
    if not_ready:
        raise AppError(
            "QUALIFICATION_NOT_CONFIGURED",
            "Regulated services need configured, active qualification requirements before activation.",
            status.HTTP_409_CONFLICT,
            {"w_ids": sorted(not_ready)},
        )


def _check_transition(transitions: dict[str, set[str]], current: str, new: str, reason: str | None) -> None:
    if new not in transitions.get(current, set()):
        raise AppError(
            "INVALID_STATUS_TRANSITION",
            f"Status cannot change from '{current}' to '{new}'.",
            status.HTTP_409_CONFLICT,
            {"from": current, "to": new},
        )
    if new in REASON_REQUIRED and not reason:
        raise AppError(
            "REASON_REQUIRED", "A reason is required for this status.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )


# ---------------------------------------------------------------- prepared changes (step 4.5.3)
# The changes that alter availability are split in two: `prepare_*` validates and applies the change to the
# session (flush included, so DB constraints and the regulated-service gate run) but never writes audit_log or
# domain_events and never commits; `_record` writes the audit entry and event of a prepared change. The public
# functions are `prepare_*` + `_record` + commit, exactly as before. The impact preview (step 4.5.4) runs only
# `prepare_*` inside `dry_run`, which rolls the whole transaction back.


@dataclass(frozen=True)
class Prepared[T: (CatalogueCategory, CatalogueSpecialisation, CatalogueService)]:
    entity: T
    action: str  # "status_changed" | "hold_activated" | "updated" | "requirements_changed"
    before: dict[str, Any]
    reason: str | None = None


def _record(db: Session, admin: User, change: Prepared[Any]) -> None:
    if change.action == "requirements_changed":
        _log_requirements(db, admin, change.entity, change.before, change.entity.qualifications)
    else:
        log_change(db, admin, change.action, change.entity, change.before, change.reason)


@contextmanager
def dry_run(db: Session) -> Iterator[None]:
    """Apply `prepare_*` changes only to see their effect; the whole transaction is rolled back at exit.

    A full rollback (not a savepoint) ends the transaction, so every row lock taken by the flushed changes is
    released and nothing written inside survives. The session must not hold uncommitted work of its own.
    """
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("dry_run needs a session without pending changes")
    try:
        yield
    finally:
        db.rollback()


# ---------------------------------------------------------------- availability (R-CAT-03, step 4.5)

# Reason codes why a service is not orderable, in the order they are reported.
SERVICE_NOT_ACTIVE = "SERVICE_NOT_ACTIVE"
SPECIALISATION_NOT_ACTIVE = "SPECIALISATION_NOT_ACTIVE"
CATEGORY_NOT_ACTIVE = "CATEGORY_NOT_ACTIVE"
QUALIFICATION_NOT_CONFIGURED = "QUALIFICATION_NOT_CONFIGURED"
NO_ELIGIBLE_MASTERS = "NO_ELIGIBLE_MASTERS"


@dataclass(frozen=True)
class Availability:
    service_id: uuid.UUID
    eligible_masters: int
    reasons: tuple[eligibility.Reason, ...] = ()

    @property
    def orderable(self) -> bool:
        return not self.reasons


def availability(
    db: Session, service_ids: Sequence[uuid.UUID] | None = None, today: date | None = None
) -> dict[uuid.UUID, Availability]:
    """Whether each service can be ordered now, and why not (R-CAT-03, DATABASE §3.2 "Orderability").

    Orderable = the service, its specialisation and its category are all `active`, the regulated-service gate
    passes (`qualifications_ready`), and at least one master is eligible. The count comes only from
    `eligibility.eligible_counts`, i.e. the R-MST-11 rule; no separate capacity logic exists. Computed from
    the current rows on every call (nothing stored, so never stale); reads only.
    """
    query = select(CatalogueService).options(
        selectinload(CatalogueService.qualifications),
        selectinload(CatalogueService.specialisation).selectinload(CatalogueSpecialisation.qualifications),
        selectinload(CatalogueService.specialisation).selectinload(CatalogueSpecialisation.category),
    )
    if service_ids is not None:
        query = query.where(CatalogueService.id.in_(service_ids))
    services = db.scalars(query).all()
    counts = eligibility.eligible_counts(db, [s.id for s in services], today)
    result = {}
    for service in services:
        spec = service.specialisation
        reasons = []
        for code, entry in (
            (SERVICE_NOT_ACTIVE, service),
            (SPECIALISATION_NOT_ACTIVE, spec),
            (CATEGORY_NOT_ACTIVE, spec.category),
        ):
            if entry.status != "active":
                reasons.append(eligibility.Reason(code, {"id": str(entry.id), "status": entry.status}))
        if not qualifications_ready(service):
            reasons.append(eligibility.Reason(QUALIFICATION_NOT_CONFIGURED))
        if counts[service.id] == 0:
            reasons.append(eligibility.Reason(NO_ELIGIBLE_MASTERS))
        result[service.id] = Availability(service.id, counts[service.id], tuple(reasons))
    return result


# ---------------------------------------------------------------- reads


def tree(db: Session) -> tuple[list[CatalogueCategory], list[Qualification]]:
    categories = db.scalars(
        select(CatalogueCategory)
        .options(
            selectinload(CatalogueCategory.specialisations).selectinload(
                CatalogueSpecialisation.qualifications
            ),
            selectinload(CatalogueCategory.specialisations)
            .selectinload(CatalogueSpecialisation.services)
            .selectinload(CatalogueService.qualifications),
        )
        .order_by(CatalogueCategory.sort_order, CatalogueCategory.name)
    ).all()
    qualifications = db.scalars(select(Qualification).order_by(Qualification.name)).all()
    return list(categories), list(qualifications)


# ---------------------------------------------------------------- categories


def create_category(db: Session, admin: User, data: CategoryCreate) -> CatalogueCategory:
    require_can_create()
    category = CatalogueCategory(
        name=data.name,
        description=data.description,
        status=data.status,
        sort_order=_next_sort_order(db, CatalogueCategory.sort_order),
        source="admin",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(category)
    _flush(db)
    log_change(db, admin, "created", category, None)
    db.commit()
    return category


def update_category(
    db: Session, admin: User, category_id: uuid.UUID, data: CategoryUpdate
) -> CatalogueCategory:
    category = _lock(db, CatalogueCategory, category_id)
    _check_version(category, data.expected_version)
    before = content(category)
    for field, value in data.changes().items():
        setattr(category, field, value)
    _touch(category, admin)
    _flush(db)
    log_change(db, admin, "updated", category, before)
    db.commit()
    return category


def set_category_status(
    db: Session, admin: User, category_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> CatalogueCategory:
    change = prepare_category_status(db, admin, category_id, new, reason, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_category_status(
    db: Session, admin: User, category_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> Prepared[CatalogueCategory]:
    category = _lock(db, CatalogueCategory, category_id)
    _check_version(category, expected_version)
    _check_transition(GROUP_TRANSITIONS, category.status, new, reason)
    before = content(category)
    category.status, category.status_reason = new, reason
    _touch(category, admin)
    _flush(db)
    return Prepared(category, "status_changed", before, reason)


# ---------------------------------------------------------------- specialisations


def create_specialisation(db: Session, admin: User, data: SpecialisationCreate) -> CatalogueSpecialisation:
    require_can_create()
    category = _get(db, CatalogueCategory, data.category_id)
    _parent_not_archived(category)
    spec = CatalogueSpecialisation(
        category_id=category.id,
        name=data.name,
        description=data.description,
        status=data.status,
        qualification_required=data.qualification_required,
        sort_order=_next_sort_order(
            db, CatalogueSpecialisation.sort_order, CatalogueSpecialisation.category_id, category.id
        ),
        source="admin",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(spec)
    _flush(db)
    log_change(db, admin, "created", spec, None)
    db.commit()
    return spec


def update_specialisation(
    db: Session, admin: User, spec_id: uuid.UUID, data: SpecialisationUpdate
) -> CatalogueSpecialisation:
    change = prepare_specialisation_update(db, admin, spec_id, data)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_specialisation_update(
    db: Session, admin: User, spec_id: uuid.UUID, data: SpecialisationUpdate
) -> Prepared[CatalogueSpecialisation]:
    changes = data.changes()
    target = changes.get("category_id")
    if target is not None:
        _lock(
            db, CatalogueCategory, target, share=True
        )  # the parent first; it must not be archived meanwhile
    spec = _lock(db, CatalogueSpecialisation, spec_id)
    _check_version(spec, data.expected_version)
    before = content(spec)
    if target is not None and target != spec.category_id:
        _parent_not_archived(_get(db, CatalogueCategory, target))
        spec.sort_order = _next_sort_order(
            db,
            CatalogueSpecialisation.sort_order,
            CatalogueSpecialisation.category_id,
            changes["category_id"],
        )
    for field, value in changes.items():
        setattr(spec, field, value)
    _touch(spec, admin)
    _flush(db)
    db.refresh(spec)
    assert_active_services_ready(spec.services)
    return Prepared(spec, "updated", before)


def set_specialisation_status(
    db: Session, admin: User, spec_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> CatalogueSpecialisation:
    change = prepare_specialisation_status(db, admin, spec_id, new, reason, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_specialisation_status(
    db: Session, admin: User, spec_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> Prepared[CatalogueSpecialisation]:
    spec = _lock(db, CatalogueSpecialisation, spec_id)
    _check_version(spec, expected_version)
    _check_transition(GROUP_TRANSITIONS, spec.status, new, reason)
    before = content(spec)
    spec.status, spec.status_reason = new, reason
    _touch(spec, admin)
    _flush(db)
    return Prepared(spec, "status_changed", before, reason)


def set_specialisation_requirements(
    db: Session,
    admin: User,
    spec_id: uuid.UUID,
    qualification_ids: Sequence[uuid.UUID],
    expected_version: int,
) -> CatalogueSpecialisation:
    change = prepare_specialisation_requirements(db, admin, spec_id, qualification_ids, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_specialisation_requirements(
    db: Session,
    admin: User,
    spec_id: uuid.UUID,
    qualification_ids: Sequence[uuid.UUID],
    expected_version: int,
) -> Prepared[CatalogueSpecialisation]:
    spec = _lock(db, CatalogueSpecialisation, spec_id)
    _check_version(spec, expected_version)
    before = {"qualification_ids": sorted(str(q.id) for q in spec.qualifications)}
    spec.qualifications = _load_qualifications(db, qualification_ids)
    _touch(spec, admin)
    _flush(db)
    assert_active_services_ready(spec.services)
    return Prepared(spec, "requirements_changed", before)


# ---------------------------------------------------------------- services


def create_service(db: Session, admin: User, data: ServiceCreate) -> CatalogueService:
    require_can_create()
    spec = _get(db, CatalogueSpecialisation, data.specialisation_id)
    _parent_not_archived(spec)
    service = CatalogueService(
        specialisation_id=spec.id,
        w_id=next_w_id(db),
        name=data.name,
        description=data.description,
        status=data.status,
        qualification_required=data.qualification_required,
        risk_level=data.risk_level,
        restrictions=data.restrictions,
        sort_order=_next_sort_order(
            db, CatalogueService.sort_order, CatalogueService.specialisation_id, spec.id
        ),
        source="admin",
        created_by=admin.id,
        updated_by=admin.id,
    )
    db.add(service)
    _flush(db)
    log_change(db, admin, "created", service, None)
    db.commit()
    return service


def update_service(db: Session, admin: User, service_id: uuid.UUID, data: ServiceUpdate) -> CatalogueService:
    change = prepare_service_update(db, admin, service_id, data)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_service_update(
    db: Session, admin: User, service_id: uuid.UUID, data: ServiceUpdate
) -> Prepared[CatalogueService]:
    changes = data.changes()
    target = changes.get("specialisation_id")
    service = _lock_service(db, service_id, *([target] if target is not None else []))
    _check_version(service, data.expected_version)
    before = content(service)
    if target is not None and target != service.specialisation_id:
        _parent_not_archived(_get(db, CatalogueSpecialisation, target))
        service.sort_order = _next_sort_order(
            db, CatalogueService.sort_order, CatalogueService.specialisation_id, changes["specialisation_id"]
        )
    for field, value in changes.items():
        setattr(service, field, value)
    _touch(service, admin)
    _flush(db)
    db.refresh(service)
    assert_active_services_ready([service])
    return Prepared(service, "updated", before)


def _lock_service(db: Session, service_id: uuid.UUID, *other_specialisations: uuid.UUID) -> CatalogueService:
    """Parents first: the service's specialisation (and a move target) FOR SHARE, then the service FOR UPDATE.

    The specialisation is the one read before locking; if the service moved in between, the move bumped its
    version and the caller's version check refuses the stale request.
    """
    current = _get(db, CatalogueService, service_id).specialisation_id
    _lock_specialisations(db, [current, *other_specialisations])
    return _lock(db, CatalogueService, service_id)


def set_service_status(
    db: Session, admin: User, service_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> CatalogueService:
    change = prepare_service_status(db, admin, service_id, new, reason, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_service_status(
    db: Session, admin: User, service_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> Prepared[CatalogueService]:
    service = _lock_service(db, service_id)
    _check_version(service, expected_version)
    if service.status == "hold" and new == "active":
        raise AppError(
            "HOLD_ACTIVATION_REQUIRED",
            "HOLD services are activated only through the explicit HOLD activation action.",
            status.HTTP_409_CONFLICT,
        )
    _check_transition(SERVICE_TRANSITIONS, service.status, new, reason)
    return _apply_service_status(db, admin, service, new, reason, "status_changed")


def activate_hold(
    db: Session, admin: User, service_id: uuid.UUID, reason: str, expected_version: int
) -> CatalogueService:
    change = prepare_activate_hold(db, admin, service_id, reason, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_activate_hold(
    db: Session, admin: User, service_id: uuid.UUID, reason: str, expected_version: int
) -> Prepared[CatalogueService]:
    service = _lock_service(db, service_id)
    _check_version(service, expected_version)
    if service.status != "hold":
        raise AppError("NOT_ON_HOLD", "The service is not on HOLD.", status.HTTP_409_CONFLICT)
    return _apply_service_status(db, admin, service, "active", reason, "hold_activated")


def _apply_service_status(
    db: Session, admin: User, service: CatalogueService, new: str, reason: str | None, action: str
) -> Prepared[CatalogueService]:
    before = content(service)
    service.status, service.status_reason = new, reason
    if new == "active":
        assert_active_services_ready([service])
        service.activated_by, service.activated_at = admin.id, datetime.now(UTC)
    _touch(service, admin)
    _flush(db)
    return Prepared(service, action, before, reason)


def set_service_requirements(
    db: Session,
    admin: User,
    service_id: uuid.UUID,
    qualification_ids: Sequence[uuid.UUID],
    expected_version: int,
) -> CatalogueService:
    change = prepare_service_requirements(db, admin, service_id, qualification_ids, expected_version)
    _record(db, admin, change)
    db.commit()
    return change.entity


def prepare_service_requirements(
    db: Session,
    admin: User,
    service_id: uuid.UUID,
    qualification_ids: Sequence[uuid.UUID],
    expected_version: int,
) -> Prepared[CatalogueService]:
    service = _lock_service(db, service_id)
    _check_version(service, expected_version)
    before = {"qualification_ids": sorted(str(q.id) for q in service.qualifications)}
    service.qualifications = _load_qualifications(db, qualification_ids)
    _touch(service, admin)
    _flush(db)
    assert_active_services_ready([service])
    return Prepared(service, "requirements_changed", before)


def _load_qualifications(db: Session, ids: Sequence[uuid.UUID]) -> list[Qualification]:
    unique_ids = set(ids)
    # Last in the lock order; FOR SHARE so a type cannot be archived while it is being required.
    found = list(
        db.scalars(
            select(Qualification)
            .where(Qualification.id.in_(unique_ids))
            .order_by(Qualification.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    if len(found) != len(unique_ids):
        raise AppError("QUALIFICATION_NOT_FOUND", "Unknown qualification.", status.HTTP_404_NOT_FOUND)
    if any(q.status == "archived" for q in found):
        raise AppError(
            "QUALIFICATION_ARCHIVED", "Archived qualifications cannot be required.", status.HTTP_409_CONFLICT
        )
    return found


def _log_requirements(
    db: Session,
    admin: User,
    entity: CatalogueSpecialisation | CatalogueService,
    before: dict[str, Any],
    qualifications: Sequence[Qualification],
) -> None:
    kind = KIND[type(entity)]
    after = {"qualification_ids": sorted(str(q.id) for q in qualifications)}
    action = f"catalogue.{kind}.requirements_changed"
    record_audit(db, action, f"catalogue_{kind}", entity.id, "user", admin.id, before, after)
    record_event(db, action, f"catalogue_{kind}", entity.id, "user", admin.id, after)


# ---------------------------------------------------------------- ordering


def reorder(
    db: Session, admin: User, kind: str, parent_id: uuid.UUID | None, ids: Sequence[uuid.UUID]
) -> None:
    model: type[CatalogueCategory | CatalogueSpecialisation | CatalogueService]
    siblings_query: Select[Any]
    if kind == "category":
        model, siblings_query = CatalogueCategory, select(CatalogueCategory)
    elif kind == "specialisation":
        _get(db, CatalogueCategory, parent_id)  # type: ignore[arg-type]
        model = CatalogueSpecialisation
        siblings_query = select(model).where(CatalogueSpecialisation.category_id == parent_id)
    else:
        _get(db, CatalogueSpecialisation, parent_id)  # type: ignore[arg-type]
        model = CatalogueService
        siblings_query = select(model).where(CatalogueService.specialisation_id == parent_id)
    siblings = {e.id: e for e in db.scalars(siblings_query) if e.status not in HIDDEN_FROM_ORDER}
    if len(ids) != len(set(ids)) or set(ids) != set(siblings):
        raise AppError(
            "ORDER_MISMATCH",
            "The order must list every visible sibling exactly once.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    before = {str(e.id): e.sort_order for e in siblings.values()}
    for position, entity_id in enumerate(ids):
        entity = siblings[entity_id]
        if entity.sort_order != position:
            entity.sort_order = position
            _touch(entity, admin)
    _flush(db)
    after = {str(e.id): e.sort_order for e in siblings.values()}
    record_audit(
        db, f"catalogue.{kind}.reordered", f"catalogue_{kind}", parent_id, "user", admin.id, before, after
    )
    record_event(
        db,
        f"catalogue.{kind}.reordered",
        f"catalogue_{kind}",
        parent_id or ROOT_ID,
        "user",
        admin.id,
        {"count": len(ids)},
    )
    db.commit()


# ---------------------------------------------------------------- qualifications


def create_qualification(db: Session, admin: User, data: QualificationCreate) -> Qualification:
    require_can_create()
    qualification = Qualification(
        **data.model_dump(), status="draft", created_by=admin.id, updated_by=admin.id
    )
    db.add(qualification)
    _flush(db)
    log_change(db, admin, "created", qualification, None)
    db.commit()
    return qualification


def update_qualification(
    db: Session, admin: User, qualification_id: uuid.UUID, data: QualificationUpdate
) -> Qualification:
    qualification = _get(db, Qualification, qualification_id)
    before = content(qualification)
    for field, value in data.changes().items():
        setattr(qualification, field, value)
    _touch(qualification, admin)
    _flush(db)
    log_change(db, admin, "updated", qualification, before)
    db.commit()
    return qualification


def set_qualification_status(
    db: Session, admin: User, qualification_id: uuid.UUID, new: str, reason: str | None, expected_version: int
) -> Qualification:
    qualification = _lock(db, Qualification, qualification_id)
    _check_version(qualification, expected_version)
    if new not in QUALIFICATION_TRANSITIONS.get(qualification.status, set()):
        raise AppError(
            "INVALID_STATUS_TRANSITION",
            f"Status cannot change from '{qualification.status}' to '{new}'.",
            status.HTTP_409_CONFLICT,
        )
    if new == "archived" and _is_required_anywhere(db, qualification.id):
        raise AppError(
            "QUALIFICATION_IN_USE",
            "Remove this qualification from all requirements before archiving it.",
            status.HTTP_409_CONFLICT,
        )
    before = content(qualification)
    qualification.status = new
    _touch(qualification, admin)
    _flush(db)
    log_change(db, admin, "status_changed", qualification, before, reason)
    db.commit()
    return qualification


def _is_required_anywhere(db: Session, qualification_id: uuid.UUID) -> bool:
    for model in (CatalogueService, CatalogueSpecialisation):
        query = select(model.id).where(model.qualifications.any(Qualification.id == qualification_id))
        if db.scalar(query.limit(1)) is not None:
            return True
    return False
