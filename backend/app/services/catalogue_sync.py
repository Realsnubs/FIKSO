"""Catalogue transfer between environments: production export → staging import (R-CAT-15/16).

Entries are matched by UUID *and* W-ID. Missing entries are created with their original IDs; differing
entries are updated only when the admin selects them and they were not edited locally; any identity conflict
rejects the whole package. Nothing in the target is ever deleted, renumbered or merged (ARCHITECTURE §6a).
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import signing
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    CatalogueSyncImport,
    Qualification,
    User,
)
from app.models.catalogue import KVC_W_ID_PATTERN, W_ID_PATTERN
from app.schemas.catalogue import GroupStatus, QualificationStatus, RiskLevel, ServiceStatus
from app.services import catalogue as cat
from app.services.events import record_audit, record_event

FORMAT = "fikso-catalogue/1"
Source = Literal["seed_cm_v1", "kvc_v1", "admin"]


# ---------------------------------------------------------------- package schema


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    version: int


class _EntryItem(_Item):
    name: str
    description: str | None
    sort_order: int
    source: Source
    source_ref: str | None


class CategoryItem(_EntryItem):
    status: GroupStatus


class SpecialisationItem(_EntryItem):
    status: GroupStatus
    category_id: uuid.UUID
    qualification_required: bool


class ServiceItem(_EntryItem):
    status: ServiceStatus
    specialisation_id: uuid.UUID
    w_id: Annotated[str, Field(pattern=W_ID_PATTERN)]
    risk_level: RiskLevel
    qualification_required: bool
    restrictions: str | None
    review_note: str | None
    source_status: str | None


class QualificationItem(_Item):
    name: str
    description: str | None
    status: QualificationStatus
    requires_document: bool
    requires_document_number: bool
    requires_expiry_date: bool
    max_validity_months: int | None
    verifier_instructions: str | None


class Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["fikso-catalogue/1"]
    source_environment: str
    catalogue_role: Literal["issuer", "receiver", "isolated"]
    package_id: uuid.UUID
    key_id: Annotated[str, Field(pattern=signing.KEY_ID_PATTERN)]
    exported_at: datetime
    categories: list[CategoryItem]
    specialisations: list[SpecialisationItem]
    qualifications: list[QualificationItem]
    services: list[ServiceItem]
    service_qualifications: list[tuple[uuid.UUID, uuid.UUID]]
    specialisation_qualifications: list[tuple[uuid.UUID, uuid.UUID]]
    signature: str

    @model_validator(mode="after")
    def _unique_ids(self) -> "Package":
        ids = [
            i.id
            for group in (self.categories, self.specialisations, self.qualifications, self.services)
            for i in group
        ]
        w_ids = [s.w_id for s in self.services]
        if len(ids) != len(set(ids)) or len(w_ids) != len(set(w_ids)):
            raise ValueError("duplicate IDs in package")
        return self


# Kinds in dependency order: parents are created before children.
KINDS: list[tuple[str, type[Any], str]] = [
    ("category", CatalogueCategory, "categories"),
    ("specialisation", CatalogueSpecialisation, "specialisations"),
    ("qualification", Qualification, "qualifications"),
    ("service", CatalogueService, "services"),
]
PARENT = {
    "specialisation": ("category_id", "categories"),
    "service": ("specialisation_id", "specialisations"),
}


def _item_content(item: _Item) -> dict[str, Any]:
    return item.model_dump(mode="json", exclude={"id", "version"})


def _links(
    package: Package,
) -> list[tuple[type[CatalogueService] | type[CatalogueSpecialisation], uuid.UUID, uuid.UUID]]:
    owners: list[tuple[type[CatalogueService] | type[CatalogueSpecialisation], uuid.UUID, uuid.UUID]] = [
        (CatalogueService, s, q) for s, q in package.service_qualifications
    ]
    return owners + [(CatalogueSpecialisation, s, q) for s, q in package.specialisation_qualifications]


def _signed_bytes(body: dict[str, Any]) -> bytes:
    """All but the signature is signed: metadata, key ID, entities, statuses, links and versions."""
    return cat.canonical_json({k: v for k, v in body.items() if k != "signature"}).encode()


def sign_package(body: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    private_key = settings.catalogue_signing_private_key
    if private_key is None or not settings.catalogue_signing_key_id:
        raise AppError(
            "SIGNING_KEY_MISSING", "No catalogue signing key is configured here.", status.HTTP_409_CONFLICT
        )
    signed = {k: v for k, v in body.items() if k != "signature"} | {
        "key_id": settings.catalogue_signing_key_id
    }
    return signed | {"signature": signing.sign(private_key.get_secret_value(), _signed_bytes(signed))}


def _package_sha(body: dict[str, Any]) -> str:
    return hashlib.sha256(cat.canonical_json(body).encode()).hexdigest()


# ---------------------------------------------------------------- export


def export_package(db: Session, admin: User) -> dict[str, Any]:
    settings = get_settings()
    if settings.catalogue_role == "receiver":
        raise AppError(
            "EXPORT_NOT_ALLOWED",
            "Staging does not export catalogue packages; production is the only source.",
            status.HTTP_409_CONFLICT,
        )
    categories, qualifications = cat.tree(db)
    specs = [s for c in categories for s in c.specialisations]
    services = [v for s in specs for v in s.services]

    def item(entity: Any) -> dict[str, Any]:
        return {"id": str(entity.id), "version": entity.version} | cat.content(entity)

    body: dict[str, Any] = {
        "format": FORMAT,
        "source_environment": settings.environment,
        "catalogue_role": settings.catalogue_role,
        "package_id": str(uuid.uuid4()),
        "exported_at": datetime.now(UTC).isoformat(),
        "categories": [item(c) for c in categories],
        "specialisations": [item(s) for s in specs],
        "qualifications": [item(q) for q in qualifications],
        "services": [item(v) for v in services],
        "service_qualifications": sorted([str(v.id), str(q.id)] for v in services for q in v.qualifications),
        "specialisation_qualifications": sorted(
            [str(s.id), str(q.id)] for s in specs for q in s.qualifications
        ),
    }
    body = sign_package(body)
    record_audit(
        db,
        "catalogue.exported",
        "catalogue_export",
        None,
        "user",
        admin.id,
        after={
            "package_id": body["package_id"],
            "key_id": body["key_id"],
            "sha256": _package_sha({k: v for k, v in body.items() if k != "signature"}),
            "services": len(services),
        },
    )
    db.commit()
    return body


# ---------------------------------------------------------------- preview / plan


def _verify(raw: dict[str, Any]) -> tuple[Package, str]:
    if get_settings().catalogue_role != "receiver":
        raise AppError(
            "IMPORT_NOT_ALLOWED",
            "Only staging imports catalogue packages; production is the single source of catalogue IDs.",
            status.HTTP_409_CONFLICT,
        )
    try:
        package = Package.model_validate(raw)
    except ValidationError as exc:
        raise AppError(
            "PACKAGE_INVALID",
            "The file is not a valid FIKSO catalogue package.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"errors": exc.error_count()},
        ) from exc
    settings = get_settings()
    if package.key_id in settings.catalogue_revoked_key_ids:
        raise AppError(
            "PACKAGE_KEY_REVOKED",
            "The package was signed with a revoked key.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    public_key = settings.catalogue_trusted_public_keys.get(package.key_id)
    if public_key is None:
        raise AppError(
            "PACKAGE_KEY_UNKNOWN",
            "The package was signed with an untrusted key.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if not signing.verify(public_key, _signed_bytes(raw), package.signature):
        raise AppError(
            "PACKAGE_SIGNATURE_INVALID",
            "The package signature is invalid.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    body = {k: v for k, v in raw.items() if k != "signature"}
    if package.catalogue_role != "issuer" or package.source_environment != "production":
        raise AppError(
            "PACKAGE_NOT_FROM_PRODUCTION",
            "Only packages exported from production can be imported.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return package, _package_sha(body)


def _status_equal(package_status: str, target_status: str) -> bool:
    # Imported "active" entries land as "inactive" unless kept active, which is not a difference to report.
    return package_status == target_status or (package_status == "active" and target_status == "inactive")


def build_plan(db: Session, package: Package) -> dict[str, Any]:
    plan: dict[str, Any] = {"create": [], "update": [], "unchanged": [], "conflicts": [], "links_to_add": 0}
    package_ids = {name: {i.id for i in getattr(package, name)} for _, _, name in KINDS}

    def conflict(kind: str, item: Any, reason: str) -> None:
        plan["conflicts"].append(
            {
                "kind": kind,
                "id": str(item.id),
                "w_id": getattr(item, "w_id", None),
                "name": item.name,
                "reason": reason,
            }
        )

    for kind, model, name in KINDS:
        for item in getattr(package, name):
            if kind in PARENT:
                field, parent_group = PARENT[kind]
                parent_id = getattr(item, field)
                parent_model = CatalogueCategory if kind == "specialisation" else CatalogueSpecialisation
                if parent_id not in package_ids[parent_group] and db.get(parent_model, parent_id) is None:
                    conflict(kind, item, "parent_missing")
                    continue
            if kind == "service":
                is_kvc = re.match(KVC_W_ID_PATTERN, item.w_id) is not None
                if is_kvc != (item.source == "kvc_v1"):
                    conflict(kind, item, "w_id_source_mismatch")
                    continue
            target = db.get(model, item.id)
            entry = {"kind": kind, "id": str(item.id), "name": item.name, "w_id": getattr(item, "w_id", None)}
            if target is None:
                if kind == "service":
                    holder = db.scalar(select(CatalogueService.id).where(CatalogueService.w_id == item.w_id))
                    if holder is not None:
                        conflict(kind, item, "w_id_used_by_other_uuid")
                        continue
                plan["create"].append(entry)
                continue
            if kind == "service" and target.w_id != item.w_id:
                conflict(kind, item, "uuid_has_other_w_id")
                continue
            current, incoming = cat.content(target), _item_content(item)
            changes = sorted(
                f
                for f in incoming
                if not (
                    _status_equal(incoming[f], current[f]) if f == "status" else incoming[f] == current[f]
                )
            )
            if not changes:
                plan["unchanged"].append(entry)
            else:
                locally_edited = target.last_sync_hash != cat.content_hash(current)
                plan["update"].append(entry | {"changes": changes, "locally_edited": locally_edited})

    for owner_model, owner_id, qualification_id in _links(package):
        owner = cast(CatalogueService | CatalogueSpecialisation | None, db.get(owner_model, owner_id))
        if owner is None or all(q.id != qualification_id for q in owner.qualifications):
            plan["links_to_add"] += 1
    return plan


def _check_replay(db: Session, package: Package, sha: str) -> None:
    """Refuse a package applied before (same ID or bytes) or older than the newest applied one."""
    applied = select(CatalogueSyncImport).where(CatalogueSyncImport.status == "applied")
    if db.scalar(
        applied.where(
            (CatalogueSyncImport.package_id == package.package_id)
            | (CatalogueSyncImport.package_sha256 == sha)
        ).limit(1)
    ):
        raise AppError(
            "PACKAGE_ALREADY_APPLIED", "This package has already been applied.", status.HTTP_409_CONFLICT
        )
    newest = db.scalar(
        select(func.max(CatalogueSyncImport.exported_at)).where(CatalogueSyncImport.status == "applied")
    )
    if newest is not None and package.exported_at <= newest:
        raise AppError(
            "PACKAGE_OUTDATED",
            "A newer production package has already been applied; export a fresh package.",
            status.HTTP_409_CONFLICT,
        )


def preview(db: Session, admin: User, raw: dict[str, Any]) -> CatalogueSyncImport:
    package, sha = _verify(raw)
    _check_replay(db, package, sha)
    record = CatalogueSyncImport(
        package_id=package.package_id,
        key_id=package.key_id,
        package_sha256=sha,
        format_version=package.format,
        source_environment=package.source_environment,
        exported_at=package.exported_at,
        package=raw,
        preview=build_plan(db, package),
        uploaded_by=admin.id,
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        "catalogue.sync_import.previewed",
        "catalogue_sync_import",
        record.id,
        "user",
        admin.id,
        after={
            "package_id": str(package.package_id),
            "key_id": package.key_id,
            "sha256": sha,
            "conflicts": len(record.preview["conflicts"]),
        },
    )
    db.commit()
    return record


def get_import(db: Session, import_id: uuid.UUID) -> CatalogueSyncImport:
    record = db.get(CatalogueSyncImport, import_id)
    if record is None:
        raise AppError("IMPORT_NOT_FOUND", "Import not found.", status.HTTP_404_NOT_FOUND)
    return record


# ---------------------------------------------------------------- apply


def apply(
    db: Session,
    admin: User,
    import_id: uuid.UUID,
    apply_updates: list[uuid.UUID],
    keep_active: list[uuid.UUID],
) -> CatalogueSyncImport:
    record = get_import(db, import_id)
    if record.status != "previewed":
        raise AppError("IMPORT_NOT_PENDING", "This import is no longer pending.", status.HTTP_409_CONFLICT)
    package, sha = _verify(record.package)
    _check_replay(db, package, sha)
    # Re-plan against the current state: the catalogue may have changed since the preview.
    plan = build_plan(db, package)
    record.preview = plan
    if plan["conflicts"]:
        record.status = "rejected"
        db.commit()
        raise AppError(
            "IMPORT_CONFLICT",
            "The package conflicts with existing catalogue IDs; nothing was imported.",
            status.HTTP_409_CONFLICT,
            {"conflicts": plan["conflicts"]},
        )

    updates = {u["id"]: u for u in plan["update"]}
    for entity_id in map(str, apply_updates):
        if entity_id not in updates:
            raise AppError(
                "NOT_AN_UPDATE",
                "Only listed update candidates can be applied.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"id": entity_id},
            )
        if updates[entity_id]["locally_edited"]:
            raise AppError(
                "LOCALLY_EDITED",
                "This entry was edited here; it is not overwritten.",
                status.HTTP_409_CONFLICT,
                {"id": entity_id},
            )
    creates = {c["id"] for c in plan["create"]}
    selected = set(map(str, apply_updates))
    keep = set(map(str, keep_active))
    active_in_package = {
        str(i.id)
        for kind, _, name in KINDS
        if kind != "qualification"
        for i in getattr(package, name)
        if i.status == "active"
    }
    for entity_id in keep:
        if entity_id not in active_in_package or entity_id not in creates | selected:
            raise AppError(
                "INVALID_KEEP_ACTIVE",
                "Keep active applies only to imported entries active in production.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"id": entity_id},
            )
    touched: list[Any] = []

    for _kind, model, name in KINDS:
        for item in getattr(package, name):
            entity_id = str(item.id)
            if entity_id not in creates and entity_id not in selected:
                continue
            values = _item_content(item)
            existing = None if entity_id in creates else db.get(model, item.id)
            # Qualifications are configuration, not orderable entries: their status is carried as-is.
            if values["status"] == "active" and model is not Qualification:
                # Active arrives inactive unless kept active; an already active entry stays active; HOLD is
                # never activated by an import (R-CAT-04).
                stays_active = existing is not None and existing.status == "active"
                on_hold = existing is not None and existing.status == "hold"
                if on_hold or not (stays_active or entity_id in keep):
                    values["status"] = "inactive"
            for id_field in ("category_id", "specialisation_id"):
                if id_field in values:
                    values[id_field] = uuid.UUID(values[id_field])
            if entity_id in creates:
                entity = model(id=item.id, created_by=admin.id, updated_by=admin.id, **values)
                db.add(entity)
                action = "imported"
            else:
                assert existing is not None  # planned as an update, so it exists
                entity = existing
                before = cat.content(entity)
                for field, value in values.items():
                    setattr(entity, field, value)
                entity.version += 1
                entity.updated_by = admin.id
                action = "import_updated"
            touched.append((entity, action, None if action == "imported" else before))
    try:
        db.flush()
        for owner_model, owner_id, qualification_id in _links(package):
            owner = cast(CatalogueService | CatalogueSpecialisation | None, db.get(owner_model, owner_id))
            qualification = db.get(Qualification, qualification_id)
            if owner is not None and qualification is not None and qualification not in owner.qualifications:
                owner.qualifications.append(qualification)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "IMPORT_CONFLICT",
            "The package conflicts with existing catalogue data; nothing was imported.",
            status.HTTP_409_CONFLICT,
        ) from exc

    services = [e for e, _, _ in touched if isinstance(e, CatalogueService)]
    cat.assert_active_services_ready(services)
    cat.advance_w_id_sequence(db, [s.w_id for s in package.services])

    for entity, action, before in touched:
        entity.last_sync_hash = cat.content_hash(cat.content(entity))
        cat.log_change(db, admin, action, entity, before)
    # Rows equal to production are marked as synced, so later local edits to them are detected.
    for entry in plan["unchanged"]:
        model = next(m for k, m, _ in KINDS if k == entry["kind"])
        entity = db.get(model, uuid.UUID(entry["id"]))
        assert entity is not None
        entity.last_sync_hash = cat.content_hash(cat.content(entity))

    record.status, record.applied_by, record.applied_at = "applied", admin.id, datetime.now(UTC)
    summary = {
        "package_id": str(package.package_id),
        "key_id": package.key_id,
        "sha256": sha,
        "created": len(creates),
        "updated": len(selected),
    }
    record_audit(
        db,
        "catalogue.sync_import.applied",
        "catalogue_sync_import",
        record.id,
        "user",
        admin.id,
        after=summary,
    )
    record_event(
        db, "catalogue.sync_import.applied", "catalogue_sync_import", record.id, "user", admin.id, summary
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "PACKAGE_ALREADY_APPLIED", "This package has already been applied.", status.HTTP_409_CONFLICT
        ) from exc
    return record
