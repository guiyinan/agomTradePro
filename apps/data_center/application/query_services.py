"""Application-level query helpers for cross-app data-center access."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.application.repository_provider import (
    get_data_center_diagnostic_repository,
    get_macro_fact_cache_warmup_repository,
    get_macro_fact_repository,
    get_market_thermometer_snapshot_repository,
    get_price_bar_repository,
)


def get_data_center_diagnostic_summary() -> dict[str, int]:
    """Return data-center summary counts for operational diagnostics."""

    return get_data_center_diagnostic_repository().get_summary()


def macro_fact_exists_on_or_before(reporting_period: date) -> bool:
    """Return whether macro data exists on or before the reporting period."""

    return get_data_center_diagnostic_repository().macro_fact_exists_on_or_before(
        reporting_period
    )


def get_latest_macro_indicator_value(indicator_code: str) -> float | None:
    """Return the latest canonical macro indicator value for one code."""

    latest = get_macro_fact_repository().get_latest(indicator_code)
    return float(latest.value) if latest is not None else None


def list_latest_macro_indicator_payloads(limit: int = 50) -> list[dict[str, Any]]:
    """Return latest macro indicator payloads for cache warmup."""

    return [
        {
            "indicator_code": fact.indicator_code,
            "value": float(fact.value),
            "reporting_period": str(fact.reporting_period),
        }
        for fact in get_macro_fact_cache_warmup_repository().list_latest_by_indicator(
            limit=limit
        )
    ]


def get_latest_market_thermometer_snapshot_payload() -> dict[str, Any] | None:
    """Return the latest market thermometer snapshot as a JSON-safe payload."""

    snapshot = get_market_thermometer_snapshot_repository().get_latest()
    return snapshot.to_dict() if snapshot is not None else None


def fetch_close_price_series(
    *,
    asset_code: str,
    start_date: date,
    end_date: date,
    limit: int = 5000,
) -> list[tuple[date, float]]:
    """Return close-price history from data-center facts, oldest to newest."""

    bars = get_price_bar_repository().get_bars(
        asset_code,
        start=start_date,
        end=end_date,
        limit=limit,
    )
    return [(bar.bar_date, float(bar.close)) for bar in reversed(bars)]


def fetch_close_prices(
    *,
    asset_code: str,
    start_date: date,
    end_date: date,
) -> list[float] | None:
    """Return close prices from data-center facts, oldest to newest."""

    bars = get_price_bar_repository().get_bars(asset_code, start=start_date, end=end_date)
    if not bars:
        return None
    return [float(bar.close) for bar in bars]
