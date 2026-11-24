import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Index, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk

ACTOR_TYPES = ("user", "service_principal", "system")


class DomainEvent(UUIDPk, CreatedAt, Base):
    """Append-only business event log (AI-ready data layer, R-AIR). A DB trigger blocks UPDATE/DELETE."""

    __tablename__ = "domain_events"
    __table_args__ = (
        CheckConstraint(f"actor_type IN {ACTOR_TYPES}", name="actor_type"),
        Index("ix_domain_events_aggregate", "aggregate_type", "aggregate_id", "created_at"),
        Index("ix_domain_events_type_created", "event_type", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")


class AuditLog(UUIDPk, CreatedAt, Base):
    """Append-only record of admin/system writes and of access to personal documents.

    A DB trigger blocks UPDATE/DELETE.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(f"actor_type IN {ACTOR_TYPES}", name="actor_type"),
        Index("ix_audit_log_entity", "entity_type", "entity_id", "created_at"),
    )

    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
