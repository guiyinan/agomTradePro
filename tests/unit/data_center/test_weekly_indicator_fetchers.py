"""Fail-closed tests for semantically incompatible weekly proxies."""

from __future__ import annotations

from datetime import date

from apps.data_center.infrastructure.macro_sources.fetchers.weekly_indicators_fetchers import (
    WeeklyIndicatorFetcher,
)


class RejectEndpointCalls:
    """Ensure rejected proxy endpoints are never queried."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"proxy endpoint must not be called: {name}")


def test_weekly_proxy_routes_fail_closed_without_calling_endpoints() -> None:
    fetcher = WeeklyIndicatorFetcher(
        RejectEndpointCalls(),
        "akshare",
        lambda point: None,
        lambda points: points,
    )
    start_date = date(2026, 1, 1)
    end_date = date(2026, 7, 25)

    assert fetcher.fetch_power_generation(start_date, end_date) == []
    assert fetcher.fetch_blast_furnace_utilization(start_date, end_date) == []
    assert fetcher.fetch_ccfi(start_date, end_date) == []
    assert fetcher.fetch_scfi(start_date, end_date) == []
