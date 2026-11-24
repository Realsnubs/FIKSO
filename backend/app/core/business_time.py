"""Business calendar date (ARCHITECTURE §6b "Qualification validity").

Dates that have a business meaning (qualification `valid_until`, later commission periods) are calendar days
in Europe/Riga. "Today" is always computed by the database from one clock and one zone, so the API,
eligibility checks and tests never disagree about which day it is.
"""

from datetime import date, datetime

from sqlalchemy import Date, func, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

BUSINESS_TIMEZONE = "Europe/Riga"


def business_today_sql(at: datetime | None = None) -> ColumnElement[date]:
    """SQL expression for the Riga calendar date at `at` (default: the transaction's `now()`)."""
    # A naive datetime would be read as local time by timezone(); only absolute instants are meaningful.
    if at is not None and at.tzinfo is None:
        raise ValueError("business_today needs a timezone-aware instant")
    instant = func.now() if at is None else literal(at)
    return func.timezone(BUSINESS_TIMEZONE, instant).cast(Date)


def business_today(db: Session, at: datetime | None = None) -> date:
    today: date | None = db.scalar(select(business_today_sql(at)))
    assert today is not None
    return today
