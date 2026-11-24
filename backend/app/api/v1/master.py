"""Master's own capabilities (R-MST-08..16, ARCHITECTURE §6b). Every route requires the master role and works
only on the caller's own master profile; other masters' IDs return 404."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.api.deps import DbSession, require_role
from app.core.business_time import business_today
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.integrations.storage import get_storage
from app.models import (
    Attachment,
    CatalogueSpecialisation,
    MasterCompetency,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.schemas.master import (
    AttachmentOut,
    CapabilitiesOut,
    CatalogueServiceOut,
    CatalogueSpecialisationOut,
    CompetencyDeclareIn,
    CompetencyOut,
    MasterCatalogueOut,
    QualificationRuleOut,
    SpecialisationApplicationOut,
    SpecialisationRequestIn,
    SubmissionOut,
)
from app.services import master_capabilities as svc
from app.services.uploads import validate_files

router = APIRouter(prefix="/master", tags=["master"])
MasterUser = Annotated[User, Depends(require_role("master"))]
EXTENSIONS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}


@router.get("/capabilities", response_model=CapabilitiesOut)
def get_capabilities(db: DbSession, user: MasterUser) -> CapabilitiesOut:
    data = svc.capabilities(db, user, get_settings().qualification_expiry_warning_days)
    master = data["master"]
    return CapabilitiesOut(
        approval_status=master.approval_status,
        # The reason of the last decision is shown only while it is a rejection.
        rejection_reason=master.decision_reason if master.approval_status == "rejected" else None,
        today=data["today"],
        specialisations=[_application(i["application"], i["name"]) for i in data["specialisations"]],
        competencies=[
            CompetencyOut(
                service_id=i["service"].id,
                w_id=i["service"].w_id,
                name=i["service"].name,
                specialisation_id=i["service"].specialisation_id,
                status=i["competency"].status,
                declared_at=i["competency"].declared_at,
                decided_at=i["competency"].decided_at,
                decision_reason=i["competency"].decision_reason,
                eligible=i["eligible"],
                reasons=i["reasons"],
            )
            for i in data["competencies"]
        ],
        qualifications=[
            _submission(i["submission"], i["name"], i["files"], i["expired"], i["expires_soon"])
            for i in data["qualifications"]
        ],
    )


@router.get("/catalogue", response_model=MasterCatalogueOut)
def get_catalogue(db: DbSession, _: MasterUser) -> MasterCatalogueOut:
    data = svc.master_catalogue(db)
    active = {q.id for q in data["qualification_types"]}
    return MasterCatalogueOut(
        specialisations=[
            CatalogueSpecialisationOut(
                id=spec.id,
                category_id=spec.category_id,
                name=spec.name,
                description=spec.description,
                status=spec.status,
                qualification_required=spec.qualification_required,
                qualification_ids=[q.id for q in spec.qualifications if q.id in active],
                services=[
                    CatalogueServiceOut(
                        id=s.id,
                        w_id=s.w_id,
                        name=s.name,
                        status=s.status,
                        qualification_required=s.qualification_required,
                        qualification_ids=[q.id for q in s.qualifications if q.id in active],
                    )
                    for s in services
                ],
            )
            for spec, services in data["specialisations"]
        ],
        qualification_types=[
            QualificationRuleOut.model_validate(q, from_attributes=True) for q in data["qualification_types"]
        ],
    )


def _application(row: MasterSpecialisation, name: str) -> SpecialisationApplicationOut:
    return SpecialisationApplicationOut(
        specialisation_id=row.specialisation_id,
        name=name,
        status=row.status,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        decision_reason=row.decision_reason,
    )


def _submission(
    row: MasterQualification, name: str, files: list[Attachment], expired: bool, expires_soon: bool
) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        qualification_id=row.qualification_id,
        qualification_name=name,
        status=row.status,
        document_number=row.document_number,
        valid_until=row.valid_until,
        submitted_at=row.submitted_at,
        decided_at=row.decided_at,
        decision_reason=row.decision_reason,
        expired=expired,
        expires_soon=expires_soon,
        files=[AttachmentOut.model_validate(f, from_attributes=True) for f in files],
    )


@router.post(
    "/specialisations", status_code=status.HTTP_201_CREATED, response_model=SpecialisationApplicationOut
)
def request_specialisation(
    db: DbSession, user: MasterUser, body: SpecialisationRequestIn
) -> SpecialisationApplicationOut:
    row = svc.request_specialisation(db, user, body.specialisation_id)
    return _application(row, _spec_name(db, row))


@router.post("/specialisations/{specialisation_id}/withdraw", response_model=SpecialisationApplicationOut)
def withdraw_specialisation(
    db: DbSession, user: MasterUser, specialisation_id: uuid.UUID
) -> SpecialisationApplicationOut:
    row = svc.withdraw_specialisation(db, user, specialisation_id)
    return _application(row, _spec_name(db, row))


def _spec_name(db: DbSession, row: MasterSpecialisation) -> str:
    spec = db.get(CatalogueSpecialisation, row.specialisation_id)
    assert spec is not None
    return spec.name


@router.post("/competencies", status_code=status.HTTP_201_CREATED, response_model=dict[str, str])
def declare_competency(db: DbSession, user: MasterUser, body: CompetencyDeclareIn) -> dict[str, str]:
    return _competency(svc.declare_competency(db, user, body.service_id))


@router.post("/competencies/{service_id}/withdraw", response_model=dict[str, str])
def withdraw_competency(db: DbSession, user: MasterUser, service_id: uuid.UUID) -> dict[str, str]:
    return _competency(svc.withdraw_competency(db, user, service_id))


def _competency(row: MasterCompetency) -> dict[str, str]:
    # Eligibility and reasons are read from GET /capabilities, the one place that evaluates them.
    return {"service_id": str(row.service_id), "status": row.status}


@router.post(
    "/qualifications",
    status_code=status.HTTP_201_CREATED,
    response_model=SubmissionOut,
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload"))],
)
def submit_qualification(
    db: DbSession,
    user: MasterUser,
    qualification_id: Annotated[uuid.UUID, Form()],
    document_number: Annotated[str | None, Form(max_length=100)] = None,
    valid_until: Annotated[date | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> SubmissionOut:
    """Multipart: the files are uploaded only here, together with the submission they belong to."""
    valid = validate_files(files or [])
    number = (document_number or "").strip() or None
    data = svc.SubmissionIn(qualification_id, number, valid_until)
    row = svc.submit_qualification(db, get_storage(), user, data, valid)
    return _submission_out(db, row)


@router.post("/qualifications/{submission_id}/withdraw", response_model=SubmissionOut)
def withdraw_qualification(db: DbSession, user: MasterUser, submission_id: uuid.UUID) -> SubmissionOut:
    return _submission_out(db, svc.withdraw_qualification(db, user, submission_id))


def _submission_out(db: DbSession, row: MasterQualification) -> SubmissionOut:
    qualification = db.get(Qualification, row.qualification_id)
    assert qualification is not None
    flags = svc.expiry_flags(row, business_today(db), get_settings().qualification_expiry_warning_days)
    files = svc.attachments_of(db, [row.id])[row.id]
    return _submission(row, qualification.name, files, flags["expired"], flags["expires_soon"])


@router.get("/qualifications/{submission_id}/files/{file_id}", response_class=Response)
def get_file(
    db: DbSession,
    user: MasterUser,
    submission_id: uuid.UUID,
    file_id: uuid.UUID,
    mode: Annotated[Literal["view", "download"], Query()] = "download",
) -> StreamingResponse:
    submission, attachment = svc.own_attachment(db, user, submission_id, file_id)
    return file_response(db, user, submission, attachment, mode)


def file_response(
    db: DbSession, actor: User, submission: MasterQualification, attachment: Attachment, mode: str
) -> StreamingResponse:
    """Stream a stored file after the caller's access check; shared with the admin API (step 4.4)."""
    try:
        handle = get_storage().open(attachment.storage_key)
    except FileNotFoundError as exc:
        # The row exists but the object is gone (storage incident): nothing is served or logged as read.
        raise AppError("FILE_UNAVAILABLE", "The file is not available.", status.HTTP_404_NOT_FOUND) from exc
    try:
        svc.log_file_access(db, actor, submission, attachment, mode)
    except BaseException:
        handle.close()  # nothing is served without its log entry; do not leak the open file
        raise
    name = f"{attachment.id}.{EXTENSIONS.get(attachment.mime_type, 'bin')}"
    headers = {
        "Content-Disposition": f'{"inline" if mode == "view" else "attachment"}; filename="{name}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store, private",
        "Content-Length": str(attachment.size_bytes),
    }
    if mode == "view":
        # Inline content can never run scripts or reach the API with the viewer's session.
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
    return StreamingResponse(handle, media_type=attachment.mime_type, headers=headers)
