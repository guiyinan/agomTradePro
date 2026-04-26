"""Bridge helpers for realtime price access."""

from __future__ import annotations

from typing import Any

from apps.realtime.application.price_polling_service import PricePollingUseCase


def fetch_latest_prices(asset_codes: list[str]) -> list[dict[str, Any]]:
    """Return latest realtime prices for the given asset codes."""

    return PricePollingUseCase().get_latest_prices(asset_codes)
