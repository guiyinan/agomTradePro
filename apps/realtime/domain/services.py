"""Realtime domain services."""

from decimal import Decimal

from apps.realtime.domain.entities import PriceUpdate, PriceUpdateStatus
from apps.realtime.domain.rules import calculate_change_pct, classify_price_update


def build_price_update(
    *,
    asset_code: str,
    old_price: Decimal | None,
    new_price: Decimal | None,
    timestamp,
    error_message: str | None = None,
) -> PriceUpdate:
    """Build a price update entity from old/new prices."""
    status = classify_price_update(old_price, new_price)
    return PriceUpdate(
        asset_code=asset_code,
        old_price=old_price,
        new_price=new_price,
        status=status if error_message is None else PriceUpdateStatus.FAILED,
        timestamp=timestamp,
        error_message=error_message,
    )


__all__ = ["build_price_update", "calculate_change_pct", "classify_price_update"]
