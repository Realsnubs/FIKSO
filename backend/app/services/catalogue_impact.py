"""Scope and basis of a proposed catalogue change (R-CAT-18, step 4.5.4).

The *scope* of a change is every catalogue row its impact depends on: the changed entry, its ancestors, every
affected service with its specialisation and category before and after a move, and every qualification type in
the old and new effective requirements of the affected services. The *basis* is the scope with the version of
each row. A preview returns the basis; a change that sends it back is applied only if the basis is still
exactly the same — the same rows (no entry added to or moved out of an affected branch) with the same
versions.

Locks (`lock_scope`) follow the one catalogue order — category → specialisation → service → qualification
type, ascending ID within a level — with one mode per level in every scenario, so no transaction ever upgrades
FOR SHARE to FOR UPDATE. A *container* whose membership defines the affected services (the changed category
and its specialisations, a changed specialisation) is locked FOR UPDATE: creating a child (FK `KEY SHARE`) or
moving one in or out (FOR SHARE / FOR UPDATE on that row) then waits until the change is committed.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import status
from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    MasterCompetency,
    MasterProfile,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications, specialisation_qualifications
from app.schemas.catalogue import ServiceUpdate, SpecialisationUpdate
from app.services import catalogue, eligibility

EntityKind = Literal["category", "specialisation", "service"]
ChangeKind = Literal["status", "move", "qualification_required", "requirements", "activate_hold"]
Mode = Literal["update", "share"]
BasisKind = Literal["category", "specialisation", "service", "qualification"]

ALLOWED_CHANGES: dict[str, frozenset[str]] = {
    "category": frozenset({"status"}),
    "specialisation": frozenset({"status", "move", "qualification_required", "requirements"}),
    "service": frozenset({"status", "move", "qualification_required", "requirements", "activate_hold"}),
}
# Lock and basis order: parents before children, qualification types last.
LEVELS: tuple[tuple[BasisKind, Any], ...] = (
    ("category", CatalogueCategory),
    ("specialisation", CatalogueSpecialisation),
    ("service", CatalogueService),
    ("qualification", Qualification),
)
BASIS_MAX = 2000
LOCK_TIMEOUT = "3s"


@dataclass(frozen=True)
class ProposedChange:
    entity: EntityKind
    id: uuid.UUID
    kind: ChangeKind
    status: str | None = None
    reason: str | None = None
    target_id: uuid.UUID | None = None  # move: the new parent
    value: bool | None = None  # qualification_required
    qualification_ids: tuple[uuid.UUID, ...] | None = None  # requirements: the new set


@dataclass(frozen=True)
class Scope:
    """Rows per level with the lock mode of that level, and the services whose availability can change."""

    rows: dict[BasisKind, frozenset[uuid.UUID]]
    modes: dict[BasisKind, Mode]
    affected_services: frozenset[uuid.UUID] = field(default_factory=frozenset)


@dataclass(frozen=True, order=True)
class BasisItem:
    kind: BasisKind
    id: uuid.UUID
    version: int


def validate(change: ProposedChange) -> None:
    if change.kind not in ALLOWED_CHANGES[change.entity]:
        raise AppError(
            "IMPACT_CHANGE_NOT_SUPPORTED",
            f"A {change.entity} cannot be previewed for '{change.kind}'.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


def _not_found(kind: str) -> AppError:
    return AppError(f"{kind.upper()}_NOT_FOUND", f"Catalogue {kind} not found.", status.HTTP_404_NOT_FOUND)


def _required_types(
    db: Session, services: Iterable[uuid.UUID], specialisations: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Qualification types required by these services or these specialisations (two queries, any size)."""
    services, specialisations = list(services), list(specialisations)
    found: set[uuid.UUID] = set()
    if services:
        found |= set(
            db.scalars(
                select(service_qualifications.c.qualification_id).where(
                    service_qualifications.c.service_id.in_(services)
                )
            )
        )
    if specialisations:
        found |= set(
            db.scalars(
                select(specialisation_qualifications.c.qualification_id).where(
                    specialisation_qualifications.c.specialisation_id.in_(specialisations)
                )
            )
        )
    return found


def scope(db: Session, change: ProposedChange) -> Scope:
    """The rows the impact of `change` depends on, read from the current state (a fixed number of queries)."""
    validate(change)
    new_types = set(change.qualification_ids or ())
    if change.entity == "category":
        if db.get(CatalogueCategory, change.id) is None:
            raise _not_found("category")
        specs = set(
            db.scalars(
                select(CatalogueSpecialisation.id).where(CatalogueSpecialisation.category_id == change.id)
            )
        )
        services = set(
            db.scalars(select(CatalogueService.id).where(CatalogueService.specialisation_id.in_(specs)))
        )
        return Scope(
            rows={
                "category": frozenset({change.id}),
                "specialisation": frozenset(specs),
                "service": frozenset(services),
                "qualification": frozenset(_required_types(db, services, specs)),
            },
            modes={
                "category": "update",
                "specialisation": "update",
                "service": "share",
                "qualification": "share",
            },
            affected_services=frozenset(services),
        )

    if change.entity == "specialisation":
        spec = db.get(CatalogueSpecialisation, change.id)
        if spec is None:
            raise _not_found("specialisation")
        categories = {spec.category_id}
        if change.kind == "move" and change.target_id is not None:
            categories.add(change.target_id)
        services = set(
            db.scalars(select(CatalogueService.id).where(CatalogueService.specialisation_id == spec.id))
        )
        return Scope(
            rows={
                "category": frozenset(categories),
                "specialisation": frozenset({spec.id}),
                "service": frozenset(services),
                "qualification": frozenset(_required_types(db, services, [spec.id]) | new_types),
            },
            modes={
                "category": "share",
                "specialisation": "update",
                "service": "share",
                "qualification": "share",
            },
            affected_services=frozenset(services),
        )

    service = db.get(CatalogueService, change.id)
    if service is None:
        raise _not_found("service")
    specs = {service.specialisation_id}
    if change.kind == "move" and change.target_id is not None:
        specs.add(change.target_id)
    categories = set(
        db.scalars(select(CatalogueSpecialisation.category_id).where(CatalogueSpecialisation.id.in_(specs)))
    )
    return Scope(
        rows={
            "category": frozenset(categories),
            "specialisation": frozenset(specs),
            "service": frozenset({service.id}),
            "qualification": frozenset(_required_types(db, [service.id], specs) | new_types),
        },
        modes={"category": "share", "specialisation": "share", "service": "update", "qualification": "share"},
        affected_services=frozenset({service.id}),
    )


def lock_scope(db: Session, current: Scope) -> list[BasisItem]:
    """Lock every row of the scope in the catalogue order and return their versions (one query per level).

    `lock_timeout` bounds the wait; a timeout is reported as 409 CATALOGUE_BUSY (the transaction is aborted
    and must be rolled back by the caller, which every request does).
    """
    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    basis: list[BasisItem] = []
    for kind, model in LEVELS:
        ids = current.rows[kind]
        if not ids:
            continue
        query = (
            select(model.id, model.version)
            .where(model.id.in_(ids))
            .order_by(model.id)
            .with_for_update(read=current.modes[kind] == "share")
        )
        try:
            rows = db.execute(query).all()
        except OperationalError as exc:
            if not isinstance(exc.orig, LockNotAvailable):
                raise
            raise AppError(
                "CATALOGUE_BUSY",
                "The catalogue is being changed by someone else; try again.",
                status.HTTP_409_CONFLICT,
            ) from exc
        basis += [BasisItem(kind, row_id, version) for row_id, version in rows]
    return sorted(basis)


def lock_and_read_basis(db: Session, change: ProposedChange) -> tuple[Scope, list[BasisItem]]:
    """Scope → locks → the scope again under the locks. Equal scopes mean every row the impact depends on is
    locked and stays as read until the transaction ends. A different scope means the catalogue changed between
    the first read and the locks: 409 IMPACT_PREVIEW_OUTDATED, nothing is written.
    """
    before = scope(db, change)
    basis = lock_scope(db, before)
    after = scope(db, change)
    if after.rows != before.rows:
        locked = {(item.kind, item.id) for item in basis}
        now = {(kind, row_id) for kind, ids in after.rows.items() for row_id in ids}
        raise AppError(
            "IMPACT_PREVIEW_OUTDATED",
            "The catalogue changed while the change was being checked; preview it again.",
            status.HTTP_409_CONFLICT,
            {
                "changed": [],
                "added": [{"kind": k, "id": str(i)} for k, i in sorted(now - locked)],
                "removed": [{"kind": k, "id": str(i)} for k, i in sorted(locked - now)],
            },
        )
    return after, basis


def difference(current: list[BasisItem], expected: list[BasisItem]) -> dict[str, list[dict[str, Any]]]:
    """What differs from the basis the admin saw: changed versions, rows added since, rows gone from it."""
    now = {(item.kind, item.id): item.version for item in current}
    then = {(item.kind, item.id): item.version for item in expected}
    return {
        "changed": [
            {"kind": kind, "id": str(row_id), "expected": then[(kind, row_id)], "current": version}
            for (kind, row_id), version in sorted(now.items())
            if (kind, row_id) in then and then[(kind, row_id)] != version
        ],
        "added": [
            {"kind": kind, "id": str(row_id), "version": version}
            for (kind, row_id), version in sorted(now.items())
            if (kind, row_id) not in then
        ],
        "removed": [
            {"kind": kind, "id": str(row_id), "expected": version}
            for (kind, row_id), version in sorted(then.items())
            if (kind, row_id) not in now
        ],
    }


# --- applying a previewed change (step 4.5.4.3) -------------------------------------------------------------


def change_for_update(
    entity: Literal["specialisation", "service"], entry_id: uuid.UUID, fields: dict[str, Any]
) -> ProposedChange:
    """The scope of a PATCH: a move (the wider scope, both branches) when the parent is in the body, otherwise
    the entry's own scope — the same rows as a `qualification_required` preview."""
    parent = fields.get("category_id" if entity == "specialisation" else "specialisation_id")
    if parent is not None:
        return ProposedChange(entity, entry_id, "move", target_id=parent)
    return ProposedChange(
        entity, entry_id, "qualification_required", value=fields.get("qualification_required")
    )


def check_basis(db: Session, change: ProposedChange, expected: list[BasisItem]) -> None:
    """Lock the change's scope and require it to be exactly the previewed basis — the same rows, none added or
    gone, every one at the same version — before the change runs (409 IMPACT_PREVIEW_OUTDATED otherwise).

    The caller then runs the real operation in the same transaction: its prepare_* takes rows already locked
    here in the same or a weaker mode, so there is no window between this check and the write, and no lock
    upgrade. Nothing is written before the check passes.
    """
    _, basis = lock_and_read_basis(db, change)
    outdated = difference(basis, sorted(expected))
    if any(outdated.values()):
        raise AppError(
            "IMPACT_PREVIEW_OUTDATED",
            "The catalogue changed since the impact preview; preview the change again.",
            status.HTTP_409_CONFLICT,
            outdated,
        )


# --- preview (step 4.5.4.2) ---------------------------------------------------------------------------------

MASTERS_LISTED = 100
NOTES = {
    "open_requests": "Not available yet: client requests are implemented in step 5.",
    "eligible_masters": (
        "A snapshot at computed_at. Master decisions do not change catalogue versions, so the master counts "
        "can change before the change is applied; the basis protects the catalogue state only."
    ),
}


def _apply(db: Session, admin: User, change: ProposedChange, version: int) -> None:
    """The real operation's own prepare_* (same checks, same errors), with the version just locked."""
    if change.entity == "category":
        catalogue.prepare_category_status(db, admin, change.id, str(change.status), change.reason, version)
    elif change.entity == "specialisation":
        if change.kind == "status":
            catalogue.prepare_specialisation_status(
                db, admin, change.id, str(change.status), change.reason, version
            )
        elif change.kind == "requirements":
            catalogue.prepare_specialisation_requirements(
                db, admin, change.id, change.qualification_ids or (), version
            )
        else:
            fields = (
                {"category_id": change.target_id}
                if change.kind == "move"
                else {"qualification_required": change.value}
            )
            catalogue.prepare_specialisation_update(
                db, admin, change.id, SpecialisationUpdate(expected_version=version, **fields)
            )
    elif change.kind == "status":
        catalogue.prepare_service_status(db, admin, change.id, str(change.status), change.reason, version)
    elif change.kind == "activate_hold":
        catalogue.prepare_activate_hold(db, admin, change.id, str(change.reason), version)
    elif change.kind == "requirements":
        catalogue.prepare_service_requirements(db, admin, change.id, change.qualification_ids or (), version)
    else:
        fields = (
            {"specialisation_id": change.target_id}
            if change.kind == "move"
            else {"qualification_required": change.value}
        )
        catalogue.prepare_service_update(
            db, admin, change.id, ServiceUpdate(expected_version=version, **fields)
        )


def _state(item: catalogue.Availability) -> dict[str, Any]:
    return {
        "orderable": item.orderable,
        "eligible_masters": item.eligible_masters,
        "reasons": [{"code": r.code, "details": r.details} for r in item.reasons],
    }


def _status_counts(db: Session, model: Any, column: Any, ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Rows per status of active (not deleted) masters for these specialisations or services."""
    ids = list(ids)
    if not ids:
        return {}
    rows = db.execute(
        select(model.status, func.count())
        .join(MasterProfile, MasterProfile.id == model.master_id)
        .join(User, User.id == MasterProfile.user_id)
        .where(column.in_(ids), User.deleted_at.is_(None))
        .group_by(model.status)
    ).tuples()
    return {row_status: count for row_status, count in rows}


def preview(db: Session, admin: User, change: ProposedChange) -> dict[str, Any]:
    """What `change` would do, computed by applying it for real inside `catalogue.dry_run` (step 4.5.4.2).

    Locks the scope first (so the basis, before and after all describe one catalogue state), runs the real
    prepare_* (an invalid change fails with exactly the real operation's error), compares availability and
    eligible masters before and after, and rolls everything back: nothing is written, logged or announced, and
    every lock is released when the request ends. A fixed number of queries, whatever the branch size.
    """
    with catalogue.dry_run(db):
        current, basis = lock_and_read_basis(db, change)
        target = next(item for item in basis if item.kind == change.entity and item.id == change.id)
        services = sorted(current.affected_services)
        computed_at = db.scalar(select(func.now()))
        before = catalogue.availability(db, services)
        pairs_before = eligibility.eligible_pairs(db, services)
        by_specialisation = _status_counts(
            db, MasterSpecialisation, MasterSpecialisation.specialisation_id, current.rows["specialisation"]
        )
        by_competency = _status_counts(db, MasterCompetency, MasterCompetency.service_id, services)

        _apply(db, admin, change, target.version)

        after = catalogue.availability(db, services)
        pairs_after = eligibility.eligible_pairs(db, services)
        losing = {master_id for master_id, _ in pairs_before - pairs_after}
        listed = db.execute(
            select(MasterProfile.id, User.full_name)
            .join(User, User.id == MasterProfile.user_id)
            .where(MasterProfile.id.in_(losing))
            .order_by(User.full_name, MasterProfile.id)
            .limit(MASTERS_LISTED)
        ).all()
        labels = {
            row.id: (row.w_id, row.name)
            for row in db.execute(
                select(CatalogueService.id, CatalogueService.w_id, CatalogueService.name).where(
                    CatalogueService.id.in_(services)
                )
            )
        }
        result = {
            "basis": [{"kind": item.kind, "id": item.id, "version": item.version} for item in basis],
            "services": [
                {
                    "service_id": service_id,
                    "w_id": labels[service_id][0],
                    "name": labels[service_id][1],
                    "before": _state(before[service_id]),
                    "after": _state(after[service_id]),
                }
                for service_id in services
            ],
            "stops_being_orderable": [s for s in services if before[s].orderable and not after[s].orderable],
            "becomes_orderable": [s for s in services if not before[s].orderable and after[s].orderable],
            "masters": {
                "by_specialisation_status": by_specialisation,
                "by_competency_status": by_competency,
                "losing_eligibility": {
                    "total": len(losing),
                    "items": [{"master_id": master_id, "full_name": name} for master_id, name in listed],
                },
            },
            "open_requests": None,
            "notes": NOTES,
            "computed_at": computed_at,
        }
    return result
