import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk

REQUEST_TYPES = ("immediate", "reserved")
REQUEST_STATUSES = ("draft", "matching", "proposed", "confirmed", "unserved", "cancelled")
REQUEST_SOURCES = ("app", "website_deeplink")
UNSERVED_REASONS = ("no_candidates", "rounds_exhausted")


class ServiceRequest(UUIDPk, Timestamps, Base):
    """A client's request for one orderable service (R-REQ, D1). The exact address is personal data."""

    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(f"request_type IN {REQUEST_TYPES}", name="request_type"),
        CheckConstraint(f"status IN {REQUEST_STATUSES}", name="status"),
        CheckConstraint(f"source IN {REQUEST_SOURCES}", name="source"),
        CheckConstraint(
            f"unserved_reason IS NULL OR unserved_reason IN {UNSERVED_REASONS}", name="unserved_reason"
        ),
        CheckConstraint("char_length(description) BETWEEN 10 AND 2000", name="description_length"),
        CheckConstraint(
            "request_type = 'immediate' OR (preferred_time_from IS NOT NULL AND preferred_time_to IS "
            "NOT NULL "
            "AND preferred_time_to > preferred_time_from)",
            name="reserved_window",
        ),
        CheckConstraint("current_round BETWEEN 0 AND 3", name="current_round"),
        UniqueConstraint("client_id", "idempotency_key"),
        Index("ix_service_requests_client_created", "client_id", "created_at"),
        Index("ix_service_requests_status_created", "status", "created_at"),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_services.id", ondelete="RESTRICT"), nullable=False
    )
    # IDs, names and W-ID as they were when the request was made (R-CAT-09).
    catalogue_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    commercial_terms_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commercial_terms.id", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_time_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferred_time_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    address_formatted: Mapped[str] = mapped_column(Text, nullable=False)
    flat: Mapped[str | None] = mapped_column(Text)
    access_info: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lon: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    geocode_source: Mapped[str] = mapped_column(Text, nullable=False)
    # City-based matching (2026-11-05). Requests created before have none and cannot be re-matched.
    city_code: Mapped[str | None] = mapped_column(ForeignKey("cities.code", ondelete="RESTRICT"))
    # NULL = "any available language" (the master needs at least one); never the interface language.
    communication_language: Mapped[str | None] = mapped_column(
        ForeignKey("communication_languages.code", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    unserved_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="app", server_default="app")
    deeplink_w_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
