import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPk

ENTITY_TYPES = ("qualification", "request", "worksheet", "profile", "portfolio")


class Attachment(UUIDPk, Base):
    """A stored file, always created together with the record it belongs to (R-MST-15).

    Rows are immutable and never deleted (DB trigger): the owner/entity binding cannot be changed afterwards.
    No original file name is kept; the storage key is random.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {ENTITY_TYPES}", name="entity_type"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        Index("ix_attachments_entity", "entity_type", "entity_id"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
