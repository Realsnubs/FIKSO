import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk

ENTRY_TYPES = ("charge", "payment", "adjustment")
PAYMENT_METHODS = ("cash", "bank_transfer")


class CommissionSettings(UUIDPk, CreatedAt, Base):
    """Commission rate and default unpaid limit, with history (R-COM-01/02). The latest row applies."""

    __tablename__ = "commission_settings"
    __table_args__ = (
        CheckConstraint("rate >= 0 AND rate <= 1", name="rate"),
        CheckConstraint("default_limit_eur >= 0", name="default_limit"),
    )

    rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    default_limit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(Text)


class CommissionLedgerEntry(UUIDPk, CreatedAt, Base):
    """Append-only commission journal of one master. Balance = SUM(amount_eur); payments are negative.

    Payments are never allocated to charges (owner decision: balance model).
    """

    __tablename__ = "commission_ledger"
    __table_args__ = (
        CheckConstraint(f"entry_type IN {ENTRY_TYPES}", name="entry_type"),
        CheckConstraint(
            "(entry_type = 'charge' AND amount_eur > 0 AND order_id IS NOT NULL AND base_labour_eur "
            "IS NOT NULL "
            "AND rate IS NOT NULL) OR (entry_type = 'payment' AND amount_eur < 0 AND order_id IS NULL "
            f"AND payment_method IN {PAYMENT_METHODS} AND paid_on IS NOT NULL) "
            "OR (entry_type = 'adjustment' AND amount_eur <> 0 AND reason IS NOT NULL)",
            name="entry_shape",
        ),
        Index(
            "uq_commission_ledger_charge_order",
            "order_id",
            unique=True,
            postgresql_where=text("entry_type = 'charge'"),
        ),
        Index("ix_commission_ledger_master_created", "master_id", "created_at"),
        # A repeated payment/adjustment request (double click, retry) is recorded once.
        Index(
            "uq_commission_ledger_idempotency",
            "master_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    base_labour_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(Text)
    paid_on: Mapped[date | None] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class CommissionLimitChange(UUIDPk, CreatedAt, Base):
    __tablename__ = "commission_limit_changes"

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    old_limit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    new_limit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
