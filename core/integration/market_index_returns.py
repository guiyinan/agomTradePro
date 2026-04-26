"""Bridge helpers for market index return access."""

from __future__ import annotations

from datetime import date


def fetch_index_daily_returns(*, index_code: str, start_date: date, end_date: date) -> dict:
    """Return daily index returns through the owning equity adapter."""

    from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter

    return MarketDataRepositoryAdapter().get_index_daily_returns(
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
    )
