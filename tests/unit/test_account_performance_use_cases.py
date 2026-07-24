"""Performance application use-case correctness tests."""

from datetime import date

import pytest

from apps.simulated_trading.application.performance_use_cases import (
    GetAccountPerformanceReportUseCase,
)
from apps.simulated_trading.domain.services import PerformanceCalculatorService


class AccountRepo:
    def get_by_id(self, account_id: int) -> dict[str, object] | None:
        if account_id != 1:
            return None
        return {
            "account_id": 1,
            "initial_capital": 100.0,
            "start_date": date(2026, 1, 1),
            "account_type": "simulated",
        }


class DailyNetValueRepo:
    def list_range(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, object]]:
        return [
            {"record_date": date(2026, 1, 1), "total_value": 100.0},
            {"record_date": date(2026, 1, 2), "total_value": 101.0},
            {"record_date": date(2026, 1, 3), "total_value": 102.0},
        ]


class CashFlowRepo:
    def list_for_account(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, object]]:
        return []


class BenchmarkRepo:
    def list_active(self, account_id: int) -> list[dict[str, object]]:
        return [
            {"benchmark_code": "INDEX_A", "weight": 0.25},
            {"benchmark_code": "INDEX_B", "weight": 0.75},
        ]


class MarketDataRepo:
    def __init__(self, *, missing_code: str | None = None) -> None:
        self.missing_code = missing_code

    def get_index_cumulative_return(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> float | None:
        if index_code == self.missing_code:
            return None
        return {"INDEX_A": 10.0, "INDEX_B": 20.0}[index_code]

    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        if index_code == "INDEX_A":
            return [
                (date(2026, 1, 2), 0.01),
                (date(2026, 1, 3), 0.02),
            ]
        return [
            (date(2026, 1, 1), 0.99),
            (date(2026, 1, 2), 0.03),
            (date(2026, 1, 3), 0.04),
        ]


class TradeRepo:
    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, object]]:
        return []


def _use_case(*, missing_code: str | None = None) -> GetAccountPerformanceReportUseCase:
    return GetAccountPerformanceReportUseCase(
        account_repo=AccountRepo(),
        daily_net_value_repo=DailyNetValueRepo(),
        cash_flow_repo=CashFlowRepo(),
        benchmark_repo=BenchmarkRepo(),
        market_data_repo=MarketDataRepo(missing_code=missing_code),
        trade_history_repo=TradeRepo(),
    )


def test_composite_benchmark_aligns_components_and_portfolio_by_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[float]] = {}

    def capture_beta_alpha(
        portfolio_returns: list[float],
        benchmark_returns: list[float],
        annualized_portfolio_return: float,
        annualized_benchmark_return: float,
    ) -> tuple[float, float]:
        captured["portfolio"] = portfolio_returns
        captured["benchmark"] = benchmark_returns
        return 1.0, 0.0

    def capture_tracking_error(
        portfolio_returns: list[float],
        benchmark_returns: list[float],
    ) -> float:
        captured["tracking_portfolio"] = portfolio_returns
        captured["tracking_benchmark"] = benchmark_returns
        return 1.0

    monkeypatch.setattr(
        PerformanceCalculatorService,
        "calculate_beta_alpha",
        capture_beta_alpha,
    )
    monkeypatch.setattr(
        PerformanceCalculatorService,
        "calculate_tracking_error",
        capture_tracking_error,
    )

    report = _use_case().execute(
        account_id=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    assert report.benchmark is not None
    assert report.benchmark.benchmark_return == pytest.approx(17.5)
    assert captured["benchmark"] == pytest.approx([0.025, 0.035])
    assert captured["portfolio"] == pytest.approx([0.01, 1.0 / 101.0])
    assert captured["tracking_benchmark"] == pytest.approx([0.025, 0.035])


def test_missing_benchmark_component_does_not_publish_partial_return() -> None:
    report = _use_case(missing_code="INDEX_A").execute(
        account_id=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    assert report.benchmark is not None
    assert report.benchmark.benchmark_return is None
    assert report.benchmark.excess_return is None
    assert any("组合基准指标返回 null" in warning for warning in report.warnings)


def test_performance_report_rejects_reversed_date_range() -> None:
    with pytest.raises(ValueError, match="start_date"):
        _use_case().execute(
            account_id=1,
            start_date=date(2026, 1, 3),
            end_date=date(2026, 1, 1),
        )
