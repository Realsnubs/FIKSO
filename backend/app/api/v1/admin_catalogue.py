"""Admin catalogue management (R-CAT-08..16, ARCHITECTURE §6a). Every route requires the admin role."""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from app.api.deps import AdminUser, DbSession, require_role
from app.core.config import get_settings
from app.models import (
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    CatalogueSyncImport,
    Qualification,
)
from app.schemas.catalogue import (
    AvailabilityReasonOut,
    CatalogueTreeOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    HoldActivation,
    ImpactActivateHold,
    ImpactIn,
    ImpactMove,
    ImpactOut,
    ImpactQualificationRequired,
    ImpactStatus,
    OrderIn,
    QualificationCreate,
    QualificationOut,
    QualificationStatusChange,
    QualificationUpdate,
    RequirementsIn,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    SpecialisationCreate,
    SpecialisationOut,
    SpecialisationUpdate,
    StatusChange,
    SyncApplyIn,
    SyncImportOut,
    TreeCategoryOut,
    TreeServiceOut,
    TreeSpecialisationOut,
)
from app.services import catalogue as svc
from app.services import catalogue_impact
from app.services import catalogue_sync as sync

router = APIRouter(
    prefix="/admin/catalogue", tags=["admin-catalogue"], dependencies=[Depends(require_role("admin"))]
)

_ENTRY_FIELDS = (
    "id",
    "name",
    "description",
    "status",
    "status_reason",
    "sort_order",
    "source",
    "source_ref",
    "version",
    "updated_at",
)


SERVICE_FIELDS = (
    "specialisation_id",
    "w_id",
    "risk_level",
    "qualification_required",
    "restrictions",
    "review_note",
)


def _fields(entity: Any, *extra: str) -> dict[str, Any]:
    return {f: getattr(entity, f) for f in (*_ENTRY_FIELDS, *extra)}


def service_out(service: CatalogueService) -> ServiceOut:
    return ServiceOut(
        **_fields(service, *SERVICE_FIELDS),
        qualification_ids=[q.id for q in service.qualifications],
        qualifications_ready=svc.qualifications_ready(service),
    )


def specialisation_out(spec: CatalogueSpecialisation) -> SpecialisationOut:
    return SpecialisationOut(
        **_fields(spec, "category_id", "qualification_required"),
        qualification_ids=[q.id for q in spec.qualifications],
        services=[service_out(s) for s in spec.services],
    )


def category_out(category: CatalogueCategory) -> CategoryOut:
    return CategoryOut(
        **_fields(category), specialisations=[specialisation_out(s) for s in category.specialisations]
    )


def qualification_out(q: Qualification) -> QualificationOut:
    return QualificationOut.model_validate(q, from_attributes=True)


def import_out(record: CatalogueSyncImport) -> SyncImportOut:
    return SyncImportOut.model_validate(record, from_attributes=True)


@router.get("/tree")
def get_tree(db: DbSession) -> CatalogueTreeOut:
    categories, qualifications = svc.tree(db)
    # Every service of the tree, whatever its or its parents' status (step 4.5.2, R-CAT-03).
    availability = svc.availability(db)
    role = get_settings().catalogue_role
    return CatalogueTreeOut(
        catalogue_role=role,
        can_create=role != "receiver",
        categories=[_tree_category(c, availability) for c in categories],
        qualifications=[qualification_out(q) for q in qualifications],
    )


def _tree_category(
    category: CatalogueCategory, availability: dict[uuid.UUID, svc.Availability]
) -> TreeCategoryOut:
    out = category_out(category)
    return TreeCategoryOut(
        **out.model_dump(exclude={"specialisations"}),
        specialisations=[
            TreeSpecialisationOut(
                **spec.model_dump(exclude={"services"}),
                services=[_tree_service(service, availability[service.id]) for service in spec.services],
            )
            for spec in out.specialisations
        ],
    )


def _tree_service(service: ServiceOut, item: svc.Availability) -> TreeServiceOut:
    return TreeServiceOut(
        **service.model_dump(),
        eligible_masters=item.eligible_masters,
        orderable=item.orderable,
        orderable_reasons=[AvailabilityReasonOut(code=r.code, details=r.details) for r in item.reasons],
    )


# ---------------------------------------------------------------- previewed changes (step 4.5.4.3)


def _check_basis(db: DbSession, data: Any, change: Callable[[], catalogue_impact.ProposedChange]) -> None:
    """One mechanism for every change the impact preview supports: with `expected_basis`, the scope is locked
    and compared before the operation runs in the same transaction; without it, nothing changes (the
    operation's own locks and `expected_version` apply)."""
    if data.expected_basis is not None:
        expected = [catalogue_impact.BasisItem(b.kind, b.id, b.version) for b in data.expected_basis]
        catalogue_impact.check_basis(db, change(), expected)


def _status_change(entity: Any, entry_id: uuid.UUID, data: StatusChange) -> catalogue_impact.ProposedChange:
    return catalogue_impact.ProposedChange(entity, entry_id, "status", status=data.status, reason=data.reason)


def _requirements_change(
    entity: Any, entry_id: uuid.UUID, data: RequirementsIn
) -> catalogue_impact.ProposedChange:
    return catalogue_impact.ProposedChange(
        entity, entry_id, "requirements", qualification_ids=tuple(data.qualification_ids)
    )


# ---------------------------------------------------------------- impact preview (R-CAT-18)


@router.post("/impact")
def preview_impact(data: ImpactIn, db: DbSession, admin: AdminUser) -> ImpactOut:
    """Read-only: the change is applied inside a rolled-back transaction; nothing is written or audited."""
    change = data.change
    fields: dict[str, Any] = {}
    if isinstance(change, ImpactStatus):
        fields = {"status": change.status, "reason": change.reason}
    elif isinstance(change, ImpactActivateHold):
        fields = {"reason": change.reason}
    elif isinstance(change, ImpactMove):
        fields = {"target_id": change.target_id}
    elif isinstance(change, ImpactQualificationRequired):
        fields = {"value": change.value}
    else:
        fields = {"qualification_ids": tuple(change.qualification_ids)}
    proposed = catalogue_impact.ProposedChange(entity=data.entity, id=data.id, kind=change.kind, **fields)
    result = catalogue_impact.preview(db, admin, proposed)
    return ImpactOut(entity=data.entity, id=data.id, change=change, **result)


# ---------------------------------------------------------------- categories


@router.post("/categories", status_code=201)
def create_category(data: CategoryCreate, db: DbSession, admin: AdminUser) -> CategoryOut:
    return category_out(svc.create_category(db, admin, data))


@router.patch("/categories/{category_id}")
def update_category(
    category_id: uuid.UUID, data: CategoryUpdate, db: DbSession, admin: AdminUser
) -> CategoryOut:
    return category_out(svc.update_category(db, admin, category_id, data))


@router.post("/categories/{category_id}/status")
def set_category_status(
    category_id: uuid.UUID, data: StatusChange, db: DbSession, admin: AdminUser
) -> CategoryOut:
    _check_basis(db, data, lambda: _status_change("category", category_id, data))
    return category_out(
        svc.set_category_status(db, admin, category_id, data.status, data.reason, data.expected_version)
    )


@router.put("/categories/order", status_code=204)
def order_categories(data: OrderIn, db: DbSession, admin: AdminUser) -> None:
    svc.reorder(db, admin, "category", None, data.ids)


@router.put("/categories/{category_id}/specialisations/order", status_code=204)
def order_specialisations(category_id: uuid.UUID, data: OrderIn, db: DbSession, admin: AdminUser) -> None:
    svc.reorder(db, admin, "specialisation", category_id, data.ids)


# ---------------------------------------------------------------- specialisations


@router.post("/specialisations", status_code=201)
def create_specialisation(data: SpecialisationCreate, db: DbSession, admin: AdminUser) -> SpecialisationOut:
    return specialisation_out(svc.create_specialisation(db, admin, data))


@router.patch("/specialisations/{spec_id}")
def update_specialisation(
    spec_id: uuid.UUID, data: SpecialisationUpdate, db: DbSession, admin: AdminUser
) -> SpecialisationOut:
    _check_basis(
        db, data, lambda: catalogue_impact.change_for_update("specialisation", spec_id, data.changes())
    )
    return specialisation_out(svc.update_specialisation(db, admin, spec_id, data))


@router.post("/specialisations/{spec_id}/status")
def set_specialisation_status(
    spec_id: uuid.UUID, data: StatusChange, db: DbSession, admin: AdminUser
) -> SpecialisationOut:
    _check_basis(db, data, lambda: _status_change("specialisation", spec_id, data))
    return specialisation_out(
        svc.set_specialisation_status(db, admin, spec_id, data.status, data.reason, data.expected_version)
    )


@router.put("/specialisations/{spec_id}/qualifications")
def set_specialisation_requirements(
    spec_id: uuid.UUID, data: RequirementsIn, db: DbSession, admin: AdminUser
) -> SpecialisationOut:
    _check_basis(db, data, lambda: _requirements_change("specialisation", spec_id, data))
    return specialisation_out(
        svc.set_specialisation_requirements(db, admin, spec_id, data.qualification_ids, data.expected_version)
    )


@router.put("/specialisations/{spec_id}/services/order", status_code=204)
def order_services(spec_id: uuid.UUID, data: OrderIn, db: DbSession, admin: AdminUser) -> None:
    svc.reorder(db, admin, "service", spec_id, data.ids)


# ---------------------------------------------------------------- services


@router.post("/services", status_code=201)
def create_service(data: ServiceCreate, db: DbSession, admin: AdminUser) -> ServiceOut:
    return service_out(svc.create_service(db, admin, data))


@router.patch("/services/{service_id}")
def update_service(service_id: uuid.UUID, data: ServiceUpdate, db: DbSession, admin: AdminUser) -> ServiceOut:
    _check_basis(db, data, lambda: catalogue_impact.change_for_update("service", service_id, data.changes()))
    return service_out(svc.update_service(db, admin, service_id, data))


@router.post("/services/{service_id}/status")
def set_service_status(
    service_id: uuid.UUID, data: StatusChange, db: DbSession, admin: AdminUser
) -> ServiceOut:
    _check_basis(db, data, lambda: _status_change("service", service_id, data))
    return service_out(
        svc.set_service_status(db, admin, service_id, data.status, data.reason, data.expected_version)
    )


@router.post("/services/{service_id}/activate-hold")
def activate_hold(service_id: uuid.UUID, data: HoldActivation, db: DbSession, admin: AdminUser) -> ServiceOut:
    _check_basis(
        db,
        data,
        lambda: catalogue_impact.ProposedChange("service", service_id, "activate_hold", reason=data.reason),
    )
    return service_out(svc.activate_hold(db, admin, service_id, data.reason, data.expected_version))


@router.put("/services/{service_id}/qualifications")
def set_service_requirements(
    service_id: uuid.UUID, data: RequirementsIn, db: DbSession, admin: AdminUser
) -> ServiceOut:
    _check_basis(db, data, lambda: _requirements_change("service", service_id, data))
    return service_out(
        svc.set_service_requirements(db, admin, service_id, data.qualification_ids, data.expected_version)
    )


# ---------------------------------------------------------------- qualifications


@router.post("/qualifications", status_code=201)
def create_qualification(data: QualificationCreate, db: DbSession, admin: AdminUser) -> QualificationOut:
    return qualification_out(svc.create_qualification(db, admin, data))


@router.patch("/qualifications/{qualification_id}")
def update_qualification(
    qualification_id: uuid.UUID, data: QualificationUpdate, db: DbSession, admin: AdminUser
) -> QualificationOut:
    return qualification_out(svc.update_qualification(db, admin, qualification_id, data))


@router.post("/qualifications/{qualification_id}/status")
def set_qualification_status(
    qualification_id: uuid.UUID, data: QualificationStatusChange, db: DbSession, admin: AdminUser
) -> QualificationOut:
    return qualification_out(
        svc.set_qualification_status(
            db, admin, qualification_id, data.status, data.reason, data.expected_version
        )
    )


# ---------------------------------------------------------------- environment transfer


@router.get("/export")
def export_catalogue(db: DbSession, admin: AdminUser) -> dict[str, Any]:
    return sync.export_package(db, admin)


@router.post("/sync-imports", status_code=201)
def preview_import(
    package: Annotated[dict[str, Any], Body()], db: DbSession, admin: AdminUser
) -> SyncImportOut:
    return import_out(sync.preview(db, admin, package))


@router.get("/sync-imports/{import_id}")
def get_import(import_id: uuid.UUID, db: DbSession) -> SyncImportOut:
    return import_out(sync.get_import(db, import_id))


@router.post("/sync-imports/{import_id}/apply")
def apply_import(import_id: uuid.UUID, data: SyncApplyIn, db: DbSession, admin: AdminUser) -> SyncImportOut:
    return import_out(sync.apply(db, admin, import_id, data.apply_updates, data.keep_active))
