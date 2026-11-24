import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

GroupStatus = Literal["active", "inactive", "planned", "archived"]
ServiceStatus = Literal["draft", "active", "inactive", "planned", "hold", "rejected", "archived"]
QualificationStatus = Literal["draft", "active", "archived"]
RiskLevel = Literal["normal", "high"]
CatalogueRole = Literal["issuer", "receiver", "isolated"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class _In(BaseModel):
    # Unknown fields (e.g. "id", "w_id") are rejected, so identifiers can never be sent for change.
    model_config = ConfigDict(extra="forbid")


class _Patch(_In):
    """Partial update: only fields present in the body are applied; listed fields may not be null."""

    non_nullable: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _no_null_for_required(self) -> Self:
        for field in self.non_nullable:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.model_fields_set
            if field not in ("expected_version", "expected_basis")
        }


class _Versioned(BaseModel):
    """The entity version the admin saw; a stale one is refused with 409 VERSION_CONFLICT (step 4.5.3.1)."""

    expected_version: Annotated[int, Field(ge=1)]


class CategoryCreate(_In):
    name: Name
    description: Text | None = None
    # Entries never start active: activation goes through the status endpoint and its checks.
    status: Literal["inactive", "planned"] = "inactive"


class BasisItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["category", "specialisation", "service", "qualification"]
    id: uuid.UUID
    version: Annotated[int, Field(ge=1)]


class _Basis(BaseModel):
    """Optional: the `basis` of an impact preview (step 4.5.4.3). When sent, the change is applied only if
    every row the preview depended on is still there, nothing was added and every version is unchanged."""

    expected_basis: Annotated[list[BasisItemIn], Field(max_length=2000)] | None = None

    @model_validator(mode="after")
    def _unique_basis(self) -> Self:
        if self.expected_basis is not None:
            keys = [(item.kind, item.id) for item in self.expected_basis]
            if len(set(keys)) != len(keys):
                raise ValueError("expected_basis lists an entry twice")
        return self


class CategoryUpdate(_Versioned, _Patch):
    non_nullable = ("name",)
    name: Name | None = None
    description: Text | None = None


class SpecialisationCreate(_In):
    category_id: uuid.UUID
    name: Name
    description: Text | None = None
    status: Literal["inactive", "planned"] = "inactive"
    qualification_required: bool = False


class SpecialisationUpdate(_Versioned, _Basis, _Patch):
    non_nullable = ("name", "category_id", "qualification_required")
    name: Name | None = None
    description: Text | None = None
    category_id: uuid.UUID | None = None
    qualification_required: bool | None = None


class ServiceCreate(_In):
    specialisation_id: uuid.UUID
    name: Name
    description: Text | None = None
    status: Literal["draft", "inactive", "planned"] = "inactive"
    qualification_required: bool = False
    risk_level: RiskLevel = "normal"
    restrictions: Text | None = None


class ServiceUpdate(_Versioned, _Basis, _Patch):
    non_nullable = ("name", "specialisation_id", "qualification_required", "risk_level")
    name: Name | None = None
    description: Text | None = None
    specialisation_id: uuid.UUID | None = None
    qualification_required: bool | None = None
    risk_level: RiskLevel | None = None
    restrictions: Text | None = None
    review_note: Text | None = None


class StatusChange(_Versioned, _Basis, _In):
    status: str
    reason: Reason | None = None


class QualificationStatusChange(_Versioned, _In):
    """Kept apart from StatusChange so qualification types and catalogue entries can evolve separately."""

    status: str
    reason: Reason | None = None


class HoldActivation(_Versioned, _Basis, _In):
    confirm: Literal[True]
    reason: Reason


class OrderIn(_In):
    ids: list[uuid.UUID] = Field(min_length=1)


class RequirementsIn(_Versioned, _Basis, _In):
    qualification_ids: list[uuid.UUID]


class QualificationCreate(_In):
    name: Name
    description: Text | None = None
    requires_document: bool = True
    requires_document_number: bool = False
    requires_expiry_date: bool = False
    max_validity_months: Annotated[int, Field(ge=1, le=600)] | None = None
    verifier_instructions: Text | None = None


class QualificationUpdate(_Patch):
    non_nullable = ("name", "requires_document", "requires_document_number", "requires_expiry_date")
    name: Name | None = None
    description: Text | None = None
    requires_document: bool | None = None
    requires_document_number: bool | None = None
    requires_expiry_date: bool | None = None
    max_validity_months: Annotated[int, Field(ge=1, le=600)] | None = None
    verifier_instructions: Text | None = None


class _EntryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status_reason: str | None
    sort_order: int
    source: str
    source_ref: str | None
    version: int
    updated_at: datetime


class QualificationOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: QualificationStatus
    requires_document: bool
    requires_document_number: bool
    requires_expiry_date: bool
    max_validity_months: int | None
    verifier_instructions: str | None
    version: int
    updated_at: datetime


class ServiceOut(_EntryOut):
    specialisation_id: uuid.UUID
    w_id: str
    status: ServiceStatus
    risk_level: RiskLevel
    qualification_required: bool
    restrictions: str | None
    review_note: str | None
    qualification_ids: list[uuid.UUID]
    # False while a regulated service still lacks configured (active) qualifications (Q-21).
    qualifications_ready: bool


class SpecialisationOut(_EntryOut):
    category_id: uuid.UUID
    status: GroupStatus
    qualification_required: bool
    qualification_ids: list[uuid.UUID]
    services: list[ServiceOut]


class CategoryOut(_EntryOut):
    status: GroupStatus
    specialisations: list[SpecialisationOut]


class AvailabilityReasonOut(BaseModel):
    code: str
    details: dict[str, Any]


class TreeServiceOut(ServiceOut):
    # R-CAT-03 (step 4.5.2): computed from current rows on every read by `catalogue.availability`.
    eligible_masters: int
    orderable: bool
    orderable_reasons: list[AvailabilityReasonOut]


class TreeSpecialisationOut(SpecialisationOut):
    services: list[TreeServiceOut]  # type: ignore[assignment]


class TreeCategoryOut(CategoryOut):
    specialisations: list[TreeSpecialisationOut]  # type: ignore[assignment]


class CatalogueTreeOut(BaseModel):
    catalogue_role: CatalogueRole
    can_create: bool
    categories: list[TreeCategoryOut]
    qualifications: list[QualificationOut]


class SyncApplyIn(_In):
    confirm: Literal[True]
    apply_updates: list[uuid.UUID] = []
    keep_active: list[uuid.UUID] = []


class SyncImportOut(BaseModel):
    id: uuid.UUID
    status: Literal["previewed", "applied", "rejected"]
    source_environment: str
    exported_at: datetime
    package_sha256: str
    preview: dict[str, Any]
    created_at: datetime
    applied_at: datetime | None


# --- impact preview (R-CAT-18, step 4.5.4.2) ---------------------------------------------------------------


class _ImpactChange(_In):
    pass


class ImpactStatus(_ImpactChange):
    kind: Literal["status"]
    status: str
    reason: Reason | None = None


class ImpactMove(_ImpactChange):
    kind: Literal["move"]
    target_id: uuid.UUID  # the new category (specialisation) or specialisation (service)


class ImpactQualificationRequired(_ImpactChange):
    kind: Literal["qualification_required"]
    value: bool


class ImpactRequirements(_ImpactChange):
    kind: Literal["requirements"]
    qualification_ids: Annotated[list[uuid.UUID], Field(max_length=2000)]


class ImpactActivateHold(_ImpactChange):
    kind: Literal["activate_hold"]
    reason: Reason


ImpactChange = Annotated[
    ImpactStatus | ImpactMove | ImpactQualificationRequired | ImpactRequirements | ImpactActivateHold,
    Field(discriminator="kind"),
]


class ImpactIn(_In):
    entity: Literal["category", "specialisation", "service"]
    id: uuid.UUID
    change: ImpactChange


class BasisItemOut(BaseModel):
    kind: Literal["category", "specialisation", "service", "qualification"]
    id: uuid.UUID
    version: int


class ServiceStateOut(BaseModel):
    orderable: bool
    eligible_masters: int
    reasons: list[AvailabilityReasonOut]


class ImpactServiceOut(BaseModel):
    service_id: uuid.UUID
    w_id: str
    name: str
    before: ServiceStateOut
    after: ServiceStateOut


class MasterRefOut(BaseModel):
    # Identification only: no e-mail, phone or other contact data (owner decision 4).
    master_id: uuid.UUID
    full_name: str


class LosingEligibilityOut(BaseModel):
    total: int
    items: list[MasterRefOut]  # at most 100, ordered by name


class ImpactMastersOut(BaseModel):
    by_specialisation_status: dict[str, int]
    by_competency_status: dict[str, int]
    losing_eligibility: LosingEligibilityOut


class ImpactNotesOut(BaseModel):
    open_requests: str
    eligible_masters: str


class ImpactOut(BaseModel):
    entity: Literal["category", "specialisation", "service"]
    id: uuid.UUID
    change: ImpactChange
    basis: list[BasisItemOut]
    services: list[ImpactServiceOut]
    stops_being_orderable: list[uuid.UUID]
    becomes_orderable: list[uuid.UUID]
    masters: ImpactMastersOut
    open_requests: None  # counted once client requests exist (step 5)
    notes: ImpactNotesOut
    computed_at: datetime
