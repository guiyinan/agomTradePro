"""Tests for factor data adapters."""

from datetime import date

from apps.factor.infrastructure.adapters import CachedFactorAdapter


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
