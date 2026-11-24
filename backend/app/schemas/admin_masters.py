"""Admin master API I/O (ARCHITECTURE §6b). Adds what a verifier needs to the master's own view (versions,
deciders, verifier instructions); storage keys and file hashes are never exposed."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator

from app.schemas.master import (
    CompetencyOut,
    QualificationRuleOut,
    ReasonOut,
    SpecialisationApplicationOut,
    SubmissionOut,
)

ApprovalStatus = Literal["pending_approval", "approved", "rejected"]
UserStatus = Literal["active", "blocked"]


class PendingCountsOut(BaseModel):
    specialisations: int
    competencies: int
    qualifications: int


class AdminMasterListItemOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    phone: str | None
    user_status: UserStatus
    approval_status: ApprovalStatus
    decided_at: datetime | None
    version: int
    registered_at: datetime
    pending: PendingCountsOut


class _Decided(BaseModel):
    decided_by: uuid.UUID | None
    version: int


class AdminSpecialisationOut(SpecialisationApplicationOut, _Decided):
    pass


class AdminCompetencyOut(CompetencyOut, _Decided):
    pass


class AdminSubmissionOut(SubmissionOut, _Decided):
    pass


class AdminQualificationRuleOut(QualificationRuleOut):
    verifier_instructions: str | None


class AdminMasterOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    phone: str | None
    user_status: UserStatus
    blocked_reason: str | None
    approval_status: ApprovalStatus
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    version: int
    registered_at: datetime
    today: date
    specialisations: list[AdminSpecialisationOut]
    competencies: list[AdminCompetencyOut]
    qualifications: list[AdminSubmissionOut]
    qualification_types: list[AdminQualificationRuleOut]


class ReviewQueueItemOut(BaseModel):
    kind: Literal["specialisation", "competency", "qualification"]
    master_id: uuid.UUID
    master_name: str
    approval_status: ApprovalStatus
    user_status: UserStatus
    item_id: uuid.UUID
    name: str
    w_id: str | None
    valid_until: date | None
    since: datetime
    version: int


class _DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The version the admin saw (from the detail or the review queue); a stale one → 409 VERSION_CONFLICT.
    expected_version: Annotated[int, Field(ge=1)]


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ProfileApproveIn(_DecisionIn):
    pass


class ProfileRejectIn(_DecisionIn):
    reason: Reason


class ApproveIn(_DecisionIn):
    """Approval takes no reason."""


class ReasonedDecisionIn(_DecisionIn):
    reason: Reason


BULK_VERIFY_MAX = 50  # = master_admin.BULK_VERIFY_MAX


def _unique(values: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(set(values)) != len(values):
        raise ValueError("each service may be listed once")
    return values


class BulkVerifyPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=BULK_VERIFY_MAX)]

    @field_validator("service_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _unique(value)


class BulkVerifyItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: uuid.UUID
    expected_version: Annotated[int, Field(ge=1)]


class BulkVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[BulkVerifyItemIn], Field(min_length=1, max_length=BULK_VERIFY_MAX)]
    # Explicitly the JSON value true: false, a missing value, 1 or "true" are refused.
    confirm: StrictBool

    @field_validator("confirm")
    @classmethod
    def confirmed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm must be true")
        return value

    @field_validator("items")
    @classmethod
    def unique_items(cls, value: list[BulkVerifyItemIn]) -> list[BulkVerifyItemIn]:
        _unique([item.service_id for item in value])
        return value


class BulkPreviewItemOut(BaseModel):
    service_id: uuid.UUID
    w_id: str | None
    name: str | None
    status: Literal["declared", "verified", "rejected", "revoked", "withdrawn"] | None
    expected_version: int | None
    verifiable: bool
    reasons: list[ReasonOut]


class BulkPreviewOut(BaseModel):
    items: list[BulkPreviewItemOut]
    applicable: bool
