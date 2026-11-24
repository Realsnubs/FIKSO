from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.auth import UserOut


class AdminUserOut(UserOut):
    blocked_reason: str | None
    last_login_at: datetime | None


class BlockUserIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
