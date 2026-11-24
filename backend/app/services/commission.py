"""Commission ledger, balance model (P2, R-COM). Append-only; payments are never allocated to charges."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.errors import AppError
from app.models import CommissionLedgerEntry, CommissionLimitChange, CommissionSettings, MasterProfile, User
from app.services.events import record_audit, record_event
from app.services.money import eur


def current_settings(db: Session) -> CommissionSettings:
    row = db.scalar(select(CommissionSettings).order_by(CommissionSettings.effective_from.desc()).limit(1))
    if row is None:
        raise AppError(
            "COMMISSION_NOT_CONFIGURED", "Commission settings missing.", status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return row


def balance(db: Session, master_id: uuid.UUID) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(CommissionLedgerEntry.amount_eur), 0)).where(
            CommissionLedgerEntry.master_id == master_id
        )
    )
    return eur(value or 0)


def balance_expr() -> object:
    """Correlated SUM for the matching candidate query (limit filter, Q-11: reached = balance ≥ limit)."""
    return (
        select(func.coalesce(func.sum(CommissionLedgerEntry.amount_eur), 0))
        .where(CommissionLedgerEntry.master_id == MasterProfile.id)
        .correlate(MasterProfile)
        .scalar_subquery()
    )


@dataclass(frozen=True)
class Summary:
    charged_total: Decimal
    paid_total: Decimal
    adjustments_total: Decimal
    balance: Decimal
    limit: Decimal
    limit_reached: bool


def summary(db: Session, master: MasterProfile) -> Summary:
    rows = db.execute(
        select(CommissionLedgerEntry.entry_type, func.coalesce(func.sum(CommissionLedgerEntry.amount_eur), 0))
        .where(CommissionLedgerEntry.master_id == master.id)
        .group_by(CommissionLedgerEntry.entry_type)
    ).all()
    totals = {kind: eur(total) for kind, total in rows}
    charged = totals.get("charge", eur(0))
    paid = -totals.get("payment", eur(0))
    adjustments = totals.get("adjustment", eur(0))
    current = eur(charged - paid + adjustments)
    return Summary(
        charged,
        eur(paid),
        adjustments,
        current,
        master.commission_limit_eur,
        current >= master.commission_limit_eur,
    )


def entries(db: Session, master_id: uuid.UUID) -> list[CommissionLedgerEntry]:
    return list(
        db.scalars(
            select(CommissionLedgerEntry)
            .where(CommissionLedgerEntry.master_id == master_id)
            .order_by(CommissionLedgerEntry.created_at.desc())
        ).all()
    )


def _repeated(db: Session, master_id: uuid.UUID, key: str | None) -> CommissionLedgerEntry | None:
    if not key:
        return None
    return db.scalar(
        select(CommissionLedgerEntry).where(
            CommissionLedgerEntry.master_id == master_id, CommissionLedgerEntry.idempotency_key == key
        )
    )


def _lock_master(db: Session, master_id: uuid.UUID) -> MasterProfile:
    master = db.scalar(select(MasterProfile).where(MasterProfile.id == master_id).with_for_update())
    if master is None:
        raise AppError("NOT_FOUND", "Master not found.", status.HTTP_404_NOT_FOUND)
    return master


def record_charge(
    db: Session, master_id: uuid.UUID, order_id: uuid.UUID, labour: Decimal, rate: Decimal, amount: Decimal
) -> CommissionLedgerEntry:
    """Called only from work-sheet finalisation, under the master lock; the unique index stops a
    second charge."""
    entry = CommissionLedgerEntry(
        master_id=master_id,
        entry_type="charge",
        order_id=order_id,
        base_labour_eur=labour,
        rate=rate,
        amount_eur=amount,
    )
    db.add(entry)
    record_event(
        db,
        "commission.charged",
        "master",
        master_id,
        "system",
        None,
        {"order_id": str(order_id), "amount_eur": str(amount)},
    )
    return entry


def record_payment(
    db: Session,
    admin: User,
    master_id: uuid.UUID,
    amount: Decimal,
    paid_on: date,
    method: str,
    reference: str | None,
    comment: str | None,
    idempotency_key: str | None = None,
) -> CommissionLedgerEntry:
    """A payment the owner received; it lowers the balance and is never tied to particular charges.

    A repeated request with the same Idempotency-Key returns the first entry instead of recording it twice.
    """
    master = _lock_master(db, master_id)
    repeated = _repeated(db, master.id, idempotency_key)
    if repeated is not None:
        return repeated
    # The business day in Riga, not UTC: just after midnight a payment dated "today" is not in the future.
    if paid_on > business_today(db):
        raise AppError(
            "INVALID_DATE", "The payment date cannot be in the future.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    entry = CommissionLedgerEntry(
        master_id=master.id,
        entry_type="payment",
        amount_eur=-eur(amount),
        payment_method=method,
        paid_on=paid_on,
        reference=reference,
        reason=comment,
        recorded_by=admin.id,
        idempotency_key=idempotency_key,
    )
    db.add(entry)
    db.flush()
    after = {"amount_eur": str(eur(amount)), "paid_on": paid_on.isoformat(), "method": method}
    record_audit(
        db,
        "commission.payment_recorded",
        "master_profile",
        master.id,
        "user",
        admin.id,
        after=after,
        reason=comment,
    )
    record_event(db, "commission.payment_recorded", "master", master.id, "user", admin.id, after)
    db.commit()
    return entry


def record_adjustment(
    db: Session,
    admin: User,
    master_id: uuid.UUID,
    amount: Decimal,
    reason: str,
    idempotency_key: str | None = None,
) -> CommissionLedgerEntry:
    master = _lock_master(db, master_id)
    repeated = _repeated(db, master.id, idempotency_key)
    if repeated is not None:
        return repeated
    entry = CommissionLedgerEntry(
        master_id=master.id,
        entry_type="adjustment",
        amount_eur=eur(amount),
        reason=reason,
        recorded_by=admin.id,
        idempotency_key=idempotency_key,
    )
    db.add(entry)
    db.flush()
    record_audit(
        db,
        "commission.adjusted",
        "master_profile",
        master.id,
        "user",
        admin.id,
        after={"amount_eur": str(eur(amount))},
        reason=reason,
    )
    record_event(
        db, "commission.adjusted", "master", master.id, "user", admin.id, {"amount_eur": str(eur(amount))}
    )
    db.commit()
    return entry


def change_limit(
    db: Session, admin: User, master_id: uuid.UUID, new_limit: Decimal, reason: str
) -> MasterProfile:
    master = _lock_master(db, master_id)
    old = master.commission_limit_eur
    master.commission_limit_eur = eur(new_limit)
    db.add(
        CommissionLimitChange(
            master_id=master.id,
            old_limit_eur=old,
            new_limit_eur=eur(new_limit),
            reason=reason,
            changed_by=admin.id,
        )
    )
    record_audit(
        db,
        "commission.limit_changed",
        "master_profile",
        master.id,
        "user",
        admin.id,
        before={"limit": str(old)},
        after={"limit": str(eur(new_limit))},
        reason=reason,
    )
    record_event(
        db, "commission.limit_changed", "master", master.id, "user", admin.id, {"limit": str(eur(new_limit))}
    )
    db.commit()
    return master


def overview(db: Session) -> list[tuple[MasterProfile, User, Decimal]]:
    bal = balance_expr()
    rows = db.execute(
        select(MasterProfile, User, bal.label("balance"))  # type: ignore[attr-defined]
        .join(User, User.id == MasterProfile.user_id)
        .where(MasterProfile.approval_status == "approved")
        .order_by(bal.desc(), User.full_name)  # type: ignore[attr-defined]
    ).all()
    return [(m, u, eur(b)) for m, u, b in rows]
