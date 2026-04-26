"""Bridge helpers for realtime price polling workflows."""

from __future__ import annotations

from apps.realtime.application.price_polling_service import PricePollingUseCase


def execute_realtime_price_polling() -> dict:
    """Execute one realtime price-polling cycle and return the snapshot payload."""

    return PricePollingUseCase().execute_price_polling()
