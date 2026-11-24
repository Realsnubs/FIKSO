"""Admin decisions on masters and their capabilities (R-AUTH-03, R-MST-08..16, ARCHITECTURE §6b, step 4.4).

Every decision takes one path: lock the master row (the same lock the master's own writes take, so decisions,
withdrawals and submissions of one master run one at a time), check the version the admin saw and the allowed
transition, record decider, time and reason, bump the version, and write `audit_log` + `domain_events` with
the full state before and after, in one transaction. A repeated or stale decision fails with 409 and changes
nothing.

Owner decisions 2026-11-02: `rejected` and `revoked` are final for a row (a new review starts only with the
master's re-application); a profile is approved from `pending_approval` or `rejected` and rejected only from
`pending_approval` (an approved master is restricted by blocking the user); a qualification is verified
exactly as submitted. Eligibility is never stored: it follows from these rows at query time
(services/eligibility.py).
"""

import base64
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import status
from sqlalchemy import ColumnElement, Text, and_, func, literal, not_, or_, select, tuple_, union_all
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.errors import AppError
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
from app.services.master_capabilities import (
    NOT_DECLARABLE_SERVICES,
    REQUESTABLE_SPECIALISATIONS,
    capability_view,
    log_change,
    snapshot,
    submission_attachment,
)

Kind = Literal["profile", "specialisation", "competency", "qualification"]
Action = Literal["approve", "reject", "revoke", "verify"]
Row = MasterProfile | MasterSpecialisation | MasterCompetency | MasterQualification
Precondition = Callable[[MasterProfile, Row], None]

RESULT: dict[str, str] = {
    "approve": "approved",
    "reject": "rejected",
    "revoke": "revoked",
    "verify": "verified",
}
# Allowed source statuses per kind and action; anything else is INVALID_TRANSITION.
TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "profile": {"approve": ("pending_approval", "rejected"), "reject": ("pending_approval",)},
    "specialisation": {"approve": ("requested",), "reject": ("requested",), "revoke": ("approved",)},
    "competency": {"verify": ("declared",), "reject": ("declared",), "revoke": ("verified",)},
    "qualification": {"verify": ("submitted",), "reject": ("submitted",), "revoke": ("verified",)},
}
# Required reasons: ARCHITECTURE §6b; specialisation (step 4.4.5) and competency (step 4.4.6) reject/revoke by
# owner decision 2026-11-02. Approvals and verifications take none (enforced by the API schemas).
REASON_REQUIRED = {
    ("profile", "reject"),
    ("specialisation", "reject"),
    ("specialisation", "revoke"),
    ("competency", "reject"),
    ("competency", "revoke"),
    ("qualification", "reject"),
    ("qualification", "revoke"),
}
ENTITY_TYPE = {
    "profile": "master_profile",
    "specialisation": "master_specialisation",
    "competency": "master_competency",
    "qualification": "master_qualification",
}


@dataclass(frozen=True)
class Decision:
    action: Action
    expected_version: int
    reason: str | None = None


def lock_master(db: Session, master_id: uuid.UUID) -> MasterProfile:
    # Deleted accounts are not shown to admins (owner decision 2026-11-02), so they are not decided on either.
    master = db.scalar(
        select(MasterProfile)
        .join(User, User.id == MasterProfile.user_id)
        .where(MasterProfile.id == master_id, User.deleted_at.is_(None))
        .with_for_update(of=MasterProfile)
    )
    if master is None:
        raise AppError("MASTER_NOT_FOUND", "Master not found.", status.HTTP_404_NOT_FOUND)
    return master


def _row(db: Session, master: MasterProfile, kind: Kind, key: uuid.UUID | None) -> Row:
    row: Row | None
    if kind == "profile":
        row = master
    elif kind == "specialisation":
        row = db.get(MasterSpecialisation, (master.id, key))
    elif kind == "competency":
        row = db.get(MasterCompetency, (master.id, key))
    else:
        found = db.get(MasterQualification, key)
        # A submission of another master is reported exactly like an unknown one.
        row = found if found is not None and found.master_id == master.id else None
    if row is None:
        raise AppError(
            f"{kind.upper()}_NOT_FOUND", f"{kind.capitalize()} not found.", status.HTTP_404_NOT_FOUND
        )
    return row


def _status(row: Row) -> str:
    return row.approval_status if isinstance(row, MasterProfile) else row.status


def _guard(admin: User, master: MasterProfile) -> None:
    # Roles are exclusive, so an admin is never a master; kept as a guard should that ever change.
    if admin.role != "admin" or admin.id == master.user_id:
        raise AppError(
            "DECISION_FORBIDDEN", "This user cannot decide on this master.", status.HTTP_403_FORBIDDEN
        )


def _check(kind: Kind, row: Row, decision: Decision) -> str | None:
    """Version, transition and reason checks of one decision; returns the trimmed reason."""
    current = _status(row)
    if row.version != decision.expected_version:
        raise AppError(
            "VERSION_CONFLICT",
            "The record changed since it was loaded.",
            status.HTTP_409_CONFLICT,
            {"status": current, "version": row.version},
        )
    if current not in TRANSITIONS[kind].get(decision.action, ()):
        raise AppError(
            "INVALID_TRANSITION",
            f"Cannot {decision.action} a {kind} that is {current}.",
            status.HTTP_409_CONFLICT,
            {"status": current, "version": row.version, "action": decision.action},
        )
    reason = (decision.reason or "").strip() or None
    if (kind, decision.action) in REASON_REQUIRED and reason is None:
        raise AppError(
            "REASON_REQUIRED",
            "A reason is required for this decision.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return reason


def _apply(
    db: Session, admin: User, master: MasterProfile, kind: Kind, row: Row, action: Action, reason: str | None
) -> None:
    """Record one decision with its audit entry and event; the caller commits (or rolls back) once."""
    before = snapshot(row)
    new_status = RESULT[action]
    if isinstance(row, MasterProfile):
        row.approval_status = new_status
    else:
        row.status = new_status
    row.decided_by = admin.id
    row.decided_at = datetime.now(UTC)
    row.decision_reason = reason
    row.version += 1
    db.flush()
    entity_id = row.id if isinstance(row, MasterQualification) else master.id
    log_change(db, admin, f"{kind}.{new_status}", ENTITY_TYPE[kind], entity_id, before, snapshot(row), reason)


def decide(
    db: Session,
    admin: User,
    master_id: uuid.UUID,
    kind: Kind,
    key: uuid.UUID | None,
    decision: Decision,
    precondition: Precondition | None = None,
) -> Row:
    """Apply one admin decision; `precondition` adds the kind-specific checks (eligibility) under the lock."""
    master = lock_master(db, master_id)
    _guard(admin, master)
    row = _row(db, master, kind, key)
    reason = _check(kind, row, decision)
    if precondition is not None:
        precondition(master, row)
    _apply(db, admin, master, kind, row, decision.action, reason)
    db.commit()
    return row


def decide_profile(db: Session, admin: User, master_id: uuid.UUID, decision: Decision) -> MasterProfile:
    """Approve or reject a master profile (R-AUTH-03, step 4.4.4).

    Blocking is separate: a blocked user stays blocked whatever the profile decision (users.set_blocked),
    and eligibility requires both (R-MST-11). Approval clears the reason, so an earlier rejection reason is
    never shown as current; it stays in the audit trail.
    """
    row = decide(db, admin, master_id, "profile", None, decision)
    assert isinstance(row, MasterProfile)
    return row


def decide_specialisation(
    db: Session, admin: User, master_id: uuid.UUID, specialisation_id: uuid.UUID, decision: Decision
) -> MasterSpecialisation:
    """Approve, reject or revoke a master's specialisation (R-MST-08, step 4.4.5).

    The row is keyed by master and catalogue specialisation. Approval needs the catalogue entry still
    requestable (`active`/`planned`, like the master's request); it changes nothing else: competencies and
    qualifications keep their own decisions (R-MST-14). Revocation excludes the master at once through
    eligibility without touching competency rows (R-MST-11).
    """

    def still_available(master: MasterProfile, row: Row) -> None:
        if decision.action != "approve":
            return
        spec = db.get(CatalogueSpecialisation, specialisation_id)
        if spec is None or spec.status not in REQUESTABLE_SPECIALISATIONS:
            raise AppError(
                "SPECIALISATION_NOT_AVAILABLE",
                "This specialisation is no longer offered in the catalogue.",
                status.HTTP_409_CONFLICT,
                {"catalogue_status": spec.status if spec else None},
            )

    row = decide(db, admin, master_id, "specialisation", specialisation_id, decision, still_available)
    assert isinstance(row, MasterSpecialisation)
    return row


# Eligibility conditions that do not block a verification: the user's block status is separate (R-AUTH-05,
# eligibility still requires an active user) and the competency itself is what is being verified.
NOT_VERIFICATION_BLOCKERS = {eligibility.USER_NOT_ACTIVE, eligibility.COMPETENCY_NOT_VERIFIED}


def verification_blockers(
    db: Session, master_id: uuid.UUID, service_id: uuid.UUID
) -> list[eligibility.Reason]:
    """Why a competency cannot be verified now (R-MST-09/11/14, owner decision 2026-11-02 for step 4.4.6).

    Service availability first (the master's declaration rule), then the shared eligibility reasons
    (`eligibility.explain`, Riga business date): profile and specialisation approved, requirements
    configured (`QUALIFICATION_NOT_CONFIGURED`), every required qualification type active and held
    verified and unexpired.
    """
    service = db.get(CatalogueService, service_id)
    if service is None or service.status in NOT_DECLARABLE_SERVICES:
        status_ = service.status if service else None
        return [eligibility.Reason("SERVICE_NOT_AVAILABLE", {"catalogue_status": status_})]
    result = eligibility.explain(db, service_id, [master_id])[master_id]
    return [reason for reason in result.reasons if reason.code not in NOT_VERIFICATION_BLOCKERS]


def decide_competency(
    db: Session, admin: User, master_id: uuid.UUID, service_id: uuid.UUID, decision: Decision
) -> MasterCompetency:
    """Verify, reject or revoke a master's competency for one service (R-MST-14, step 4.4.6).

    The row is keyed by master and catalogue service. Verification runs the blockers under the master row
    lock, so a concurrent revocation of a qualification or specialisation is seen, never raced. Revocation
    changes only this row; eligibility excludes the master at once.
    """

    def verifiable(master: MasterProfile, row: Row) -> None:
        if decision.action != "verify":
            return
        blockers = verification_blockers(db, master.id, service_id)
        if blockers:
            raise AppError(
                blockers[0].code,
                "The competency cannot be verified yet.",
                status.HTTP_409_CONFLICT,
                {"reasons": [{"code": r.code, "details": r.details} for r in blockers]},
            )

    row = decide(db, admin, master_id, "competency", service_id, decision, verifiable)
    assert isinstance(row, MasterCompetency)
    return row


def decide_qualification(
    db: Session, admin: User, master_id: uuid.UUID, submission_id: uuid.UUID, decision: Decision
) -> MasterQualification:
    """Verify, reject or revoke one qualification submission (R-MST-09/15/16, step 4.4.7).

    Each submission is its own row (renewal = new row), so a decision never touches another submission, and
    the document data and files stay exactly as the master submitted them (owner decision 2026-11-02; wrong
    data → reject, the master submits again). Verification is refused for an inactive qualification type or an
    already expired document (Riga date, `valid_until` inclusive), so expiry is never "verified away".
    Eligibility follows from the rows at query time (services/eligibility.py).
    """

    def verifiable(master: MasterProfile, row: Row) -> None:
        if decision.action != "verify":
            return
        assert isinstance(row, MasterQualification)
        qualification = db.get(Qualification, row.qualification_id)
        assert qualification is not None
        reasons: list[eligibility.Reason] = []
        if qualification.status != "active":
            reasons.append(
                eligibility.Reason(
                    eligibility.QUALIFICATION_TYPE_NOT_ACTIVE,
                    {"qualification_id": str(qualification.id), "status": qualification.status},
                )
            )
        if row.valid_until is not None and row.valid_until < business_today(db):
            reasons.append(
                eligibility.Reason(
                    eligibility.QUALIFICATION_EXPIRED, {"valid_until": row.valid_until.isoformat()}
                )
            )
        if reasons:
            raise AppError(
                reasons[0].code,
                "The qualification cannot be verified.",
                status.HTTP_409_CONFLICT,
                {"reasons": [{"code": r.code, "details": r.details} for r in reasons]},
            )

    row = decide(db, admin, master_id, "qualification", submission_id, decision, verifiable)
    assert isinstance(row, MasterQualification)
    return row


# --- bulk competency verification (step 4.4.8) --------------------------------------------------------------
# R-MST-14 / Q-28 / owner decisions 2026-11-02: only explicitly selected, declared competencies of one master,
# only for non-regulated services, after a preview; all or nothing; one audit entry and one event each.

BULK_VERIFY_MAX = 50  # one master's selection; larger sets are split by the admin (ARCHITECTURE §6b)


def _bulk_selection(service_ids: list[uuid.UUID]) -> None:
    """The API schemas enforce this too; the service repeats it so no caller can bypass it (e.g. a duplicate
    item would otherwise be decided twice)."""
    if not 1 <= len(service_ids) <= BULK_VERIFY_MAX or len(set(service_ids)) != len(service_ids):
        raise AppError(
            "BULK_VERIFY_INVALID",
            f"Select 1 to {BULK_VERIFY_MAX} different competencies.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"max_items": BULK_VERIFY_MAX},
        )


def _regulation(db: Session, service_id: uuid.UUID) -> eligibility.Reason | None:
    """Regulated = a `qualification_required` flag on the service or its specialisation, or any effective
    qualification requirement (eligibility's own rule). Such competencies are verified one by one."""
    service = db.get(CatalogueService, service_id)
    if service is None:
        return None  # reported as SERVICE_NOT_AVAILABLE by the verification blockers
    spec = db.get(CatalogueSpecialisation, service.specialisation_id)
    assert spec is not None
    required = eligibility.required_qualification_ids(db, service_id)
    if not (service.qualification_required or spec.qualification_required or required):
        return None
    return eligibility.Reason(
        "REGULATED_SERVICE",
        {
            "service_qualification_required": service.qualification_required,
            "specialisation_qualification_required": spec.qualification_required,
            "required_qualifications": len(required),
        },
    )


def _bulk_item(
    db: Session,
    master: MasterProfile,
    service_id: uuid.UUID,
    row: MasterCompetency | None,
    version: int | None,
) -> list[dict[str, Any]]:
    """Every reason one selected competency cannot be bulk-verified (empty = it can)."""
    if row is None:
        return [{"code": "COMPETENCY_NOT_FOUND", "details": {}}]
    reasons: list[dict[str, Any]] = []
    try:
        _check("competency", row, Decision("verify", row.version if version is None else version))
    except AppError as exc:
        reasons.append({"code": exc.code, "details": exc.details})
    regulated = _regulation(db, service_id)
    if regulated is not None:
        reasons.append({"code": regulated.code, "details": regulated.details})
    reasons += [
        {"code": r.code, "details": r.details} for r in verification_blockers(db, master.id, service_id)
    ]
    return reasons


def bulk_verify_preview(db: Session, master_id: uuid.UUID, service_ids: list[uuid.UUID]) -> dict[str, Any]:
    """What a bulk verification of exactly these competencies would do. Reads only; writes nothing."""
    _bulk_selection(service_ids)
    found = db.execute(
        select(MasterProfile)
        .join(User, User.id == MasterProfile.user_id)
        .where(MasterProfile.id == master_id, User.deleted_at.is_(None))
    ).scalar_one_or_none()
    if found is None:
        raise AppError("MASTER_NOT_FOUND", "Master not found.", status.HTTP_404_NOT_FOUND)
    items = []
    for service_id in service_ids:
        row = db.get(MasterCompetency, (master_id, service_id))
        service = db.get(CatalogueService, service_id) if row is not None else None
        reasons = _bulk_item(db, found, service_id, row, None)
        items.append(
            {
                "service_id": service_id,
                "w_id": service.w_id if service else None,
                "name": service.name if service else None,
                "status": row.status if row else None,
                "expected_version": row.version if row else None,
                "verifiable": not reasons,
                "reasons": reasons,
            }
        )
    db.rollback()  # nothing was written; end the read transaction
    return {"items": items, "applicable": all(i["verifiable"] for i in items)}


def bulk_verify(
    db: Session, admin: User, master_id: uuid.UUID, items: list[tuple[uuid.UUID, int]]
) -> list[MasterCompetency]:
    """Verify all listed competencies in one transaction, or none.

    Lock order: the master row, then the selected competency rows sorted by service ID (stable order, so two
    bulk operations never deadlock). Every condition is re-checked under these locks; one failing item fails
    the whole request (409 BULK_VERIFY_REJECTED with every failing item) and nothing is written. Any error
    while writing rolls back every decision of the request.
    """
    _bulk_selection([service_id for service_id, _ in items])
    master = lock_master(db, master_id)
    _guard(admin, master)
    wanted = sorted(items)
    rows = {
        row.service_id: row
        for row in db.scalars(
            select(MasterCompetency)
            .where(
                MasterCompetency.master_id == master.id,
                MasterCompetency.service_id.in_([service_id for service_id, _ in wanted]),
            )
            .order_by(MasterCompetency.service_id)
            .with_for_update()
        )
    }
    failures = []
    for service_id, version in wanted:
        reasons = _bulk_item(db, master, service_id, rows.get(service_id), version)
        if reasons:
            failures.append({"service_id": str(service_id), "reasons": reasons})
    if failures:
        db.rollback()
        raise AppError(
            "BULK_VERIFY_REJECTED",
            "No competency was verified: every selected item must pass.",
            status.HTTP_409_CONFLICT,
            {"items": failures},
        )
    try:
        for service_id, _ in wanted:
            _apply(db, admin, master, "competency", rows[service_id], "verify", None)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return [rows[service_id] for service_id, _ in wanted]


# --- admin read models (step 4.4.2) -------------------------------------------------------------------------
# Reads write nothing to audit_log; only document views/downloads are logged (R-MST-15).

QueueKind = Literal["specialisation", "competency", "qualification"]
_PENDING: dict[str, tuple[Any, str, Any, Any]] = {
    # kind: (model, pending status, item key column, "waiting since" column)
    "specialisation": (
        MasterSpecialisation,
        "requested",
        MasterSpecialisation.specialisation_id,
        MasterSpecialisation.requested_at,
    ),
    "competency": (MasterCompetency, "declared", MasterCompetency.service_id, MasterCompetency.declared_at),
    "qualification": (
        MasterQualification,
        "submitted",
        MasterQualification.id,
        MasterQualification.submitted_at,
    ),
}


def _encode_cursor(*parts: object) -> str:
    text = "|".join(p.isoformat() if isinstance(p, datetime) else str(p) for p in parts)
    return base64.urlsafe_b64encode(text.encode()).decode()


def _decode_cursor(cursor: str, parts: int) -> list[str]:
    try:
        values = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("INVALID_CURSOR", "Invalid pagination cursor.") from exc
    if len(values) != parts:
        raise AppError("INVALID_CURSOR", "Invalid pagination cursor.")
    return values


def _parse[T](parse: Callable[[str], T], value: str) -> T:
    try:
        return parse(value)
    except ValueError as exc:
        raise AppError("INVALID_CURSOR", "Invalid pagination cursor.") from exc


def _pending_count(kind: str) -> ColumnElement[int]:
    model, pending, _, _ = _PENDING[kind]
    return (
        select(func.count())
        .select_from(model)
        .where(model.master_id == MasterProfile.id, model.status == pending)
        .correlate(MasterProfile)
        .scalar_subquery()
    )


def list_masters(
    db: Session, approval_status: str | None, has_pending: bool | None, limit: int, cursor: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Masters newest first, with the number of items waiting for a decision (ARCHITECTURE §6b)."""
    counts = {kind: _pending_count(kind) for kind in _PENDING}
    query = (
        select(MasterProfile, User, *(count.label(kind) for kind, count in counts.items()))
        .join(User, User.id == MasterProfile.user_id)
        .where(User.deleted_at.is_(None))
    )
    if approval_status:
        query = query.where(MasterProfile.approval_status == approval_status)
    if has_pending is not None:
        any_pending = or_(*(count > 0 for count in counts.values()))
        query = query.where(any_pending if has_pending else not_(any_pending))
    if cursor:
        created, master_id = _decode_cursor(cursor, 2)
        at, key = _parse(datetime.fromisoformat, created), _parse(uuid.UUID, master_id)
        query = query.where(
            or_(MasterProfile.created_at < at, and_(MasterProfile.created_at == at, MasterProfile.id < key))
        )
    rows = db.execute(
        query.order_by(MasterProfile.created_at.desc(), MasterProfile.id.desc()).limit(limit + 1)
    ).all()
    items = [
        {"master": row[0], "user": row[1], "pending": {kind: getattr(row, kind) for kind in _PENDING}}
        for row in rows[:limit]
    ]
    last = rows[limit - 1][0] if len(rows) > limit else None
    return items, _encode_cursor(last.created_at, last.id) if last else None


def master_detail(db: Session, master_id: uuid.UUID, warning_days: int) -> dict[str, Any]:
    """What an admin needs to decide: all rows incl. history, eligibility reasons, expiry flags, rules."""
    found = db.execute(
        select(MasterProfile, User)
        .join(User, User.id == MasterProfile.user_id)
        .where(MasterProfile.id == master_id, User.deleted_at.is_(None))
    ).first()
    if found is None:
        raise AppError("MASTER_NOT_FOUND", "Master not found.", status.HTTP_404_NOT_FOUND)
    master, user = found
    view = capability_view(db, master, warning_days)
    type_ids = {item["submission"].qualification_id for item in view["qualifications"]}
    types = db.scalars(
        select(Qualification).where(Qualification.id.in_(type_ids)).order_by(Qualification.name)
    )
    return {**view, "user": user, "qualification_types": list(types)}


def review_queue(
    db: Session, kind: QueueKind | None, limit: int, cursor: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Items waiting for a decision across all masters, oldest first (ARCHITECTURE §6b)."""
    parts = [
        select(
            literal(name, Text).label("kind"),
            model.master_id.label("master_id"),
            key.label("item_id"),
            since.label("since"),
            model.version.label("version"),
        ).where(model.status == pending)
        for name, (model, pending, key, since) in _PENDING.items()
        if kind in (None, name)
    ]
    queue = union_all(*parts).subquery("queue")
    query = (
        select(queue, MasterProfile.approval_status, User.full_name, User.status)
        .join(MasterProfile, MasterProfile.id == queue.c.master_id)
        .join(User, User.id == MasterProfile.user_id)
        .where(User.deleted_at.is_(None))
    )
    if cursor:
        since, item_kind, item_id = _decode_cursor(cursor, 3)
        position = (_parse(datetime.fromisoformat, since), item_kind, _parse(uuid.UUID, item_id))
        query = query.where(tuple_(queue.c.since, queue.c.kind, queue.c.item_id) > tuple_(*position))
    rows = db.execute(query.order_by(queue.c.since, queue.c.kind, queue.c.item_id).limit(limit + 1)).all()
    page = rows[:limit]
    names = _queue_names(db, page)
    items = [
        {
            "kind": row.kind,
            "master_id": row.master_id,
            "master_name": row.full_name,
            "approval_status": row.approval_status,
            "user_status": row.status,
            "item_id": row.item_id,
            "since": row.since,
            "version": row.version,
            **names[(row.kind, row.item_id)],
        }
        for row in page
    ]
    last = rows[limit - 1] if len(rows) > limit else None
    return items, _encode_cursor(last.since, last.kind, last.item_id) if last else None


def _queue_names(db: Session, rows: Sequence[Any]) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    ids: dict[str, set[uuid.UUID]] = {name: set() for name in _PENDING}
    for row in rows:
        ids[row.kind].add(row.item_id)
    names: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}
    for spec in db.scalars(
        select(CatalogueSpecialisation).where(CatalogueSpecialisation.id.in_(ids["specialisation"]))
    ):
        names[("specialisation", spec.id)] = {"name": spec.name, "w_id": None, "valid_until": None}
    for service in db.scalars(select(CatalogueService).where(CatalogueService.id.in_(ids["competency"]))):
        names[("competency", service.id)] = {"name": service.name, "w_id": service.w_id, "valid_until": None}
    for submission, name in db.execute(
        select(MasterQualification, Qualification.name)
        .join(Qualification, Qualification.id == MasterQualification.qualification_id)
        .where(MasterQualification.id.in_(ids["qualification"]))
    ):
        names[("qualification", submission.id)] = {
            "name": name,
            "w_id": None,
            "valid_until": submission.valid_until,
        }
    return names


def master_attachment(
    db: Session, master_id: uuid.UUID, submission_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[MasterQualification, Attachment]:
    """An evidence file for an admin (R-MST-15, Q-27), resolved by master, submission, file and entity type
    together. Any mismatch (other master, other submission, other entity type, unknown ID) is the same 404, so
    nothing about other records is revealed."""
    found = db.execute(
        select(MasterQualification, User.id)
        .join(MasterProfile, MasterProfile.id == MasterQualification.master_id)
        .join(User, User.id == MasterProfile.user_id)
        .where(
            MasterQualification.id == submission_id,
            MasterQualification.master_id == master_id,
            User.deleted_at.is_(None),  # like the master detail: deleted accounts are not shown
        )
    ).first()
    not_found = AppError("FILE_NOT_FOUND", "File not found.", status.HTTP_404_NOT_FOUND)
    if found is None:
        raise not_found
    submission, owner_id = found
    try:
        attachment = submission_attachment(db, submission, attachment_id)  # checks entity type and binding
    except AppError as exc:
        raise not_found from exc
    if attachment.owner_user_id != owner_id:  # defence in depth: the binding is immutable (DB trigger)
        raise not_found
    return submission, attachment
