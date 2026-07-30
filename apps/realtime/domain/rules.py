"""Realtime domain rules."""

from datetime import date, timedelta
from decimal import Decimal

from apps.realtime.domain.entities import AlertCondition, PriceUpdateStatus


def daily_market_observation_status(
    observed_at: date,
    *,
    as_of_date: date,
    max_business_days: int = 1,
) -> tuple[bool, int]:
    """Return stale state and weekday age for one daily market observation."""

    if max_business_days < 0:
        raise ValueError("max_business_days must be non-negative")
    if observed_at > as_of_date:
        return (True, 0)
    current = observed_at + timedelta(days=1)
    age = 0
    while current <= as_of_date:
        if current.weekday() < 5:
            age += 1
        current += timedelta(days=1)
    return (age > max_business_days, age)


def should_trigger_alert(
    condition: AlertCondition,
    threshold: Decimal,
    old_price: Decimal | None,
    new_price: Decimal,
) -> bool:
    """Evaluate a price-alert condition without converting Decimal values."""

    if condition is AlertCondition.ABOVE:
        return new_price >= threshold
    if condition is AlertCondition.BELOW:
        return new_price <= threshold
    if old_price is None:
        return False
    if condition is AlertCondition.CROSS_UP:
        return old_price < threshold <= new_price
    if condition is AlertCondition.CROSS_DOWN:
        return old_price > threshold >= new_price
    return False


def classify_price_update(
    old_price: Decimal | None,
    new_price: Decimal | None,
) -> PriceUpdateStatus:
    """Classify a price update from old/new price values."""
    if new_price is None:
        return PriceUpdateStatus.FAILED
    if old_price is None:
        return PriceUpdateStatus.SUCCESS
    if old_price == new_price:
        return PriceUpdateStatus.NO_CHANGE
    return PriceUpdateStatus.SUCCESS


def calculate_change_pct(
    old_price: Decimal | None,
    new_price: Decimal | None,
) -> Decimal | None:
    """Calculate percentage price change when both prices are available."""
    if old_price is None or new_price is None or old_price == 0:
        return None
    return (new_price - old_price) / old_price * Decimal(100)
