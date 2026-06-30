"""Bridge helpers for shared historical price reads."""

from __future__ import annotations

from datetime import date, timedelta

from apps.data_center.application.query_services import (
    fetch_close_price_series as _fetch_close_price_series,
)
from apps.data_center.application.query_services import (
    fetch_close_prices as _fetch_close_prices,
)


def fetch_close_price_series_from_data_center(
    asset_code: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    """Return close-price history from data_center facts, oldest to newest."""

    return _fetch_close_price_series(
        asset_code=asset_code,
        start_date=start_date,
        end_date=end_date,
        limit=5000,
    )


def fetch_close_prices_from_data_center(
    asset_code: str,
    end_date: date,
    days_back: int,
) -> list[float] | None:
    """Return close-price history from data_center facts, oldest to newest."""

    start_date = end_date - timedelta(days=days_back + 30)
    prices = _fetch_close_prices(
        asset_code=asset_code,
        start_date=start_date,
        end_date=end_date,
    )
    if not prices:
        return None
    return prices[-days_back:] if len(prices) > days_back else prices
