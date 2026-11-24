"""Public commercial terms (C1): append-only history, the newest row in force applies."""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import CommercialTerms, User
from app.schemas.commercial import CommercialTermsIn, CommercialTermsOut
from app.schemas.public import LocalizedText
from app.services.events import record_audit, record_event


def current(db: Session, at: datetime | None = None) -> CommercialTerms:
    at = at or datetime.now(UTC)
    terms = db.scalar(
        select(CommercialTerms)
        .where(CommercialTerms.effective_from <= at)
        .order_by(CommercialTerms.effective_from.desc(), CommercialTerms.created_at.desc())
        .limit(1)
    )
    if terms is None:
        raise AppError(
            "TERMS_NOT_CONFIGURED",
            "Commercial terms are not configured.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return terms


def materials_note(terms: CommercialTerms) -> LocalizedText:
    return LocalizedText.model_validate(terms.public_notes.get("materials") or {"lv": "-"})


def out(terms: CommercialTerms) -> CommercialTermsOut:
    return CommercialTermsOut(
        id=terms.id,
        hourly_rate_eur=terms.hourly_rate_eur,
        minimum_order_eur=terms.minimum_order_eur,
        materials_note=materials_note(terms),
        effective_from=terms.effective_from,
        reason=terms.reason,
        created_at=terms.created_at,
    )


def history(db: Session) -> list[CommercialTerms]:
    return list(db.scalars(select(CommercialTerms).order_by(CommercialTerms.effective_from.desc())).all())


def create(db: Session, admin: User, data: CommercialTermsIn) -> CommercialTerms:
    """A change is a new row in force from now; earlier rows and the requests that point at them stay
    as they are."""
    terms = CommercialTerms(
        hourly_rate_eur=data.hourly_rate_eur,
        minimum_order_eur=data.minimum_order_eur,
        public_notes={"materials": data.materials_note.model_dump(exclude_none=True)},
        effective_from=datetime.now(UTC),
        reason=data.reason,
        created_by=admin.id,
    )
    db.add(terms)
    db.flush()
    after = {"hourly_rate_eur": str(terms.hourly_rate_eur), "minimum_order_eur": str(terms.minimum_order_eur)}
    record_audit(
        db,
        "commercial_terms.changed",
        "commercial_terms",
        terms.id,
        "user",
        admin.id,
        after=after,
        reason=data.reason,
    )
    record_event(db, "commercial_terms.changed", "commercial_terms", terms.id, "user", admin.id, after)
    db.commit()
    return terms
