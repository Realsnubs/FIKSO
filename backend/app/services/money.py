"""Money rules (CLAUDE.md rule 5): Decimal only, EUR, 2 decimals, ROUND_HALF_UP."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def eur(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def labour_amount(hourly_rate: Decimal, minimum: Decimal, billable_seconds: int) -> Decimal:
    """labour = max(minimum, rate × billable hours) — owner decision; the minimum is a floor, not a
    surcharge."""
    by_time = eur(hourly_rate * Decimal(billable_seconds) / Decimal(3600))
    return max(eur(minimum), by_time)


def commission(rate: Decimal, labour: Decimal) -> Decimal:
    """Commission on the labour amount only; materials and external costs never enter the base."""
    return eur(rate * labour)
