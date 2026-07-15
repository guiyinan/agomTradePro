"""Register Realtime price access for Data Center."""

from __future__ import annotations

from typing import Any

from apps.data_center.application.business_runtime_gateway import (
    register_realtime_price_fetcher,
)

from . import price_polling_service


def _fetch_latest_prices(asset_codes: list[str]) -> list[dict[str, Any]]:
    return price_polling_service.PricePollingUseCase().get_latest_prices(asset_codes)


def register_realtime_data_center_runtime() -> None:
    """Register the Realtime latest-price provider."""

    register_realtime_price_fetcher(_fetch_latest_prices)


__all__ = ["register_realtime_data_center_runtime"]
