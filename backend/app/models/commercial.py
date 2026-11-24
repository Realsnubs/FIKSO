import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class CommercialTerms(UUIDPk, CreatedAt, Base):
    """Public terms for clients (rate, minimum order value, materials line), append-only history (C1).

    The commission rate is a term for masters and lives in `commission_settings`. A request keeps the row that
    was in force when it was submitted, so later changes never alter it.
    """

    __tablename__ = "commercial_terms"
    __table_args__ = (
        CheckConstraint("hourly_rate_eur > 0", name="hourly_rate"),
        CheckConstraint("minimum_order_eur >= 0", name="minimum_order"),
        Index("ix_commercial_terms_effective_from", "effective_from"),
    )

    hourly_rate_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    minimum_order_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # {"materials": {"lv": ..., "en": ..., "ru": ...}}
    public_notes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class SystemSetting(Base):
    """Operational thresholds editable without a deploy (timeouts, matching parameters, photo limits)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
