from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User:
    unauthenticated = AppError("NOT_AUTHENTICATED", "Authentication required.", status.HTTP_401_UNAUTHORIZED)
    if credentials is None:
        raise unauthenticated
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise unauthenticated
    user = db.get(User, payload["sub"])
    # Status is re-checked on every request so a block takes effect before the access token expires.
    if user is None or not user.is_active:
        raise unauthenticated
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "You do not have access to this resource.", status.HTTP_403_FORBIDDEN)
        return user

    return dependency


AdminUser = Annotated[User, Depends(require_role("admin"))]
