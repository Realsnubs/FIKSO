import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk

if TYPE_CHECKING:
    from app.models.user import User

APPROVAL_STATUSES = ("pending_approval", "approved", "rejected")
SPECIALISATION_STATUSES = ("requested", "approved", "rejected", "revoked", "withdrawn")
COMPETENCY_STATUSES = ("declared", "verified", "rejected", "revoked", "withdrawn")
QUALIFICATION_STATUSES = ("submitted", "verified", "rejected", "revoked", "withdrawn")
AVAILABILITY_MODES = ("available_now", "available_for_reservations", "unavailable")


def _decision_recorded(decided: tuple[str, ...]) -> CheckConstraint:
    # An admin decision always names who decided and when.
    return CheckConstraint(
        f"status NOT IN {decided} OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
        name="decision_recorded",
    )


class MasterProfile(UUIDPk, Timestamps, Base):
    """Approval state, availability, work zone and commission limit of a master (R-MST, step 4b, R-COM)."""

    __tablename__ = "master_profiles"
    __table_args__ = (
        CheckConstraint(f"approval_status IN {APPROVAL_STATUSES}", name="approval_status"),
        # The admin approval of a master records who decided and when, like every other decision (R-MST-10).
        CheckConstraint(
            "approval_status NOT IN ('approved', 'rejected') "
            "OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decision_recorded",
        ),
        CheckConstraint(f"availability_mode IN {AVAILABILITY_MODES}", name="availability_mode"),
        CheckConstraint(
            "(work_zone_center_lat IS NULL) = (work_zone_center_lon IS NULL) "
            "AND (work_zone_center_lat IS NULL) = (work_zone_radius_km IS NULL)",
            name="work_zone_complete",
        ),
        CheckConstraint("work_zone_radius_km IS NULL OR work_zone_radius_km > 0", name="work_zone_radius"),
        CheckConstraint("commission_limit_eur >= 0", name="commission_limit"),
        Index("ix_master_profiles_matching", "approval_status", "availability_mode", "is_busy"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    availability_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="unavailable", server_default="unavailable"
    )
    is_busy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    busy_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_zone_center_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    work_zone_center_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    work_zone_radius_km: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    rating_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_limit_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("100.00"), server_default="100.00"
    )
    approval_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending_approval", server_default="pending_approval"
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    user: Mapped["User"] = relationship(back_populates="master_profile", foreign_keys=[user_id])


class _Decision:
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class MasterSpecialisation(_Decision, Timestamps, Base):
    """A master's application for / assignment to a specialisation (R-MST-08). Never deleted."""

    __tablename__ = "master_specialisations"
    __table_args__ = (
        CheckConstraint(f"status IN {SPECIALISATION_STATUSES}", name="status"),
        _decision_recorded(("approved", "rejected", "revoked")),
        Index("ix_master_specialisations_spec_status", "specialisation_id", "status"),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), primary_key=True
    )
    specialisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_specialisations.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="requested", server_default="requested")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MasterCompetency(_Decision, Timestamps, Base):
    """A master's competency for one service (R-MST-02). Only `verified` ever counts (R-MST-11)."""

    __tablename__ = "master_competencies"
    __table_args__ = (
        CheckConstraint(f"status IN {COMPETENCY_STATUSES}", name="status"),
        _decision_recorded(("verified", "rejected", "revoked")),
        Index("ix_master_competencies_service_status", "service_id", "status"),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalogue_services.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="declared", server_default="declared")
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MasterQualification(UUIDPk, _Decision, Timestamps, Base):
    """One qualification submission with evidence (R-MST-09/15). Resubmission creates a new row."""

    __tablename__ = "master_qualifications"
    __table_args__ = (
        CheckConstraint(f"status IN {QUALIFICATION_STATUSES}", name="status"),
        _decision_recorded(("verified", "rejected", "revoked")),
        # One pending submission at a time (0005). A renewal may sit next to an expired verified row, which
        # stays unchanged; "no renewal while a valid one exists" is enforced by the service under a lock.
        Index(
            "uq_master_qualifications_pending",
            "master_id",
            "qualification_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
        Index("ix_master_qualifications_qualification_status", "qualification_id", "status"),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    qualification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qualifications.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="submitted", server_default="submitted")
    # Personal data: never logged; audit entries keep only the last 4 characters.
    document_number: Mapped[str | None] = mapped_column(Text)
    # Inclusive: valid through the end of this date in Europe/Riga (R-MST-11).
    valid_until: Mapped[date | None] = mapped_column(Date)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MasterLocation(Base):
    """The latest location of a master only — no history (R-MST-07, privacy)."""

    __tablename__ = "master_locations"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180", name="coordinates"),
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lon: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    accuracy_m: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
