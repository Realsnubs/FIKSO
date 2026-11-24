import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk

RUN_OUTCOMES = ("proposed", "no_candidates")
RUN_CLOSE_REASONS = (
    "client_confirmed",
    "client_rejected",
    "client_timeout",
    "master_accepted",
    "master_declined",
    "master_expired",
    "cancelled",
    "conflict",
)
CANDIDATE_ROLES = ("proposal", "alternative", "not_shown")
ORDER_STATUSES = (
    "offered",
    "declined",
    "expired",
    "accepted",
    "scheduled",
    "en_route",
    "in_progress",
    "completed",
    "reviewed",
    "cancelled",
)
# Statuses in which an order holds the master's time (owner decision Q-FINAL-03, EXCLUDE constraint).
BLOCKING_STATUSES = ("offered", "accepted", "scheduled", "en_route", "in_progress")
OFFER_RESPONSES = ("accepted", "declined", "expired", "cancelled")
WORKSHEET_STATES = ("draft", "finalised")
# sent = the provider accepted the message (it returned a message ID); delivered/undelivered come from
# its report.
NOTIFICATION_STATUSES = ("pending", "sent", "delivered", "undelivered", "failed", "skipped", "read")
JOB_STATUSES = ("running", "succeeded", "failed")


class MatchingRun(UUIDPk, CreatedAt, Base):
    """One matching round of a request (≤ 3). Snapshot of what matching saw and why it ended (R-MATCH-06)."""

    __tablename__ = "matching_runs"
    __table_args__ = (
        CheckConstraint(f"outcome IN {RUN_OUTCOMES}", name="outcome"),
        CheckConstraint(f"close_reason IS NULL OR close_reason IN {RUN_CLOSE_REASONS}", name="close_reason"),
        CheckConstraint("run_no BETWEEN 1 AND 3", name="run_no"),
        # A technical re-run after a confirmation conflict keeps the round number (it is not a new round).
        UniqueConstraint("request_id", "run_no", "attempt"),
        Index(
            "ix_matching_runs_open_proposal",
            "proposal_expires_at",
            postgresql_where=text("closed_at IS NULL AND outcome = 'proposed'"),
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False
    )
    run_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    available_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(Text)


class MatchingCandidate(UUIDPk, Base):
    __tablename__ = "matching_candidates"
    __table_args__ = (
        CheckConstraint(f"role_in_result IN {CANDIDATE_ROLES}", name="role_in_result"),
        CheckConstraint("eta_source IN ('routing', 'fallback')", name="eta_source"),
        Index("ix_matching_candidates_run_rank", "matching_run_id", "rank"),
    )

    matching_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matching_runs.id", ondelete="CASCADE"), nullable=False
    )
    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    eta_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    eta_source: Mapped[str] = mapped_column(Text, nullable=False)
    rating_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    completed_jobs: Mapped[int] = mapped_column(Integer, nullable=False)
    role_in_result: Mapped[str] = mapped_column(Text, nullable=False)
    chosen_by_client: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Order(UUIDPk, Timestamps, Base):
    """One assignment of one master to a request: an active offer while `offered`, then the confirmed order.

    The same row moves from `offered` to `accepted`, so the master's time block never has a gap; the
    exclusion constraint makes two overlapping blocking rows of one master impossible (Q-FINAL-03).
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status"),
        CheckConstraint("order_type IN ('immediate', 'reserved')", name="order_type"),
        CheckConstraint("NOT isempty(busy_range)", name="busy_range_not_empty"),
        ExcludeConstraint(
            ("master_id", "="),
            ("busy_range", "&&"),
            using="gist",
            where=text(f"status IN {BLOCKING_STATUSES}"),
            name="ex_orders_master_busy_range",
        ),
        Index(
            "uq_orders_one_live_per_request",
            "request_id",
            unique=True,
            postgresql_where=text("status NOT IN ('declined', 'expired', 'cancelled')"),
        ),
        Index("ix_orders_client_created", "client_id", "created_at"),
        Index("ix_orders_master_status", "master_id", "status"),
        Index("ix_orders_status_updated", "status", "updated_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False
    )
    matching_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matching_runs.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimated_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    busy_range: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    en_route_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by_role: Mapped[str | None] = mapped_column(Text)
    commission_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    communication_language: Mapped[str | None] = mapped_column(Text)
    hourly_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    minimum_order_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class OrderOffer(UUIDPk, Base):
    """The offer of an order to its master (exactly one per order, so offer and order never diverge)."""

    __tablename__ = "order_offers"
    __table_args__ = (
        CheckConstraint(f"response IS NULL OR response IN {OFFER_RESPONSES}", name="response"),
        CheckConstraint("expires_at > offered_at", name="expiry_after_offer"),
        Index("ix_order_offers_open", "expires_at", postgresql_where=text("response IS NULL")),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderStatusHistory(UUIDPk, CreatedAt, Base):
    """Append-only status log of orders and requests (R-ORD-04). Exactly one of order_id/request_id is set."""

    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'service_principal', 'system')", name="actor_type"),
        Index("ix_order_status_history_order", "order_id", "created_at"),
        Index("ix_order_status_history_request", "request_id", "created_at"),
    )

    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False
    )
    entity: Mapped[str] = mapped_column(Text, nullable=False)  # "request" or "order"
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None]
    reason: Mapped[str | None] = mapped_column(Text)


class OrderDeparture(Base):
    """D-Billable departure (START) record, once per order. Departure does not start billable time (K-7)."""

    __tablename__ = "order_departures"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), primary_key=True
    )
    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    departed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_history_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_status_history.id", ondelete="RESTRICT"), nullable=False
    )


class WorkSegment(UUIDPk, Base):
    """A stretch of actual work between start/resume and pause/finish; billable time is their sum."""

    __tablename__ = "work_segments"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ordered"),
        Index(
            "uq_work_segments_one_open", "order_id", unique=True, postgresql_where=text("ended_at IS NULL")
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Worksheet(UUIDPk, Timestamps, Base):
    """The work sheet of an order (R-WS). Finalised sheets are never edited (R-WS-03)."""

    __tablename__ = "worksheets"
    __table_args__ = (
        CheckConstraint(f"state IN {WORKSHEET_STATES}", name="state"),
        CheckConstraint("materials_amount_eur >= 0 AND external_costs_eur >= 0", name="amounts_not_negative"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    work_description: Mapped[str | None] = mapped_column(Text)
    limitations_explained: Mapped[str | None] = mapped_column(Text)
    is_temporary_repair: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    materials_amount_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    external_costs_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    travel_minutes: Mapped[int | None] = mapped_column(Integer)
    billable_seconds: Mapped[int | None] = mapped_column(Integer)
    labour_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    calculation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finalised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class WorksheetMaterial(UUIDPk, Base):
    __tablename__ = "worksheet_materials"
    __table_args__ = (CheckConstraint("amount_eur >= 0 AND quantity > 0", name="positive"),)

    worksheet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worksheets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Review(UUIDPk, CreatedAt, Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class Notification(UUIDPk, CreatedAt, Base):
    """In-app notification and the outbox for other channels (worker delivers with retries)."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(f"status IN {NOTIFICATION_STATUSES}", name="status"),
        CheckConstraint("channel IN ('in_app', 'sms')", name="channel"),
        Index("ix_notifications_user_status", "user_id", "status", "created_at"),
        Index("ix_notifications_due", "next_attempt_at", postgresql_where=text("status = 'pending'")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(Text, unique=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRun(UUIDPk, Base):
    """One pass of a background job, for monitoring failing or stuck jobs. No personal data."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="status"),
        Index("ix_job_runs_name_started", "job_name", "started_at"),
    )

    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    worker_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
