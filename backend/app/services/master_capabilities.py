"""A master's own specialisation requests, competencies and qualification submissions (R-MST-08..16).

Every function takes the authenticated master user and only ever touches that user's master profile; IDs of
other masters' records resolve to 404 (no existence leak). Rows are never deleted: re-applications move a row
back to `requested`/`declared` and keep the last decision fields, and every change is written to `audit_log`
and `domain_events` with the state before and after (R-MST-16). Nothing here grants eligibility; admins
decide (step 4.4).
"""

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.errors import AppError
from app.integrations.storage import Storage
from app.models import (
    Attachment,
    CatalogueService,
    CatalogueSpecialisation,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.services import eligibility
from app.services.events import record_audit, record_event
from app.services.uploads import ValidFile, store_attachments

REQUESTABLE_SPECIALISATIONS = ("active", "planned")
NOT_DECLARABLE_SERVICES = ("draft", "rejected", "archived")
# Owner decision (OPEN_QUESTIONS "Master withdrawals"): a master withdraws only undecided items; approved or
# verified items change only by an admin decision.
WITHDRAWABLE = {
    "specialisation": ("requested",),
    "competency": ("declared",),
    "qualification": ("submitted",),
}


def _not_found(kind: str) -> AppError:
    return AppError(f"{kind.upper()}_NOT_FOUND", f"{kind.capitalize()} not found.", status.HTTP_404_NOT_FOUND)


def _conflict(code: str, message: str, details: dict[str, Any] | None = None) -> AppError:
    return AppError(code, message, status.HTTP_409_CONFLICT, details)


def get_master(db: Session, user: User, *, lock: bool = False) -> MasterProfile:
    query = select(MasterProfile).where(MasterProfile.user_id == user.id)
    if lock:
        # Serialises all writes of one master, so checks and inserts see a consistent state.
        query = query.with_for_update()
    master = db.scalar(query)
    if master is None:
        raise _not_found("master_profile")
    return master


def _writable_master(db: Session, user: User) -> MasterProfile:
    master = get_master(db, user, lock=True)
    # Owner decision (OPEN_QUESTIONS "Rejected master profile"): Q-25 allows applications while pending; a
    # rejected profile is read-only (no applications, submissions or withdrawals) until approved again.
    if master.approval_status == "rejected":
        raise _conflict("MASTER_PROFILE_REJECTED", "A rejected master profile is read-only.")
    return master


def log_change(
    db: Session,
    user: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    reason: str | None = None,
) -> None:
    """Audit entry with the full state before and after; the event leaves out free-text reasons."""
    record_audit(db, f"master.{action}", entity_type, entity_id, "user", user.id, before, after, reason)
    payload = {key: value for key, value in after.items() if key != "decision_reason"}
    record_event(db, f"master.{action}", entity_type, entity_id, "user", user.id, payload)


def snapshot(
    row: MasterProfile | MasterSpecialisation | MasterCompetency | MasterQualification,
) -> dict[str, Any]:
    """Full decision state of a row, so every earlier decision stays readable in audit_log (R-MST-16)."""
    data: dict[str, Any] = {
        "decided_by": str(row.decided_by) if row.decided_by else None,
        # Always UTC, whichever zone the session returned it in, so equal instants log identically.
        "decided_at": row.decided_at.astimezone(UTC).isoformat() if row.decided_at else None,
        "decision_reason": row.decision_reason,
        "version": row.version,
    }
    if isinstance(row, MasterProfile):
        return {"master_id": str(row.id), "approval_status": row.approval_status, **data}
    data = {"master_id": str(row.master_id), "status": row.status, **data}
    if isinstance(row, MasterSpecialisation):
        data["specialisation_id"] = str(row.specialisation_id)
    elif isinstance(row, MasterCompetency):
        data["service_id"] = str(row.service_id)
    else:
        data["qualification_id"] = str(row.qualification_id)
        data["valid_until"] = row.valid_until.isoformat() if row.valid_until else None
        # Personal data: only the last 4 characters ever reach logs (DATABASE §3.3).
        data["document_number_last4"] = row.document_number[-4:] if row.document_number else None
    return data


def _reopen(row: MasterSpecialisation | MasterCompetency, new_status: str, kind: str) -> dict[str, Any]:
    """Move a decided/withdrawn row back to pending. Returns the state before, for the audit trail."""
    before = snapshot(row)
    if row.status in ("requested", "declared", "approved", "verified"):
        raise _conflict(f"{kind.upper()}_ALREADY_EXISTS", f"This {kind} is already requested or decided.")
    row.status = new_status
    row.version += 1
    return before


# --- specialisations ----------------------------------------------------------------------------------------


def request_specialisation(db: Session, user: User, specialisation_id: uuid.UUID) -> MasterSpecialisation:
    master = _writable_master(db, user)
    spec = db.get(CatalogueSpecialisation, specialisation_id)
    if spec is None:
        raise _not_found("specialisation")
    if spec.status not in REQUESTABLE_SPECIALISATIONS:
        raise _conflict("SPECIALISATION_NOT_AVAILABLE", "This specialisation cannot be requested.")
    row = db.get(MasterSpecialisation, (master.id, specialisation_id))
    before = None
    if row is None:
        row = MasterSpecialisation(
            master_id=master.id, specialisation_id=specialisation_id, status="requested"
        )
        db.add(row)
    else:
        before = _reopen(row, "requested", "specialisation")
        row.requested_at = datetime.now(UTC)
    db.flush()
    log_change(
        db, user, "specialisation.requested", "master_specialisation", master.id, before, snapshot(row)
    )
    db.commit()
    return row


def withdraw_specialisation(db: Session, user: User, specialisation_id: uuid.UUID) -> MasterSpecialisation:
    master = _writable_master(db, user)
    row = db.get(MasterSpecialisation, (master.id, specialisation_id))
    if row is None:
        raise _not_found("specialisation")
    return _withdraw(db, user, row, "specialisation", "master_specialisation", master.id)


# --- competencies -------------------------------------------------------------------------------------------


def declare_competency(db: Session, user: User, service_id: uuid.UUID) -> MasterCompetency:
    master = _writable_master(db, user)
    service = db.get(CatalogueService, service_id)
    if service is None:
        raise _not_found("service")
    if service.status in NOT_DECLARABLE_SERVICES:
        raise _conflict("SERVICE_NOT_AVAILABLE", "A competency cannot be declared for this service.")
    spec = db.get(MasterSpecialisation, (master.id, service.specialisation_id))
    if spec is None or spec.status not in ("requested", "approved"):
        raise _conflict(
            "SPECIALISATION_NOT_REQUESTED",
            "Request the service's specialisation first.",
            {"specialisation_id": str(service.specialisation_id)},
        )
    row = db.get(MasterCompetency, (master.id, service_id))
    before = None
    if row is None:
        row = MasterCompetency(master_id=master.id, service_id=service_id, status="declared")
        db.add(row)
    else:
        before = _reopen(row, "declared", "competency")
        row.declared_at = datetime.now(UTC)
    db.flush()
    log_change(db, user, "competency.declared", "master_competency", master.id, before, snapshot(row))
    db.commit()
    return row


def withdraw_competency(db: Session, user: User, service_id: uuid.UUID) -> MasterCompetency:
    master = _writable_master(db, user)
    row = db.get(MasterCompetency, (master.id, service_id))
    if row is None:
        raise _not_found("competency")
    return _withdraw(db, user, row, "competency", "master_competency", master.id)


def _withdraw[T: (MasterSpecialisation, MasterCompetency, MasterQualification)](
    db: Session, user: User, row: T, kind: str, entity_type: str, entity_id: uuid.UUID
) -> T:
    if row.status not in WITHDRAWABLE[kind]:
        raise _conflict(
            "CANNOT_WITHDRAW",
            "Only items still waiting for a decision can be withdrawn.",
            {"status": row.status},
        )
    before = snapshot(row)
    row.status = "withdrawn"
    row.version += 1
    db.flush()
    log_change(db, user, f"{kind}.withdrawn", entity_type, entity_id, before, snapshot(row))
    db.commit()
    return row


# --- qualifications -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmissionIn:
    qualification_id: uuid.UUID
    document_number: str | None
    valid_until: date | None


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _check_rules(
    qualification: Qualification, data: SubmissionIn, files: list[ValidFile], today: date
) -> None:
    """The qualification type's own rules (R-MST-09); the admin re-checks them when verifying."""
    if qualification.requires_document and not files:
        raise AppError("DOCUMENT_REQUIRED", "This qualification needs a document.")
    if qualification.requires_document_number and not data.document_number:
        raise AppError("DOCUMENT_NUMBER_REQUIRED", "This qualification needs the document number.")
    if qualification.requires_expiry_date and data.valid_until is None:
        raise AppError("EXPIRY_DATE_REQUIRED", "This qualification needs an expiry date.")
    if data.valid_until is not None:
        # Owner decision (OPEN_QUESTIONS "Submission checks"): no already expired documents.
        if data.valid_until < today:
            raise AppError("VALID_UNTIL_IN_PAST", "The document has already expired.")
        # Owner decision (OPEN_QUESTIONS "Submission checks"): maximum validity counted from today.
        months = qualification.max_validity_months
        if months is not None and data.valid_until > _add_months(today, months):
            raise AppError(
                "VALIDITY_TOO_LONG",
                "The expiry date is later than this qualification allows.",
                details={"max_validity_months": months},
            )


def submit_qualification(
    db: Session, storage: Storage, user: User, data: SubmissionIn, files: list[ValidFile]
) -> MasterQualification:
    """Create one submission with its files, atomically (R-MST-15, renewal decision 2026-11-02).

    Allowed when the master has no verified submission for the type, or every verified one has expired (Riga
    calendar). A valid verified submission blocks it; so does a pending one. Older rows are never changed.
    """
    master = _writable_master(db, user)  # row lock: concurrent submissions of this master wait here
    qualification = db.get(Qualification, data.qualification_id)
    if qualification is None:
        raise _not_found("qualification")
    # Owner decision (OPEN_QUESTIONS "Submission checks"): only configured (active) types accept submissions.
    if qualification.status != "active":
        raise _conflict(
            "QUALIFICATION_TYPE_NOT_ACTIVE", "This qualification type is not accepting submissions."
        )
    today = business_today(db)
    _check_rules(qualification, data, files, today)
    existing = db.scalars(
        select(MasterQualification).where(
            MasterQualification.master_id == master.id,
            MasterQualification.qualification_id == qualification.id,
            MasterQualification.status.in_(("submitted", "verified")),
        )
    ).all()
    if any(row.status == "submitted" for row in existing):
        raise _conflict("QUALIFICATION_SUBMISSION_PENDING", "A submission for this qualification is pending.")
    valid = [
        r for r in existing if r.status == "verified" and (r.valid_until is None or r.valid_until >= today)
    ]
    if valid:
        ends = [r.valid_until for r in valid]
        until = None if None in ends else max(e for e in ends if e is not None)
        raise _conflict(
            "QUALIFICATION_STILL_VALID",
            "The qualification is verified and still valid.",
            {"valid_until": until.isoformat() if until else None},
        )

    row = MasterQualification(
        master_id=master.id,
        qualification_id=qualification.id,
        status="submitted",
        document_number=data.document_number,
        valid_until=data.valid_until,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:  # the pending-submission index; unreachable while the lock is held
        db.rollback()
        raise _conflict("QUALIFICATION_SUBMISSION_PENDING", "A submission is pending.") from exc
    with store_attachments(
        db, storage, files, owner_user_id=user.id, entity_type="qualification", entity_id=row.id
    ) as attachments:
        db.flush()
        after = snapshot(row) | {
            "renewal": bool(existing),
            "attachments": [str(a.id) for a in attachments],
        }
        log_change(db, user, "qualification.submitted", "master_qualification", row.id, None, after)
        db.commit()
    return row


def _own_submission(db: Session, master: MasterProfile, submission_id: uuid.UUID) -> MasterQualification:
    row = db.get(MasterQualification, submission_id)
    if row is None or row.master_id != master.id:
        raise _not_found("submission")
    return row


def withdraw_qualification(db: Session, user: User, submission_id: uuid.UUID) -> MasterQualification:
    master = _writable_master(db, user)
    row = _own_submission(db, master, submission_id)
    return _withdraw(db, user, row, "qualification", "master_qualification", row.id)


# --- evidence files -----------------------------------------------------------------------------------------


def submission_attachment(
    db: Session, submission: MasterQualification, attachment_id: uuid.UUID
) -> Attachment:
    """The file only if it belongs to exactly this submission (R-MST-15: no ID swapping)."""
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.entity_type == "qualification",
            Attachment.entity_id == submission.id,
        )
    )
    if attachment is None:
        raise _not_found("file")
    return attachment


def own_attachment(
    db: Session, user: User, submission_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[MasterQualification, Attachment]:
    master = get_master(db, user)
    submission = _own_submission(db, master, submission_id)
    attachment = submission_attachment(db, submission, attachment_id)
    if attachment.owner_user_id != user.id:  # defence in depth: the binding is immutable (DB trigger)
        raise _not_found("file")
    return submission, attachment


def log_file_access(
    db: Session, actor: User, submission: MasterQualification, attachment: Attachment, mode: str
) -> None:
    """Q-27: every view/download is logged before the content is sent; no content or file data is logged."""
    action = "attachment.viewed" if mode == "view" else "attachment.downloaded"
    record_audit(
        db,
        action,
        "attachment",
        attachment.id,
        "user",
        actor.id,
        after={"submission_id": str(submission.id), "master_id": str(submission.master_id), "mode": mode},
    )
    db.commit()


def attachments_of(db: Session, submission_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Attachment]]:
    result: dict[uuid.UUID, list[Attachment]] = {i: [] for i in submission_ids}
    rows = db.scalars(
        select(Attachment)
        .where(Attachment.entity_type == "qualification", Attachment.entity_id.in_(submission_ids))
        .order_by(Attachment.uploaded_at, Attachment.id)
    )
    for row in rows:
        result[row.entity_id].append(row)
    return result


# --- read models --------------------------------------------------------------------------------------------


def expiry_flags(row: MasterQualification, today: date, warning_days: int) -> dict[str, bool]:
    """Q-29 UI warnings: `valid_until` is inclusive, so the last valid day is not yet expired."""
    if row.status != "verified" or row.valid_until is None:
        return {"expired": False, "expires_soon": False}
    expired = row.valid_until < today
    return {
        "expired": expired,
        "expires_soon": not expired and row.valid_until <= today + timedelta(warning_days),
    }


def capabilities(db: Session, user: User, warning_days: int) -> dict[str, Any]:
    """The master's own applications, eligibility reasons per competency (R-MST-12), expiry warnings."""
    return capability_view(db, get_master(db, user), warning_days)


def capability_view(db: Session, master: MasterProfile, warning_days: int) -> dict[str, Any]:
    """One read model for the master's own screen and the admin detail, so both show the same reasons."""
    today = business_today(db)
    specs = db.execute(
        select(MasterSpecialisation, CatalogueSpecialisation.name)
        .join(CatalogueSpecialisation, CatalogueSpecialisation.id == MasterSpecialisation.specialisation_id)
        .where(MasterSpecialisation.master_id == master.id)
        .order_by(CatalogueSpecialisation.name)
    ).all()
    competencies = db.execute(
        select(MasterCompetency, CatalogueService)
        .join(CatalogueService, CatalogueService.id == MasterCompetency.service_id)
        .where(MasterCompetency.master_id == master.id)
        .order_by(CatalogueService.w_id)
    ).all()
    submissions = db.execute(
        select(MasterQualification, Qualification.name)
        .join(Qualification, Qualification.id == MasterQualification.qualification_id)
        .where(MasterQualification.master_id == master.id)
        .order_by(Qualification.name, MasterQualification.submitted_at.desc())
    ).all()
    files = attachments_of(db, [row.id for row, _ in submissions])
    competency_out = []
    for row, service in competencies:
        result = eligibility.explain(db, service.id, [master.id], today)[master.id]
        competency_out.append(
            {
                "competency": row,
                "service": service,
                "eligible": result.eligible,
                "reasons": [{"code": r.code, "details": r.details} for r in result.reasons],
            }
        )
    return {
        "master": master,
        "today": today,
        "specialisations": [{"application": row, "name": name} for row, name in specs],
        "competencies": competency_out,
        "qualifications": [
            {
                "submission": row,
                "name": name,
                "files": files[row.id],
                **expiry_flags(row, today, warning_days),
            }
            for row, name in submissions
        ],
    }


def master_catalogue(db: Session) -> dict[str, Any]:
    """What a master may apply for: active/planned specialisations, declarable services, requirement rules.

    Only names and rules of active qualification types are shown; verifier instructions stay internal.
    """
    specs = db.scalars(
        select(CatalogueSpecialisation)
        .where(CatalogueSpecialisation.status.in_(REQUESTABLE_SPECIALISATIONS))
        .order_by(CatalogueSpecialisation.sort_order, CatalogueSpecialisation.name)
    ).all()
    services = db.scalars(
        select(CatalogueService)
        .where(
            CatalogueService.specialisation_id.in_([s.id for s in specs]),
            CatalogueService.status.not_in(NOT_DECLARABLE_SERVICES),
        )
        .order_by(CatalogueService.sort_order, CatalogueService.w_id)
    ).all()
    by_spec: dict[uuid.UUID, list[CatalogueService]] = {s.id: [] for s in specs}
    for service in services:
        by_spec[service.specialisation_id].append(service)
    types = db.scalars(
        select(Qualification).where(Qualification.status == "active").order_by(Qualification.name)
    )
    return {"specialisations": [(s, by_spec[s.id]) for s in specs], "qualification_types": list(types)}
