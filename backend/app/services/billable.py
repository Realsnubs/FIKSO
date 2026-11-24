"""Billable work time (Q-01): one central rule, configurable, explicitly marked as not yet approved.

Billable time is the sum of actual work segments (travel is never added, K-7). Whether and how it is
rounded is a commercial decision of the owner; the options are offered, the default applies no rounding,
and the setting carries `confirmed: false` until the owner approves a rule (admin UI, readiness check).
"""

import math
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.services import settings

Rounding = Literal["none", "up", "nearest", "down"]
ROUNDINGS: tuple[Rounding, ...] = ("none", "up", "nearest", "down")
# Options for the owner (Q-01). None of them is chosen by the system.
OPTIONS = {
    "A": {"rounding": "none", "step_minutes": 1, "note": "exact time, to the second"},
    "B": {"rounding": "up", "step_minutes": 15, "note": "every started 15 minutes"},
    "C": {"rounding": "nearest", "step_minutes": 15, "note": "nearest 15 minutes"},
    "D": {"rounding": "up", "step_minutes": 30, "note": "every started 30 minutes"},
}


@dataclass(frozen=True)
class Rule:
    rounding: Rounding
    step_minutes: int
    confirmed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"rounding": self.rounding, "step_minutes": self.step_minutes, "confirmed": self.confirmed}


def current_rule(db: Session) -> Rule:
    value = settings.get(db, "billable_time")
    confirmed = bool(settings.get(db, "policy_confirmation").get("billable_time", False))
    return Rule(value["rounding"], int(value["step_minutes"]), confirmed)


def apply(raw_seconds: int, rule: Rule) -> int:
    """Billable seconds from the actual work seconds. Boundaries are exact: 15:00 stays 15:00 with "up"."""
    raw_seconds = max(0, raw_seconds)
    if rule.rounding == "none" or rule.step_minutes <= 0:
        return raw_seconds
    step = rule.step_minutes * 60
    if rule.rounding == "up":
        return math.ceil(raw_seconds / step) * step
    if rule.rounding == "down":
        return (raw_seconds // step) * step
    # nearest: half a step rounds up (ROUND_HALF_UP, like money)
    return ((raw_seconds + step // 2) // step) * step
