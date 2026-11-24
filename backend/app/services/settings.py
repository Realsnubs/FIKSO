"""Operational settings from `system_settings`, with code defaults as a safety net (never a second source)."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemSetting

DEFAULTS: dict[str, Any] = {
    "client_confirmation_minutes": {"immediate": 5, "reserved": 30},
    "master_response_minutes": {"immediate": 10, "reserved": 120},
    "matching": {
        "max_rounds": 3,
        "top_k": 10,
        "fallback_speed_kmh": 30,
        "alternative_margin_minutes": 10,
        "max_alternatives": 2,
        "location_fresh_minutes": 15,
    },
    # Q-D2-1 is open: working assumptions, editable by the admin without a deploy.
    "immediate_job_minutes": 120,
    "order_buffer_minutes": 0,
    "request_photos": {"max_files": 5, "max_bytes": 10 * 1024 * 1024},
    # Q-01 is open: no rounding until the owner approves a rule (see services/billable.py OPTIONS).
    "billable_time": {"rounding": "none", "step_minutes": 1},
    # Which working assumptions the owner has approved; everything starts unapproved.
    "policy_confirmation": {
        "billable_time": False,
        "immediate_job_minutes": False,
        "order_buffer_minutes": False,
    },
}

# Settings that are business policy not yet decided by the owner (shown as "not approved" until confirmed).
POLICIES = ("billable_time", "immediate_job_minutes", "order_buffer_minutes")


def unconfirmed_policies(db: Session) -> list[str]:
    confirmed = get(db, "policy_confirmation")
    return [key for key in POLICIES if not confirmed.get(key, False)]


def get(db: Session, key: str) -> Any:
    row = db.get(SystemSetting, key)
    if row is None:
        return DEFAULTS[key]
    default = DEFAULTS.get(key)
    if isinstance(default, dict) and isinstance(row.value, dict):
        return {**default, **row.value}
    return row.value


def all_settings(db: Session) -> dict[str, Any]:
    return {key: get(db, key) for key in DEFAULTS}
