import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession
from app.models import User
from app.schemas.admin import AdminUserOut, BlockUserIn
from app.schemas.common import Page
from app.services import users as users_service
from app.services.auth import user_out

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _admin_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        **user_out(user).model_dump(), blocked_reason=user.blocked_reason, last_login_at=user.last_login_at
    )


@router.get("")
def list_users(
    db: DbSession,
    _: AdminUser,
    role: Literal["client", "master", "admin"] | None = None,
    status: Literal["active", "blocked"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> Page[AdminUserOut]:
    users, next_cursor = users_service.list_users(db, role, status, limit, cursor)
    return Page(items=[_admin_out(u) for u in users], next_cursor=next_cursor)


@router.get("/{user_id}")
def get_user(user_id: uuid.UUID, db: DbSession, _: AdminUser) -> AdminUserOut:
    return _admin_out(users_service.get_user(db, user_id))


@router.post("/{user_id}/block")
def block_user(user_id: uuid.UUID, data: BlockUserIn, db: DbSession, admin: AdminUser) -> AdminUserOut:
    return _admin_out(users_service.set_blocked(db, admin, user_id, blocked=True, reason=data.reason))


@router.post("/{user_id}/unblock")
def unblock_user(user_id: uuid.UUID, db: DbSession, admin: AdminUser) -> AdminUserOut:
    return _admin_out(users_service.set_blocked(db, admin, user_id, blocked=False, reason=None))
