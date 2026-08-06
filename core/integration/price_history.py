"""Bridge helpers for shared historical price reads."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, timedelta

from apps.data_center.application.public import (
    fetch_close_price_series as _fetch_close_price_series,
)
from apps.data_center.application.public import fetch_close_prices as _fetch_close_prices
from apps.data_center.application.public import (
    get_published_price_bar_series,
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


def fetch_published_close_prices_from_data_center(
    asset_code: str,
    end_date: date,
    days_back: int,
) -> dict[str, object]:
    """Return close prices behind the canonical current-price publication gate.

    The historical bridge above intentionally reads the canonical fact store
    directly for replay/backtest callers.  Current decision consumers must use
    this envelope instead: Data Center performs the publication and freshness
    check first, and a missing/stale gate therefore yields an empty ``prices``
    list while preserving the block metadata for the caller.
    """

    if days_back <= 0:
        return {
            "prices": [],
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "invalid_days_back",
        }

    start_date = end_date - timedelta(days=days_back + 30)
    payload = get_published_price_bar_series(
        asset_code=asset_code,
        publication_key="current",
        start=start_date,
        end=end_date,
        limit=max(days_back + 30, 500),
    )
    rows_value = payload.get("rows")
    if bool(payload.get("must_not_use_for_decision")):
        rows_value = []
    rows = rows_value if isinstance(rows_value, list) else []
    prices: list[float] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        close = row.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        close_value = float(close)
        if math.isfinite(close_value):
            prices.append(close_value)

    result = dict(payload)
    result["prices"] = prices[-days_back:]
    return result
