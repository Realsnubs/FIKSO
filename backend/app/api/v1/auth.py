from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.ratelimit import rate_limit
from app.schemas.auth import (
    GuestClientIn,
    LoginIn,
    RegisterIn,
    SetPasswordIn,
    SmsCodeRequestIn,
    SmsCodeVerifyIn,
    TokenOut,
    UserOut,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["me"])

REFRESH_COOKIE = "fikso_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]
UserAgent = Annotated[str | None, Header()]


def _with_cookie(response: Response, tokens: auth_service.IssuedTokens) -> TokenOut:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=tokens.refresh_max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return tokens.body


@router.post(
    "/register/client",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", "rate_limit_register"))],
)
def register_client(
    data: RegisterIn, response: Response, db: DbSession, user_agent: UserAgent = None
) -> TokenOut:
    return _with_cookie(response, auth_service.register(db, data, "client", user_agent))


@router.post(
    "/register/master",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", "rate_limit_register"))],
)
def register_master(
    data: RegisterIn, response: Response, db: DbSession, user_agent: UserAgent = None
) -> TokenOut:
    return _with_cookie(response, auth_service.register(db, data, "master", user_agent))


@router.post(
    "/guest/client",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", "rate_limit_register"))],
)
def register_guest_client(
    data: GuestClientIn, response: Response, db: DbSession, user_agent: UserAgent = None
) -> TokenOut:
    """Ordering without a password: creates a client account from the contact details and signs it in."""
    return _with_cookie(response, auth_service.register_guest_client(db, data, user_agent))


@router.post(
    "/sms-code",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("sms_code", "rate_limit_sms_code"))],
)
def request_sms_code(data: SmsCodeRequestIn, db: DbSession) -> None:
    """Clients only. Always 202, whether or not the phone has an account."""
    auth_service.request_login_code(db, data.phone)


@router.post("/sms-code/verify", dependencies=[Depends(rate_limit("login", "rate_limit_login"))])
def verify_sms_code(
    data: SmsCodeVerifyIn, response: Response, db: DbSession, user_agent: UserAgent = None
) -> TokenOut:
    return _with_cookie(response, auth_service.login_with_code(db, data.phone, data.code, user_agent))


@router.post("/login", dependencies=[Depends(rate_limit("login", "rate_limit_login"))])
def login(data: LoginIn, response: Response, db: DbSession, user_agent: UserAgent = None) -> TokenOut:
    return _with_cookie(response, auth_service.login(db, data.email, data.password, user_agent))


@router.post("/refresh")
def refresh(
    response: Response, db: DbSession, fikso_refresh: RefreshCookie = None, user_agent: UserAgent = None
) -> TokenOut:
    return _with_cookie(response, auth_service.refresh(db, fikso_refresh, user_agent))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: DbSession, fikso_refresh: RefreshCookie = None) -> None:
    auth_service.logout(db, fikso_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@me_router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return auth_service.user_out(user)


@me_router.post("/me/password", dependencies=[Depends(rate_limit("login", "rate_limit_login"))])
def set_password(data: SetPasswordIn, user: CurrentUser, db: DbSession) -> UserOut:
    """Sets the first password of an account created without one, or changes it (current password needed)."""
    return auth_service.set_password(db, user, data)
