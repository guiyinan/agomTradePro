"""Bridge helpers for shared historical price reads."""

from __future__ import annotations

from datetime import date, timedelta

from apps.data_center.infrastructure.repositories import PriceBarRepository


def fetch_close_prices_from_data_center(
    asset_code: str,
    end_date: date,
    days_back: int,
) -> list[float] | None:
    """Return close-price history from data_center facts, oldest to newest."""

    repo = PriceBarRepository()
    start_date = end_date - timedelta(days=days_back + 30)
    bars = repo.get_bars(asset_code, start=start_date, end=end_date)
    if not bars:
        return None
    prices = [float(bar.close) for bar in bars]
    return prices[-days_back:] if len(prices) > days_back else prices
