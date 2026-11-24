import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    hash_login_code,
    hash_password,
    hash_token,
    new_login_code,
    new_refresh_token,
    verify_password,
)
from app.models import AuthSession, LoginCode, MasterProfile, User
from app.schemas.auth import GuestClientIn, RegisterIn, SetPasswordIn, TokenOut, UserOut
from app.services.events import record_event

logger = logging.getLogger(__name__)

LOGIN_CODE_MINUTES = 10
LOGIN_CODE_ATTEMPTS = 5


@dataclass(frozen=True)
class IssuedTokens:
    body: TokenOut
    refresh_token: str
    refresh_max_age: int


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    if user.master_profile is not None:
        out.master_approval_status = user.master_profile.approval_status  # type: ignore[assignment]
    return out


def register(db: Session, data: RegisterIn, role: str, user_agent: str | None) -> IssuedTokens:
    user = _new_user(db, role, data.email, data.phone, data.full_name, hash_password(data.password))
    if role == "master":
        # Masters cannot be matched until an admin approves them (R-AUTH-02/03).
        user.master_profile = MasterProfile(user_id=user.id)
    record_event(db, "user.registered", "user", user.id, "user", user.id, {"role": role})
    tokens = _issue_tokens(db, user, user_agent)
    db.commit()
    return tokens


def register_guest_client(db: Session, data: GuestClientIn, user_agent: str | None) -> IssuedTokens:
    """Ordering without a password: a client account from the contact details, signed in on this device.

    An e-mail or phone that already has an account is refused (the client signs in instead), so an order can
    never be attached to someone else's account.
    """
    user = _new_user(db, "client", data.email, data.phone, data.full_name, None)
    record_event(
        db, "user.registered", "user", user.id, "user", user.id, {"role": "client", "password": False}
    )
    tokens = _issue_tokens(db, user, user_agent)
    db.commit()
    return tokens


def _new_user(
    db: Session, role: str, email: str, phone: str, full_name: str, password_hash: str | None
) -> User:
    email = email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise AppError("EMAIL_TAKEN", "An account with this e-mail already exists.", status.HTTP_409_CONFLICT)
    if db.scalar(select(User.id).where(User.phone == phone)):
        raise AppError("PHONE_TAKEN", "An account with this phone already exists.", status.HTTP_409_CONFLICT)
    user = User(role=role, email=email, phone=phone, full_name=full_name, password_hash=password_hash)
    db.add(user)
    db.flush()
    return user


def set_password(db: Session, user: User, data: SetPasswordIn) -> UserOut:
    if user.password_hash is not None and not verify_password(
        user.password_hash, data.current_password or ""
    ):
        raise AppError(
            "INVALID_CREDENTIALS", "The current password is incorrect.", status.HTTP_401_UNAUTHORIZED
        )
    first = user.password_hash is None
    user.password_hash = hash_password(data.password)
    record_event(db, "user.password_set", "user", user.id, "user", user.id, {"first": first})
    db.commit()
    return user_out(user)


def request_login_code(db: Session, phone: str) -> None:
    """Sends a one-time sign-in code to an active client with this phone.

    The answer never says whether the phone has an account; a failed send is logged without the number.
    """
    from app.integrations.sms import SmsError, get_sms_sender

    sender = get_sms_sender()
    if sender is None:
        raise AppError(
            "SMS_UNAVAILABLE", "Sign-in by SMS is not available.", status.HTTP_503_SERVICE_UNAVAILABLE
        )
    user = db.scalar(
        select(User).where(User.phone == phone, User.role == "client", User.deleted_at.is_(None))
    )
    if user is None or not user.is_active:
        return
    now = datetime.now(UTC)
    # A new code replaces any earlier one.
    db.execute(
        update(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used_at.is_(None)).values(used_at=now)
    )
    code = new_login_code()
    row = LoginCode(id=uuid.uuid4(), user_id=user.id, expires_at=now + timedelta(minutes=LOGIN_CODE_MINUTES))
    row.code_hash = hash_login_code(row.id, code)
    db.add(row)
    db.commit()
    try:
        sender.send(
            phone, f"FIKSO: jūsu ienākšanas kods ir {code}. Tas derīgs {LOGIN_CODE_MINUTES} min.", str(row.id)
        )
    except SmsError as exc:
        logger.warning("login code %s not sent: %s", row.id, exc)


def login_with_code(db: Session, phone: str, code: str, user_agent: str | None) -> IssuedTokens:
    invalid = AppError("INVALID_CODE", "The code is incorrect or has expired.", status.HTTP_401_UNAUTHORIZED)
    user = db.scalar(
        select(User).where(User.phone == phone, User.role == "client", User.deleted_at.is_(None))
    )
    if user is None:
        raise invalid
    row = db.scalar(
        select(LoginCode)
        .where(LoginCode.user_id == user.id, LoginCode.used_at.is_(None))
        .order_by(LoginCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at <= now or row.attempts >= LOGIN_CODE_ATTEMPTS:
        raise invalid
    if not hmac.compare_digest(row.code_hash, hash_login_code(row.id, code)):
        row.attempts += 1
        if row.attempts >= LOGIN_CODE_ATTEMPTS:
            row.used_at = now
        db.commit()
        raise invalid
    if user.status == "blocked":
        raise AppError("ACCOUNT_BLOCKED", "This account is blocked.", status.HTTP_403_FORBIDDEN)
    row.used_at = now
    user.last_login_at = now
    record_event(db, "user.login_code_used", "user", user.id, "user", user.id, {})
    tokens = _issue_tokens(db, user, user_agent)
    db.commit()
    return tokens


def login(db: Session, email: str, password: str, user_agent: str | None) -> IssuedTokens:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower(), User.deleted_at.is_(None)))
    if not verify_password(user.password_hash if user else None, password) or user is None:
        raise AppError("INVALID_CREDENTIALS", "Incorrect e-mail or password.", status.HTTP_401_UNAUTHORIZED)
    if user.status == "blocked":
        raise AppError("ACCOUNT_BLOCKED", "This account is blocked.", status.HTTP_403_FORBIDDEN)
    user.last_login_at = datetime.now(UTC)
    tokens = _issue_tokens(db, user, user_agent)
    db.commit()
    return tokens


def refresh(db: Session, refresh_token: str | None, user_agent: str | None) -> IssuedTokens:
    invalid = AppError(
        "INVALID_REFRESH_TOKEN", "Session expired. Log in again.", status.HTTP_401_UNAUTHORIZED
    )
    if not refresh_token:
        raise invalid
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    if session is None:
        raise invalid
    now = datetime.now(UTC)
    if session.revoked_at is not None:
        # A rotated token was presented again: treat as theft and end every session of this user.
        revoke_all_sessions(db, session.user_id)
        db.commit()
        raise invalid
    if session.expires_at <= now:
        raise invalid
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise invalid

    session.revoked_at = now
    tokens = _issue_tokens(db, user, user_agent)
    db.commit()
    return tokens


def logout(db: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    db.execute(
        update(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_token(refresh_token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def _issue_tokens(db: Session, user: User, user_agent: str | None) -> IssuedTokens:
    settings = get_settings()
    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token = new_refresh_token()
    max_age = settings.refresh_token_days * 86400
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=max_age),
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    db.flush()
    body = TokenOut(access_token=access_token, expires_in=expires_in, user=user_out(user))
    return IssuedTokens(body=body, refresh_token=refresh_token, refresh_max_age=max_age)
