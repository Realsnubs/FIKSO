"""Master API I/O (ARCHITECTURE §6b). Storage keys, hashes and verifier instructions are never exposed."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.catalogue import QualificationStatus, ServiceStatus

SpecialisationApplicationStatus = Literal["requested", "approved", "rejected", "revoked", "withdrawn"]
CompetencyStatus = Literal["declared", "verified", "rejected", "revoked", "withdrawn"]
SubmissionStatus = Literal["submitted", "verified", "rejected", "revoked", "withdrawn"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecialisationRequestIn(_In):
    specialisation_id: uuid.UUID


class CompetencyDeclareIn(_In):
    service_id: uuid.UUID


class ReasonOut(BaseModel):
    code: str
    details: dict[str, Any]


class SpecialisationApplicationOut(BaseModel):
    specialisation_id: uuid.UUID
    name: str
    status: SpecialisationApplicationStatus
    requested_at: datetime
    decided_at: datetime | None
    decision_reason: str | None


class CompetencyOut(BaseModel):
    service_id: uuid.UUID
    w_id: str
    name: str
    specialisation_id: uuid.UUID
    status: CompetencyStatus
    declared_at: datetime
    decided_at: datetime | None
    decision_reason: str | None
    eligible: bool
    reasons: list[ReasonOut]


class AttachmentOut(BaseModel):
    id: uuid.UUID
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


class SubmissionOut(BaseModel):
    id: uuid.UUID
    qualification_id: uuid.UUID
    qualification_name: str
    status: SubmissionStatus
    document_number: str | None
    valid_until: date | None
    submitted_at: datetime
    decided_at: datetime | None
    decision_reason: str | None
    expired: bool
    expires_soon: bool
    files: list[AttachmentOut]


class CapabilitiesOut(BaseModel):
    approval_status: Literal["pending_approval", "approved", "rejected"]
    rejection_reason: str | None
    today: date
    specialisations: list[SpecialisationApplicationOut]
    competencies: list[CompetencyOut]
    qualifications: list[SubmissionOut]


class QualificationRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: QualificationStatus
    requires_document: bool
    requires_document_number: bool
    requires_expiry_date: bool
    max_validity_months: int | None


class CatalogueServiceOut(BaseModel):
    id: uuid.UUID
    w_id: str
    name: str
    status: ServiceStatus
    qualification_required: bool
    qualification_ids: list[uuid.UUID]


class CatalogueSpecialisationOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str | None
    status: Literal["active", "planned"]
    qualification_required: bool
    qualification_ids: list[uuid.UUID]
    services: list[CatalogueServiceOut]


class MasterCatalogueOut(BaseModel):
    specialisations: list[CatalogueSpecialisationOut]
    qualification_types: list[QualificationRuleOut]
