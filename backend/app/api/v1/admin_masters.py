"""Admin views of masters and the review queue (ARCHITECTURE §6b, step 4.4.2). Read-only; role admin."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.api.deps import AdminUser, DbSession
from app.api.v1.master import file_response
from app.core.config import get_settings
from app.schemas.admin_masters import (
    AdminCompetencyOut,
    AdminMasterListItemOut,
    AdminMasterOut,
    AdminQualificationRuleOut,
    AdminSpecialisationOut,
    AdminSubmissionOut,
    ApproveIn,
    BulkPreviewItemOut,
    BulkPreviewOut,
    BulkVerifyIn,
    BulkVerifyPreviewIn,
    PendingCountsOut,
    ProfileApproveIn,
    ProfileRejectIn,
    ReasonedDecisionIn,
    ReviewQueueItemOut,
)
from app.schemas.common import Page
from app.schemas.master import AttachmentOut
from app.services import master_admin

router = APIRouter(prefix="/admin", tags=["admin"])
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/masters")
def list_masters(
    db: DbSession,
    _: AdminUser,
    approval_status: Literal["pending_approval", "approved", "rejected"] | None = None,
    has_pending: bool | None = None,
    limit: Limit = 25,
    cursor: str | None = None,
) -> Page[AdminMasterListItemOut]:
    items, next_cursor = master_admin.list_masters(db, approval_status, has_pending, limit, cursor)
    return Page(items=[_list_item(i) for i in items], next_cursor=next_cursor)


def _list_item(item: dict[str, Any]) -> AdminMasterListItemOut:
    master, user, pending = item["master"], item["user"], item["pending"]
    return AdminMasterListItemOut(
        id=master.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        user_status=user.status,
        approval_status=master.approval_status,
        decided_at=master.decided_at,
        version=master.version,
        registered_at=master.created_at,
        pending=PendingCountsOut(
            specialisations=pending["specialisation"],
            competencies=pending["competency"],
            qualifications=pending["qualification"],
        ),
    )


@router.get("/masters/{master_id}")
def get_master(db: DbSession, _: AdminUser, master_id: uuid.UUID) -> AdminMasterOut:
    data = master_admin.master_detail(db, master_id, get_settings().qualification_expiry_warning_days)
    master, user = data["master"], data["user"]
    return AdminMasterOut(
        id=master.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        user_status=user.status,
        blocked_reason=user.blocked_reason,
        approval_status=master.approval_status,
        decided_by=master.decided_by,
        decided_at=master.decided_at,
        decision_reason=master.decision_reason,
        version=master.version,
        registered_at=master.created_at,
        today=data["today"],
        specialisations=[
            AdminSpecialisationOut(
                specialisation_id=i["application"].specialisation_id,
                name=i["name"],
                status=i["application"].status,
                requested_at=i["application"].requested_at,
                decided_at=i["application"].decided_at,
                decided_by=i["application"].decided_by,
                decision_reason=i["application"].decision_reason,
                version=i["application"].version,
            )
            for i in data["specialisations"]
        ],
        competencies=[
            AdminCompetencyOut(
                service_id=i["service"].id,
                w_id=i["service"].w_id,
                name=i["service"].name,
                specialisation_id=i["service"].specialisation_id,
                status=i["competency"].status,
                declared_at=i["competency"].declared_at,
                decided_at=i["competency"].decided_at,
                decided_by=i["competency"].decided_by,
                decision_reason=i["competency"].decision_reason,
                version=i["competency"].version,
                eligible=i["eligible"],
                reasons=i["reasons"],
            )
            for i in data["competencies"]
        ],
        qualifications=[
            AdminSubmissionOut(
                id=i["submission"].id,
                qualification_id=i["submission"].qualification_id,
                qualification_name=i["name"],
                status=i["submission"].status,
                document_number=i["submission"].document_number,
                valid_until=i["submission"].valid_until,
                submitted_at=i["submission"].submitted_at,
                decided_at=i["submission"].decided_at,
                decided_by=i["submission"].decided_by,
                decision_reason=i["submission"].decision_reason,
                version=i["submission"].version,
                expired=i["expired"],
                expires_soon=i["expires_soon"],
                files=[AttachmentOut.model_validate(f, from_attributes=True) for f in i["files"]],
            )
            for i in data["qualifications"]
        ],
        qualification_types=[
            AdminQualificationRuleOut.model_validate(q, from_attributes=True)
            for q in data["qualification_types"]
        ],
    )


@router.post("/masters/{master_id}/approve")
def approve_master(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, body: ProfileApproveIn
) -> AdminMasterOut:
    master_admin.decide_profile(db, admin, master_id, master_admin.Decision("approve", body.expected_version))
    return get_master(db, admin, master_id)


@router.post("/masters/{master_id}/reject")
def reject_master(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, body: ProfileRejectIn
) -> AdminMasterOut:
    decision = master_admin.Decision("reject", body.expected_version, body.reason)
    master_admin.decide_profile(db, admin, master_id, decision)
    return get_master(db, admin, master_id)


SPECIALISATION = "/masters/{master_id}/specialisations/{specialisation_id}"


@router.post(f"{SPECIALISATION}/approve")
def approve_specialisation(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, specialisation_id: uuid.UUID, body: ApproveIn
) -> AdminMasterOut:
    decision = master_admin.Decision("approve", body.expected_version)
    master_admin.decide_specialisation(db, admin, master_id, specialisation_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{SPECIALISATION}/reject")
def reject_specialisation(
    db: DbSession,
    admin: AdminUser,
    master_id: uuid.UUID,
    specialisation_id: uuid.UUID,
    body: ReasonedDecisionIn,
) -> AdminMasterOut:
    decision = master_admin.Decision("reject", body.expected_version, body.reason)
    master_admin.decide_specialisation(db, admin, master_id, specialisation_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{SPECIALISATION}/revoke")
def revoke_specialisation(
    db: DbSession,
    admin: AdminUser,
    master_id: uuid.UUID,
    specialisation_id: uuid.UUID,
    body: ReasonedDecisionIn,
) -> AdminMasterOut:
    decision = master_admin.Decision("revoke", body.expected_version, body.reason)
    master_admin.decide_specialisation(db, admin, master_id, specialisation_id, decision)
    return get_master(db, admin, master_id)


# Bulk verification (step 4.4.8): preview first, then apply all or nothing.
@router.post("/masters/{master_id}/competencies/bulk-verify/preview")
def bulk_verify_preview(
    db: DbSession, _: AdminUser, master_id: uuid.UUID, body: BulkVerifyPreviewIn
) -> BulkPreviewOut:
    data = master_admin.bulk_verify_preview(db, master_id, body.service_ids)
    return BulkPreviewOut(
        items=[BulkPreviewItemOut(**i) for i in data["items"]], applicable=data["applicable"]
    )


@router.post("/masters/{master_id}/competencies/bulk-verify")
def bulk_verify(db: DbSession, admin: AdminUser, master_id: uuid.UUID, body: BulkVerifyIn) -> AdminMasterOut:
    items = [(item.service_id, item.expected_version) for item in body.items]
    master_admin.bulk_verify(db, admin, master_id, items)
    return get_master(db, admin, master_id)


COMPETENCY = "/masters/{master_id}/competencies/{service_id}"


@router.post(f"{COMPETENCY}/verify")
def verify_competency(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, service_id: uuid.UUID, body: ApproveIn
) -> AdminMasterOut:
    decision = master_admin.Decision("verify", body.expected_version)
    master_admin.decide_competency(db, admin, master_id, service_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{COMPETENCY}/reject")
def reject_competency(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, service_id: uuid.UUID, body: ReasonedDecisionIn
) -> AdminMasterOut:
    decision = master_admin.Decision("reject", body.expected_version, body.reason)
    master_admin.decide_competency(db, admin, master_id, service_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{COMPETENCY}/revoke")
def revoke_competency(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, service_id: uuid.UUID, body: ReasonedDecisionIn
) -> AdminMasterOut:
    decision = master_admin.Decision("revoke", body.expected_version, body.reason)
    master_admin.decide_competency(db, admin, master_id, service_id, decision)
    return get_master(db, admin, master_id)


QUALIFICATION = "/masters/{master_id}/qualifications/{submission_id}"


@router.post(f"{QUALIFICATION}/verify")
def verify_qualification(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, submission_id: uuid.UUID, body: ApproveIn
) -> AdminMasterOut:
    """Verified exactly as submitted: no document fields are accepted (owner decision 2026-11-02)."""
    decision = master_admin.Decision("verify", body.expected_version)
    master_admin.decide_qualification(db, admin, master_id, submission_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{QUALIFICATION}/reject")
def reject_qualification(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, submission_id: uuid.UUID, body: ReasonedDecisionIn
) -> AdminMasterOut:
    decision = master_admin.Decision("reject", body.expected_version, body.reason)
    master_admin.decide_qualification(db, admin, master_id, submission_id, decision)
    return get_master(db, admin, master_id)


@router.post(f"{QUALIFICATION}/revoke")
def revoke_qualification(
    db: DbSession, admin: AdminUser, master_id: uuid.UUID, submission_id: uuid.UUID, body: ReasonedDecisionIn
) -> AdminMasterOut:
    decision = master_admin.Decision("revoke", body.expected_version, body.reason)
    master_admin.decide_qualification(db, admin, master_id, submission_id, decision)
    return get_master(db, admin, master_id)


@router.get("/review-queue")
def review_queue(
    db: DbSession,
    _: AdminUser,
    kind: Literal["specialisation", "competency", "qualification"] | None = None,
    limit: Limit = 25,
    cursor: str | None = None,
) -> Page[ReviewQueueItemOut]:
    items, next_cursor = master_admin.review_queue(db, kind, limit, cursor)
    return Page(items=[ReviewQueueItemOut(**i) for i in items], next_cursor=next_cursor)


@router.get("/masters/{master_id}/qualifications/{submission_id}/files/{file_id}", response_class=Response)
def get_file(
    db: DbSession,
    admin: AdminUser,
    master_id: uuid.UUID,
    submission_id: uuid.UUID,
    file_id: uuid.UUID,
    mode: Annotated[Literal["view", "download"], Query()] = "download",
) -> StreamingResponse:
    """Streamed only through this authorised route (no public or pre-signed links); every access is logged."""
    submission, attachment = master_admin.master_attachment(db, master_id, submission_id, file_id)
    return file_response(db, admin, submission, attachment, mode)
