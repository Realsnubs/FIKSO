"""Service catalogue: Category → Specialisation → Service, plus qualification types (R-CAT, DATABASE §3.2).

IDs never change and rows are never deleted (DB triggers); `archived`/`rejected` replace deletion.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk

GROUP_STATUSES = ("active", "inactive", "planned", "archived")
SERVICE_STATUSES = ("draft", "active", "inactive", "planned", "hold", "rejected", "archived")
QUALIFICATION_STATUSES = ("draft", "active", "archived")
SOURCES = ("seed_cm_v1", "kvc_v1", "admin")
RISK_LEVELS = ("normal", "high")
SYNC_IMPORT_STATUSES = ("previewed", "applied", "rejected")

# W001–W070 belong exclusively to the KVC "Darbu katalogs V1" import (Q-20).
KVC_W_ID_PATTERN = "^W0(0[1-9]|[1-6][0-9]|70)$"
W_ID_PATTERN = "^W[0-9]{3,}$"
W_ID_SEQUENCE = "catalogue_w_id_seq"


class CatalogueEntry(UUIDPk, Timestamps):
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="admin", server_default="admin")
    source_ref: Mapped[str | None] = mapped_column(Text)
    # Incremented by the service layer on every change; exports carry it for diagnostics.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Content hash at the last environment import; a different current hash means a local edit (R-CAT-15).
    last_sync_hash: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


service_qualifications = Table(
    "service_qualifications",
    Base.metadata,
    Column("service_id", ForeignKey("catalogue_services.id", ondelete="CASCADE"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

specialisation_qualifications = Table(
    "specialisation_qualifications",
    Base.metadata,
    Column(
        "specialisation_id", ForeignKey("catalogue_specialisations.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("qualification_id", ForeignKey("qualifications.id", ondelete="RESTRICT"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


class CatalogueCategory(CatalogueEntry, Base):
    __tablename__ = "catalogue_categories"
    __table_args__ = (
        CheckConstraint(f"status IN {GROUP_STATUSES}", name="status"),
        CheckConstraint(f"source IN {SOURCES}", name="source"),
        UniqueConstraint("source", "source_ref"),
        Index(
            "uq_catalogue_categories_name",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
    )

    specialisations: Mapped[list["CatalogueSpecialisation"]] = relationship(
        back_populates="category", order_by="CatalogueSpecialisation.sort_order"
    )


class CatalogueSpecialisation(CatalogueEntry, Base):
    __tablename__ = "catalogue_specialisations"
    __table_args__ = (
        CheckConstraint(f"status IN {GROUP_STATUSES}", name="status"),
        CheckConstraint(f"source IN {SOURCES}", name="source"),
        UniqueConstraint("source", "source_ref"),
        Index(
            "uq_catalogue_specialisations_name",
            "category_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_categories.id", ondelete="RESTRICT"), nullable=False
    )
    # Admin-set only, when the whole specialisation genuinely needs a qualification (Q-21).
    qualification_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    category: Mapped[CatalogueCategory] = relationship(back_populates="specialisations")
    services: Mapped[list["CatalogueService"]] = relationship(
        back_populates="specialisation", order_by="CatalogueService.sort_order"
    )
    qualifications: Mapped[list["Qualification"]] = relationship(secondary=specialisation_qualifications)


class CatalogueService(CatalogueEntry, Base):
    """A specific service (work type). `w_id` is its permanent external key (KVC W001–W070 or W071+)."""

    __tablename__ = "catalogue_services"
    __table_args__ = (
        CheckConstraint(f"status IN {SERVICE_STATUSES}", name="status"),
        CheckConstraint(f"source IN {SOURCES}", name="source"),
        CheckConstraint(f"risk_level IN {RISK_LEVELS}", name="risk_level"),
        CheckConstraint(f"w_id ~ '{W_ID_PATTERN}'", name="w_id_format"),
        CheckConstraint(f"(source = 'kvc_v1') = (w_id ~ '{KVC_W_ID_PATTERN}')", name="w_id_kvc_range"),
        UniqueConstraint("source", "source_ref"),
        Index(
            "uq_catalogue_services_name",
            "specialisation_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status NOT IN ('archived', 'rejected')"),
        ),
    )

    specialisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_specialisations.id", ondelete="RESTRICT"), nullable=False
    )
    w_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, default="normal", server_default="normal")
    qualification_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    restrictions: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[str | None] = mapped_column(Text)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    specialisation: Mapped[CatalogueSpecialisation] = relationship(back_populates="services")
    qualifications: Mapped[list["Qualification"]] = relationship(secondary=service_qualifications)


class Qualification(UUIDPk, Timestamps, Base):
    """Admin-defined qualification type with its verification rules (R-MST-09). None are seeded."""

    __tablename__ = "qualifications"
    __table_args__ = (
        CheckConstraint(f"status IN {QUALIFICATION_STATUSES}", name="status"),
        CheckConstraint("max_validity_months IS NULL OR max_validity_months > 0", name="max_validity"),
        Index(
            "uq_qualifications_name",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    requires_document: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    requires_document_number: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    requires_expiry_date: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    max_validity_months: Mapped[int | None] = mapped_column(Integer)
    verifier_instructions: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_sync_hash: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class CatalogueSyncImport(UUIDPk, CreatedAt, Base):
    """A production catalogue package uploaded to staging: previewed, then applied once (R-CAT-15)."""

    __tablename__ = "catalogue_sync_imports"
    __table_args__ = (
        CheckConstraint(f"status IN {SYNC_IMPORT_STATUSES}", name="status"),
        Index(
            "uq_catalogue_sync_imports_applied",
            "package_sha256",
            unique=True,
            postgresql_where=text("status = 'applied'"),
        ),
        Index(
            "uq_catalogue_sync_imports_applied_package_id",
            "package_id",
            unique=True,
            postgresql_where=text("status = 'applied'"),
        ),
    )

    # Replay protection (R-CAT-17): a package ID is applied at most once.
    package_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    format_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_environment: Mapped[str] = mapped_column(Text, nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    package: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="previewed", server_default="previewed")
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    applied_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
