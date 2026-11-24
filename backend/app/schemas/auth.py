import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

# E.164, e.g. +37120000000. Phone is required for both roles (OPEN_QUESTIONS Q-06 default).
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9]\d{7,14}$")]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class RegisterIn(BaseModel):
    email: EmailStr
    password: Password
    full_name: FullName
    phone: Phone


class GuestClientIn(BaseModel):
    """Ordering without a password: the client account is created from the contact details alone."""

    email: EmailStr
    full_name: FullName
    phone: Phone


class SetPasswordIn(BaseModel):
    password: Password
    # Required only when the account already has a password.
    current_password: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class SmsCodeRequestIn(BaseModel):
    phone: Phone


class SmsCodeVerifyIn(BaseModel):
    phone: Phone
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class LoginIn(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["client", "master", "admin"]
    email: str
    full_name: str
    phone: str | None
    status: Literal["active", "blocked"]
    has_password: bool
    master_approval_status: Literal["pending_approval", "approved", "rejected"] | None = None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut
