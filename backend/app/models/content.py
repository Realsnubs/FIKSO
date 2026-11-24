import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk

MEDIA_STATUSES = ("ready", "archived")
RIGHTS_BASES = ("own", "client_consent", "licence")
CONTENT_ENTITY_TYPES = ("specialisation",)
VERSION_STATES = ("draft", "published", "superseded")
PUBLIC_EVENT_TYPES = ("catalogue_view", "specialisation_view", "service_selected")


class PublicMedia(UUIDPk, Timestamps, Base):
    """A public catalogue image (OQ-10/11). Only processed WebP variants are stored; the original never is.

    Kept apart from `attachments` (private files): its own table, its own storage and its own route.
    """

    __tablename__ = "public_media"
    __table_args__ = (
        CheckConstraint(f"status IN {MEDIA_STATUSES}", name="status"),
        CheckConstraint(f"rights_basis IN {RIGHTS_BASES}", name="rights_basis"),
        CheckConstraint("personal_data_checked", name="personal_data_checked"),
        CheckConstraint(
            "rights_basis <> 'client_consent' OR (rights_reference IS NOT NULL AND consent_given_on "
            "IS NOT NULL)",
            name="consent_recorded",
        ),
    )

    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # {"560": {"key": ..., "width": .., "height": ..}, "800": ..., "1300": ...}
    variants: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    alt: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ready", server_default="ready")
    rights_basis: Mapped[str] = mapped_column(Text, nullable=False)
    rights_reference: Mapped[str | None] = mapped_column(Text)
    consent_given_on: Mapped[date | None] = mapped_column(Date)
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    personal_data_checked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    @property
    def publishable(self) -> bool:
        return self.status == "ready" and self.consent_withdrawn_at is None


class CatalogueContent(UUIDPk, Timestamps, Base):
    """Page content of a catalogue entity (C4). The catalogue itself is never changed by content."""

    __tablename__ = "catalogue_content"
    __table_args__ = (
        CheckConstraint("entity_type = 'specialisation'", name="entity_type"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        UniqueConstraint("entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalogue_content_versions.id", ondelete="RESTRICT", use_alter=True)
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class CatalogueContentVersion(UUIDPk, CreatedAt, Base):
    """One version of a page. `published`/`superseded` rows are never edited; edits go to the one `draft`."""

    __tablename__ = "catalogue_content_versions"
    __table_args__ = (
        CheckConstraint(f"state IN {VERSION_STATES}", name="state"),
        UniqueConstraint("content_id", "version_no"),
        Index(
            "uq_catalogue_content_versions_one_draft",
            "content_id",
            unique=True,
            postgresql_where=text("state = 'draft'"),
        ),
    )

    content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_content.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class ContentSlugRedirect(CreatedAt, Base):
    __tablename__ = "content_slug_redirects"

    old_slug: Mapped[str] = mapped_column(Text, primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_content.id", ondelete="CASCADE"), nullable=False
    )


class PublicEvent(UUIDPk, CreatedAt, Base):
    """Anonymous catalogue usage counters for admin statistics (C7). No user, IP or device data."""

    __tablename__ = "public_events"
    __table_args__ = (
        CheckConstraint(f"event_type IN {PUBLIC_EVENT_TYPES}", name="event_type"),
        Index("ix_public_events_type_created", "event_type", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None]
    source: Mapped[str | None] = mapped_column(Text)
