import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk

if TYPE_CHECKING:
    from app.models.master import MasterProfile

ROLES = ("client", "master", "admin")
USER_STATUSES = ("active", "blocked")


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="role"),
        CheckConstraint(f"status IN {USER_STATUSES}", name="status"),
        # E-mail is stored lower-cased by the service; the functional index guards against mixed-case writes.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index("ix_users_role_status", "role", "status"),
        # Clients who ordered without a password have none (owner decision 2026-11-24); other roles always do.
        CheckConstraint("password_hash IS NOT NULL OR role = 'client'", name="password_role"),
    )

    role: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    master_profile: Mapped["MasterProfile | None"] = relationship(
        back_populates="user", uselist=False, foreign_keys="MasterProfile.user_id"
    )

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.deleted_at is None


class AuthSession(UUIDPk, CreatedAt, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)


class LoginCode(UUIDPk, CreatedAt, Base):
    """One-time SMS sign-in code for clients; only its hash is stored."""

    __tablename__ = "login_codes"
    __table_args__ = (
        Index("ix_login_codes_user_id_open", "user_id", postgresql_where=text("used_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
