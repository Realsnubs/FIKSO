"""Master eligibility for a service (R-MST-11) and the reasons when it fails (R-MST-12).

This module is the only definition of the rule. Admin views, the catalogue's `eligible_masters` count and
later matching all use `eligible()` as a SQL condition; `explain()` builds its reasons from the same
expressions, so the explanation can never disagree with the decision. A master is eligible for a service only
when all hold:

- the user is active (not blocked, not deleted) and the master profile is `approved`;
- the master's specialisation for the service's specialisation is `approved`;
- the master's competency for the service is `verified` (a `declared` one never counts);
- a regulated service (`qualification_required` on the service or its specialisation) has at least one
  effective qualification requirement configured;
- every effective required qualification (the service's own ∪ its specialisation's) is an `active` type and
  the master holds a `verified` submission whose `valid_until` is empty or today or later (inclusive,
  Europe/Riga).

Revocation or expiry excludes the master at once; competency rows are never rewritten for it. Availability,
work zone and commission limit are not part of this rule; matching adds them (R-MATCH-02).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fastapi import status
from sqlalchemy import SQLColumnExpression, and_, func, literal, or_, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.business_time import business_today, business_today_sql
from app.core.errors import AppError
from app.models import (
    CatalogueService,
    CatalogueSpecialisation,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications, specialisation_qualifications

type Id = uuid.UUID | SQLColumnExpression[uuid.UUID]
type Day = date | SQLColumnExpression[date]

# Reason codes, in the order they are reported.
USER_NOT_ACTIVE = "USER_NOT_ACTIVE"
PROFILE_NOT_APPROVED = "PROFILE_NOT_APPROVED"
SPECIALISATION_NOT_APPROVED = "SPECIALISATION_NOT_APPROVED"
COMPETENCY_NOT_VERIFIED = "COMPETENCY_NOT_VERIFIED"
QUALIFICATION_NOT_CONFIGURED = "QUALIFICATION_NOT_CONFIGURED"
QUALIFICATION_TYPE_NOT_ACTIVE = "QUALIFICATION_TYPE_NOT_ACTIVE"
QUALIFICATION_EXPIRED = "QUALIFICATION_EXPIRED"
QUALIFICATION_REVOKED = "QUALIFICATION_REVOKED"
QUALIFICATION_MISSING = "QUALIFICATION_MISSING"


@dataclass(frozen=True)
class Reason:
    code: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Eligibility:
    master_id: uuid.UUID
    service_id: uuid.UUID
    reasons: tuple[Reason, ...]

    @property
    def eligible(self) -> bool:
        return not self.reasons


# Building blocks. Each subquery uses its own aliases and lists them in `_exists`, so it can be embedded in
# any outer query: an outer `MasterProfile.id` or `CatalogueService.id` passed as an argument is correlated,
# never re-joined.


def _exists(own: tuple[Any, ...], *where: ColumnElement[bool]) -> ColumnElement[bool]:
    # Explicit correlation: everything except the subquery's own aliases belongs to an enclosing query, at
    # any depth. Auto-correlation looks only one level up and silently re-joins e.g. master_profiles two
    # levels down, which turns "this master holds the qualification" into "some master holds it".
    return select(literal(1)).select_from(*own).where(*where).correlate_except(*own).exists()


def _user_active(master_id: Id) -> ColumnElement[bool]:
    mp, user = aliased(MasterProfile), aliased(User)
    return _exists(
        (mp, user),
        mp.id == master_id,
        user.id == mp.user_id,
        user.status == "active",
        user.deleted_at.is_(None),
    )


def _profile_approved(master_id: Id) -> ColumnElement[bool]:
    mp = aliased(MasterProfile)
    return _exists((mp,), mp.id == master_id, mp.approval_status == "approved")


def _specialisation_approved(master_id: Id, service_id: Id) -> ColumnElement[bool]:
    service, ms = aliased(CatalogueService), aliased(MasterSpecialisation)
    return _exists(
        (service, ms),
        service.id == service_id,
        ms.master_id == master_id,
        ms.specialisation_id == service.specialisation_id,
        ms.status == "approved",
    )


def _competency_verified(master_id: Id, service_id: Id) -> ColumnElement[bool]:
    mc = aliased(MasterCompetency)
    return _exists((mc,), mc.master_id == master_id, mc.service_id == service_id, mc.status == "verified")


def _required(qualification: Any, service_id: Id) -> ColumnElement[bool]:
    """The qualification is an effective requirement of the service (own ∪ its specialisation's)."""
    sq, spq = service_qualifications.alias(), specialisation_qualifications.alias()
    service = aliased(CatalogueService)
    return or_(
        _exists((sq,), sq.c.qualification_id == qualification.id, sq.c.service_id == service_id),
        _exists(
            (spq, service),
            spq.c.qualification_id == qualification.id,
            spq.c.specialisation_id == service.specialisation_id,
            service.id == service_id,
        ),
    )


def _type_active(qualification: Any) -> ColumnElement[bool]:
    return qualification.status == "active"  # type: ignore[no-any-return]


def _held(qualification: Any, master_id: Id, today: Day) -> ColumnElement[bool]:
    """A verified submission that is unexpired: `valid_until` is inclusive."""
    mq = aliased(MasterQualification)
    return _exists(
        (mq,),
        mq.master_id == master_id,
        mq.qualification_id == qualification.id,
        mq.status == "verified",
        or_(mq.valid_until.is_(None), mq.valid_until >= today),
    )


def _qualifications_configured(service_id: Id) -> ColumnElement[bool]:
    """A regulated service (own or specialisation flag) needs ≥1 configured requirement (owner, 2026-11-02).

    Without it the qualification check would pass vacuously; a regulated service never admits anyone that way.
    """
    service, spec, q = aliased(CatalogueService), aliased(CatalogueSpecialisation), aliased(Qualification)
    regulated = _exists(
        (service, spec),
        service.id == service_id,
        spec.id == service.specialisation_id,
        or_(service.qualification_required, spec.qualification_required),
    )
    return or_(~regulated, _exists((q,), _required(q, service_id)))


def _qualifications_met(master_id: Id, service_id: Id, today: Day) -> ColumnElement[bool]:
    q = aliased(Qualification)
    return ~_exists((q,), _required(q, service_id), ~and_(_type_active(q), _held(q, master_id, today)))


def _conditions(master_id: Id, service_id: Id, today: Day) -> dict[str, ColumnElement[bool]]:
    return {
        "user_active": _user_active(master_id),
        "profile_approved": _profile_approved(master_id),
        "specialisation_approved": _specialisation_approved(master_id, service_id),
        "competency_verified": _competency_verified(master_id, service_id),
        "qualifications_configured": _qualifications_configured(service_id),
        "qualifications_met": _qualifications_met(master_id, service_id, today),
    }


def eligible(master_id: Id, service_id: Id, today: Day | None = None) -> ColumnElement[bool]:
    """R-MST-11 as one SQL condition. `today` defaults to the transaction's business date (Europe/Riga)."""
    day = business_today_sql() if today is None else today
    return and_(*_conditions(master_id, service_id, day).values())


def required_qualification_ids(db: Session, service_id: uuid.UUID) -> list[uuid.UUID]:
    """The service's effective qualification requirements (own ∪ its specialisation's), any type status."""
    q = aliased(Qualification)
    return list(db.scalars(select(q.id).where(_required(q, service_id)).order_by(q.id)))


def eligible_master_ids(db: Session, service_id: uuid.UUID, today: date | None = None) -> list[uuid.UUID]:
    query = (
        select(MasterProfile.id)
        .where(eligible(MasterProfile.id, service_id, today))
        .order_by(MasterProfile.id)
    )
    return list(db.scalars(query))


def eligible_counts(
    db: Session, service_ids: Sequence[uuid.UUID] | None = None, today: date | None = None
) -> dict[uuid.UUID, int]:
    """Eligible masters per service (R-CAT-03 capacity), one grouped query over `eligible()` itself.

    Every listed service (all services when `service_ids` is None) is in the result, with 0 when nobody is
    eligible. Unknown IDs are left out. Nothing is stored: the count is always computed from current rows.
    """
    day = business_today_sql() if today is None else today
    query = (
        select(CatalogueService.id, func.count(MasterProfile.id))
        .select_from(CatalogueService)
        .outerjoin(MasterProfile, eligible(MasterProfile.id, CatalogueService.id, day))
        .group_by(CatalogueService.id)
    )
    if service_ids is not None:
        query = query.where(CatalogueService.id.in_(service_ids))
    return {service_id: count for service_id, count in db.execute(query).tuples()}


def eligible_pairs(
    db: Session, service_ids: Sequence[uuid.UUID], today: date | None = None
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """(master, service) pairs that pass `eligible()` for the listed services, in one query."""
    if not service_ids:
        return set()
    day = business_today_sql() if today is None else today
    query = (
        select(MasterProfile.id, CatalogueService.id)
        .select_from(MasterProfile)
        .join(CatalogueService, CatalogueService.id.in_(service_ids))
        .where(eligible(MasterProfile.id, CatalogueService.id, day))
    )
    return {(master_id, service_id) for master_id, service_id in db.execute(query).tuples()}


def explain(
    db: Session, service_id: uuid.UUID, master_ids: list[uuid.UUID], today: date | None = None
) -> dict[uuid.UUID, Eligibility]:
    """Eligibility of each listed master for the service, with every failing condition as a reason.

    Unknown master IDs are left out; callers check ownership before asking.
    """
    service = db.get(CatalogueService, service_id)
    if service is None:
        raise AppError("SERVICE_NOT_FOUND", "Catalogue service not found.", status.HTTP_404_NOT_FOUND)
    day = business_today(db) if today is None else today
    reasons: dict[uuid.UUID, list[Reason]] = {}

    ms, mc = aliased(MasterSpecialisation), aliased(MasterCompetency)
    conditions = _conditions(MasterProfile.id, service_id, day)
    masters = db.execute(
        select(
            MasterProfile.id,
            User.status,
            User.deleted_at,
            MasterProfile.approval_status,
            ms.status,
            mc.status,
            *(condition.label(name) for name, condition in conditions.items()),
        )
        .join(User, User.id == MasterProfile.user_id)
        .outerjoin(
            ms, and_(ms.master_id == MasterProfile.id, ms.specialisation_id == service.specialisation_id)
        )
        .outerjoin(mc, and_(mc.master_id == MasterProfile.id, mc.service_id == service_id))
        .where(MasterProfile.id.in_(master_ids))
    ).all()
    for row in masters:
        found = reasons[row[0]] = []
        if not row.user_active:
            found.append(Reason(USER_NOT_ACTIVE, {"status": row[1], "deleted": row[2] is not None}))
        if not row.profile_approved:
            found.append(Reason(PROFILE_NOT_APPROVED, {"approval_status": row[3]}))
        if not row.specialisation_approved:
            found.append(
                Reason(
                    SPECIALISATION_NOT_APPROVED,
                    {"specialisation_id": str(service.specialisation_id), "status": row[4]},
                )
            )
        if not row.competency_verified:
            found.append(Reason(COMPETENCY_NOT_VERIFIED, {"service_id": str(service_id), "status": row[5]}))
        if not row.qualifications_configured:
            found.append(Reason(QUALIFICATION_NOT_CONFIGURED, {"service_id": str(service_id)}))

    q, mq = Qualification, aliased(MasterQualification)
    verified_until = (
        select(mq.valid_until)
        .where(mq.master_id == MasterProfile.id, mq.qualification_id == q.id, mq.status == "verified")
        # After renewals several verified rows exist; report the latest end date.
        .order_by(mq.valid_until.desc().nulls_first())
        .limit(1)
        .scalar_subquery()
    )
    latest = aliased(MasterQualification)
    latest_status = (
        select(latest.status)
        .where(latest.master_id == MasterProfile.id, latest.qualification_id == q.id)
        .order_by(latest.submitted_at.desc(), latest.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    requirements = db.execute(
        select(
            MasterProfile.id,
            q.id,
            q.name,
            q.status,
            _type_active(q).label("type_active"),
            _held(q, MasterProfile.id, day).label("held"),
            verified_until.label("verified_until"),
            latest_status.label("latest_status"),
        )
        # Each listed master against each effective requirement of the service.
        .select_from(MasterProfile)
        .join(q, true())
        .where(MasterProfile.id.in_(master_ids), _required(q, service_id))
        .order_by(q.name, q.id)
    ).all()
    for req in requirements:
        about = {"qualification_id": str(req[1]), "name": req[2]}
        found = reasons[req[0]]
        if not req.type_active:
            found.append(Reason(QUALIFICATION_TYPE_NOT_ACTIVE, about | {"type_status": req[3]}))
        if req.held:
            continue
        if req.verified_until is not None:
            # A verified submission that is not held can only be past its inclusive end date.
            found.append(
                Reason(QUALIFICATION_EXPIRED, about | {"valid_until": req.verified_until.isoformat()})
            )
        elif req.latest_status == "revoked":
            found.append(Reason(QUALIFICATION_REVOKED, about))
        else:
            found.append(Reason(QUALIFICATION_MISSING, about | {"latest_status": req.latest_status}))

    result = {}
    for row in masters:
        result[row[0]] = Eligibility(row[0], service_id, tuple(reasons[row[0]]))
        # The decision comes from the shared conditions; the reasons only describe it. They must agree.
        if result[row[0]].eligible != all(getattr(row, name) for name in conditions):
            raise RuntimeError("eligibility reasons disagree with the eligibility rule")
    return result
