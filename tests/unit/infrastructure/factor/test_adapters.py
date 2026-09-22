"""Tests for factor data adapters."""

from datetime import date

import pytest

from apps.factor.infrastructure.adapters import (
    AkshareFactorAdapter,
    CachedFactorAdapter,
    FactorDataSource,
    TushareFactorAdapter,
)


class FakePriceDataService:
    """Deterministic price service recording requested symbols."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_prices(
        self,
        stock_code: str,
        end_date: date,
        days: int,
        *,
        cache_result: bool = True,
    ) -> list[float]:
        del end_date, cache_result
        self.calls.append(stock_code)
        return [float(value) for value in range(1, days + 2)]


def test_cached_factor_adapter_reuses_computed_price_factor() -> None:
    """Repeated factor requests reuse the adapter-level calculation cache."""

    price_service = FakePriceDataService()
    adapter = CachedFactorAdapter(price_service, cache_price_results=False)
    trade_date = date(2026, 7, 24)

    first = adapter.get_factor_value("600000.SH", "momentum_1m", trade_date)
    second = adapter.get_factor_value("600000.SH", "momentum_1m", trade_date)

    assert first == second
    assert first is not None
    assert price_service.calls == ["600000.SH"]


def test_cached_factor_adapter_routes_beta_to_benchmark_calculation(
    monkeypatch,
) -> None:
    """Beta reaches the benchmark branch instead of falling through to None."""

    price_service = FakePriceDataService()
    adapter = CachedFactorAdapter(price_service, cache_price_results=False)
    monkeypatch.setattr(
        "apps.factor.infrastructure.adapters.get_runtime_benchmark_code",
        lambda _key: "000300.SH",
    )

    beta = adapter.get_factor_value("600000.SH", "beta", date(2026, 7, 24))

    assert beta is not None
    assert price_service.calls == ["600000.SH", "000300.SH"]


@pytest.mark.parametrize(
    ("adapter_type", "source"),
    [(TushareFactorAdapter, "tushare"), (AkshareFactorAdapter, "akshare")],
)
def test_financial_factor_uses_decision_knowledge_boundary(
    monkeypatch: pytest.MonkeyPatch,
    adapter_type: type[FactorDataSource],
    source: str,
) -> None:
    """Date-only factor requests enter the fail-closed decision query port."""

    seen: list[dict[str, object]] = []

    def _financials(stock_code: str, **kwargs: object) -> list[dict[str, object]]:
        seen.append({"stock_code": stock_code, **kwargs})
        return [
            {
                "period_end": "2026-06-30",
                "metric_code": "roe",
                "value": 0.2,
                "source": source,
            }
        ]

    monkeypatch.setattr(
        "apps.factor.infrastructure.adapters.get_financial_facts_for_decision",
        _financials,
    )
    trade_date = date(2026, 7, 24)

    value = adapter_type().get_factor_value("600000.SH", "roe", trade_date)

    assert value == 0.2
    assert seen == [
        {
            "stock_code": "600000.SH",
            "limit": 200,
            "decision_date": trade_date,
        }
    ]
