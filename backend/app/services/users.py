import base64
import uuid
from datetime import datetime

from fastapi import status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import User
from app.services.auth import revoke_all_sessions
from app.services.events import record_audit, record_event


def _encode_cursor(user: User) -> str:
    return base64.urlsafe_b64encode(f"{user.created_at.isoformat()}|{user.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, user_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created), uuid.UUID(user_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("INVALID_CURSOR", "Invalid pagination cursor.") from exc


def list_users(
    db: Session, role: str | None, user_status: str | None, limit: int, cursor: str | None
) -> tuple[list[User], str | None]:
    query = select(User).where(User.deleted_at.is_(None))
    if role:
        query = query.where(User.role == role)
    if user_status:
        query = query.where(User.status == user_status)
    if cursor:
        created, user_id = _decode_cursor(cursor)
        query = query.where(
            or_(User.created_at < created, and_(User.created_at == created, User.id < user_id))
        )
    rows = list(db.scalars(query.order_by(User.created_at.desc(), User.id.desc()).limit(limit + 1)))
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError("USER_NOT_FOUND", "User not found.", status.HTTP_404_NOT_FOUND)
    return user


def set_blocked(db: Session, admin: User, user_id: uuid.UUID, blocked: bool, reason: str | None) -> User:
    user = get_user(db, user_id)
    if user.id == admin.id:
        raise AppError(
            "CANNOT_BLOCK_SELF", "Admins cannot block their own account.", status.HTTP_409_CONFLICT
        )

    before = {"status": user.status}
    if blocked:
        user.status, user.blocked_reason = "blocked", reason
        revoke_all_sessions(db, user.id)
    else:
        user.status, user.blocked_reason = "active", None
    action = "user.blocked" if blocked else "user.unblocked"
    record_audit(db, action, "user", user.id, "user", admin.id, before, {"status": user.status}, reason)
    record_event(db, action, "user", user.id, "user", admin.id, {"role": user.role})
    db.commit()
    return user
