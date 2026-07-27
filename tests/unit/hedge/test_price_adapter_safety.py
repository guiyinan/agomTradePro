"""Hedge historical price adapter safety contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from django.core.cache import cache

from apps.hedge.infrastructure import adapters


@pytest.fixture(autouse=True)
def clear_hedge_cache() -> None:
    """Keep exact-scope cache assertions isolated."""

    cache.clear()


def test_cached_adapter_requires_exact_historical_scope() -> None:
    """A last-known-good series cannot leak across dates or window lengths."""

    target_date = date(2026, 7, 27)
    adapters._cache_hedge_prices("510300", target_date, 3, [1.0, 1.1, 1.2])
    cached = adapters.CachedHedgeAdapter()

    assert cached.get_asset_prices("510300", target_date, 3) == [1.0, 1.1, 1.2]
    assert cached.get_asset_prices("510300", date(2026, 7, 26), 3) is None
    assert cached.get_asset_prices("510300", target_date, 4) is None


def test_cached_adapter_rejects_legacy_lists_and_corrupt_prices() -> None:
    """Raw legacy cache values and non-finite/negative closes fail closed."""

    target_date = date(2026, 7, 27)
    key = adapters._cache_key("510300", target_date, 3)
    cache.set(key, [12.0])
    cached = adapters.CachedHedgeAdapter()

    assert cached.get_asset_prices("510300", target_date, 3) is None

    cache.set(
        key,
        {
            "asset_code": "510300",
            "end_date": target_date.isoformat(),
            "days": 3,
            "prices": [1.0, float("nan"), -1.0],
        },
    )
    assert cached.get_asset_prices("510300", target_date, 3) is None


def test_failover_rejects_fabricated_or_invalid_series_before_caching(monkeypatch) -> None:
    """Invalid fallback values never reach hedge analytics or last-known-good cache."""

    class InvalidSource:
        def get_asset_prices(
            self,
            asset_code: str,
            end_date: date,
            days: int = 60,
            *,
            cache_result: bool = True,
        ) -> list[float]:
            del asset_code, end_date, days, cache_result
            return [100.0, float("inf")]

    class ValidSource:
        def get_asset_prices(
            self,
            asset_code: str,
            end_date: date,
            days: int = 60,
            *,
            cache_result: bool = True,
        ) -> list[float]:
            del asset_code, end_date, days, cache_result
            return [100.0, 101.0]

    writes: list[list[float]] = []
    monkeypatch.setattr(
        adapters,
        "_cache_hedge_prices",
        lambda asset_code, end_date, days, prices: writes.append(prices),
    )
    adapter = adapters.FailoverHedgeAdapter([InvalidSource(), ValidSource()])

    assert adapter.get_asset_prices("510300", date(2026, 7, 27), 3) == [100.0, 101.0]
    assert writes == [[100.0, 101.0]]


def test_persisted_adapter_returns_real_ascending_closes() -> None:
    """The Data Center repository result is ordered for return calculations."""

    class Repository:
        def get_bars(
            self,
            asset_code: str,
            start: date | None = None,
            end: date | None = None,
            limit: int = 500,
        ) -> list[SimpleNamespace]:
            del asset_code, start, end, limit
            return [
                SimpleNamespace(close=3.0),
                SimpleNamespace(close=2.0),
                SimpleNamespace(close=1.0),
            ]

    adapter = adapters.TushareHedgeAdapter(Repository())

    assert adapter.get_asset_prices("510300", date(2026, 7, 27), 3) == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    ("asset_code", "end_date", "days"),
    [
        ("", date(2026, 7, 27), 3),
        ("510300", "2026-07-27", 3),
        ("510300", date(2026, 7, 27), 1),
        ("510300", date(2026, 7, 27), True),
    ],
)
def test_failover_rejects_invalid_requests_before_sources(
    asset_code: object,
    end_date: object,
    days: object,
) -> None:
    """Malformed dynamic inputs fail before any provider or cache access."""

    adapter = adapters.FailoverHedgeAdapter([])
    with pytest.raises(ValueError):
        adapter.get_asset_prices(
            cast(str, asset_code),
            cast(date, end_date),
            cast(int, days),
        )
