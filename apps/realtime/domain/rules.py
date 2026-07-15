"""Realtime domain rules."""

from decimal import Decimal

from apps.realtime.domain.entities import AlertCondition, PriceUpdateStatus


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
