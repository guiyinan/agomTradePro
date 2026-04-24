"""Realtime domain rules."""

from decimal import Decimal

from apps.realtime.domain.entities import PriceUpdateStatus


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
