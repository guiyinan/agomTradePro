"""Read-side boundaries for fee-correction-aware performance projections."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from apps.simulated_trading.application.performance_use_cases import (
    GetAccountPerformanceReportUseCase,
)
from apps.simulated_trading.application.use_cases import AccountPerformanceResult
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.domain.services import PerformanceCalculatorService
from apps.simulated_trading.interface.performance_account_payload import (
    apply_account_performance_projection,
)


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=41,
        account_name="performance read boundary",
        account_type=AccountType.SIMULATED,
        initial_capital=100.0,
        current_cash=60.0,
        current_market_value=50.0,
        total_value=110.0,
        total_return=35.0,
        annual_return=12.0,
        max_drawdown=8.0,
        sharpe_ratio=1.4,
        win_rate=80.0,
        total_trades=10,
        winning_trades=8,
        start_date=date(2025, 1, 1),
    )


def test_performance_api_payload_uses_same_projection_for_nested_account_metrics() -> None:
    performance = {
        "total_return": None,
        "annual_return": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "win_rate": None,
    }
    original_performance = {
        "total_return": 35.0,
        "annual_return": 12.0,
        "max_drawdown": 8.0,
        "sharpe_ratio": 1.4,
        "win_rate": 80.0,
    }
    result: AccountPerformanceResult = {
        "account": _account(),
        "positions": [],
        "total_positions": 0,
        "total_trades": 3,
        "winning_trades": None,
        "win_rate": None,
        "win_rate_known": False,
        "performance": performance,
        "original_performance": original_performance,
        "performance_metrics_known": False,
        "performance_reason_code": "FEE_CORRECTION_HISTORY_UNKNOWN",
        "performance_source": "unknown",
    }

    original_payload = {
        "total_return": 35.0,
        "annual_return": 12.0,
        "max_drawdown": 8.0,
        "sharpe_ratio": 1.4,
        "win_rate": 80.0,
        "total_trades": 10,
        "winning_trades": 8,
        "realized_trade_metrics_known": True,
    }
    nested_account = apply_account_performance_projection(original_payload, result)

    assert nested_account["total_return"] is None
    assert nested_account["annual_return"] is None
    assert nested_account["max_drawdown"] is None
    assert nested_account["sharpe_ratio"] is None
    assert nested_account["win_rate"] is None
    assert nested_account["winning_trades"] is None
    assert nested_account["total_trades"] == 3
    assert nested_account["realized_trade_metrics_known"] is False
    assert original_payload["total_return"] == 35.0


class _ReportAccountRepository:
    def get_by_id(self, account_id: int) -> dict[str, Any]:
        return {"initial_capital": 100.0, "account_type": "simulated"}


class _ReportDailyRepository:
    def __init__(
        self,
        correction_date: date | None,
        records: list[dict[str, Any]] | None = None,
    ) -> None:
        self.correction_date = correction_date
        self.records = (
            records
            if records is not None
            else [
                {
                    "record_date": date(2025, 1, 1),
                    "total_value": 100.0,
                    "correction_coverage_known": True,
                },
                {
                    "record_date": date(2026, 1, 1),
                    "total_value": 110.0,
                    "correction_coverage_known": True,
                },
            ]
        )
        self.calls: list[tuple[int, date | None, date | None]] = []

    def list_range(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((account_id, start_date, end_date))
        rows = [dict(row) for row in self.records]
        if end_date is not None:
            rows = [row for row in rows if row["record_date"] <= end_date]
        if start_date is not None:
            rows = [row for row in rows if row["record_date"] >= start_date]
        if (
            rows
            and self.correction_date is not None
            and end_date is not None
            and self.correction_date <= end_date
            and self.correction_date > date(2026, 1, 1)
        ):
            rows[-1]["fee_correction_after_last_daily_snapshot"] = True
        return rows

    def get_record_for_date(
        self,
        account_id: int,
        record_date: date,
    ) -> dict[str, Any] | None:
        return None


class _ReportCashFlowRepository:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self.records = (
            records if records is not None else [{"flow_date": date(2025, 1, 1), "amount": 100.0}]
        )

    def list_for_account(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self.records]
        if start_date is not None:
            rows = [row for row in rows if row["flow_date"] >= start_date]
        if end_date is not None:
            rows = [row for row in rows if row["flow_date"] <= end_date]
        return rows


class _ReportBenchmarkRepository:
    def list_active(self, account_id: int) -> list[dict[str, Any]]:
        return []


class _ReportMarketDataRepository:
    pass


class _ReportTradeRepository:
    def list_closed_trades(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        return []


def _performance_report(
    correction_date: date | None,
    end_date: date,
    *,
    start_date: date = date(2025, 1, 1),
    daily_repository: _ReportDailyRepository | None = None,
    cash_flow_repository: _ReportCashFlowRepository | None = None,
) -> Any:
    daily_repository = daily_repository or _ReportDailyRepository(correction_date)
    return GetAccountPerformanceReportUseCase(
        _ReportAccountRepository(),
        daily_repository,
        cash_flow_repository or _ReportCashFlowRepository(),
        _ReportBenchmarkRepository(),
        _ReportMarketDataRepository(),
        _ReportTradeRepository(),
    ).execute(41, start_date, end_date)


def test_performance_report_blocks_metrics_when_correction_is_after_last_snapshot() -> None:
    daily_repository = _ReportDailyRepository(date(2026, 1, 3))
    report = _performance_report(
        date(2026, 1, 3),
        date(2026, 1, 5),
        daily_repository=daily_repository,
    )

    assert daily_repository.calls == [(41, None, date(2026, 1, 5))]
    assert report.period.end_date == date(2026, 1, 5)
    assert report.coverage.data_end == date(2026, 1, 1)
    assert report.returns.twr is None
    assert report.returns.annualized_twr is None
    assert report.returns.mwr is None
    assert report.returns.annualized_mwr is None
    assert report.risk.volatility is None
    assert report.risk.downside_volatility is None
    assert report.risk.max_drawdown is None
    assert report.ratios.sharpe is None
    assert report.ratios.sortino is None
    assert report.ratios.calmar is None
    assert report.ratios.treynor is None
    assert any(
        warning.startswith("FEE_CORRECTION_AFTER_LAST_DAILY_SNAPSHOT:")
        for warning in report.coverage.warnings
    )


def test_performance_report_ending_before_correction_keeps_existing_calculation() -> None:
    with_correction_history = _performance_report(date(2026, 1, 3), date(2026, 1, 2))
    without_correction_history = _performance_report(None, date(2026, 1, 2))

    assert with_correction_history == without_correction_history
    assert with_correction_history.returns.twr is not None
    assert with_correction_history.risk.max_drawdown is not None
    assert not any(
        warning.startswith("FEE_CORRECTION_AFTER_LAST_DAILY_SNAPSHOT:")
        for warning in with_correction_history.coverage.warnings
    )


def test_performance_report_detects_late_correction_when_window_has_no_daily_rows() -> None:
    daily_repository = _ReportDailyRepository(date(2026, 1, 3))
    report = _performance_report(
        date(2026, 1, 3),
        date(2026, 1, 5),
        start_date=date(2026, 1, 2),
        daily_repository=daily_repository,
    )

    assert daily_repository.calls == [(41, None, date(2026, 1, 5))]
    assert report.returns.twr is None
    assert any(
        warning.startswith("FEE_CORRECTION_AFTER_LAST_DAILY_SNAPSHOT:")
        for warning in report.coverage.warnings
    )


def test_performance_report_uses_observed_dates_for_xirr_and_annualization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xirr_inputs: list[tuple[float, date]] = []
    annualization_days: list[int] = []

    def _capture_xirr(
        cashflows: list[tuple[date, float]],
        terminal_value: float,
        terminal_date: date,
    ) -> float:
        del cashflows
        xirr_inputs.append((terminal_value, terminal_date))
        return 7.5

    def _capture_annualized_twr(twr_pct: float, days: int) -> float:
        del twr_pct
        annualization_days.append(days)
        return 8.5

    monkeypatch.setattr(PerformanceCalculatorService, "calculate_xirr", _capture_xirr)
    monkeypatch.setattr(
        PerformanceCalculatorService,
        "calculate_annualized_twr",
        _capture_annualized_twr,
    )

    report = _performance_report(None, date(2026, 1, 5))

    assert report.period.end_date == date(2026, 1, 5)
    assert report.period.days == 369
    assert report.coverage.data_start == date(2025, 1, 1)
    assert report.coverage.data_end == date(2026, 1, 1)
    assert annualization_days == [365]
    assert xirr_inputs == [(110.0, date(2026, 1, 1))]
    assert report.returns.annualized_twr == 8.5
    assert report.returns.mwr == 7.5
    assert any(
        warning.startswith("DAILY_OBSERVATION_WINDOW_DIFFERS_FROM_REQUEST:")
        for warning in report.coverage.warnings
    )


def test_performance_report_blocks_metrics_when_cashflow_follows_last_snapshot() -> None:
    report = _performance_report(
        None,
        date(2026, 1, 5),
        cash_flow_repository=_ReportCashFlowRepository(
            [
                {"flow_date": date(2025, 1, 1), "amount": 100.0},
                {"flow_date": date(2026, 1, 3), "amount": 20.0},
            ]
        ),
    )

    assert report.returns.twr is None
    assert report.returns.annualized_twr is None
    assert report.returns.mwr is None
    assert report.returns.annualized_mwr is None
    assert report.risk.volatility is None
    assert report.risk.downside_volatility is None
    assert report.risk.max_drawdown is None
    assert report.ratios.sharpe is None
    assert report.ratios.sortino is None
    assert report.ratios.calmar is None
    assert report.ratios.treynor is None
    assert any(
        warning.startswith("CASHFLOW_AFTER_LAST_DAILY_SNAPSHOT:")
        for warning in report.coverage.warnings
    )


@pytest.mark.parametrize(
    "cashflows",
    [
        [],
        [{"flow_date": date(2026, 1, 4), "amount": 20.0}],
    ],
    ids=["without-cashflow", "with-cashflow"],
)
def test_performance_report_with_empty_daily_window_reports_missing_endpoint(
    cashflows: list[dict[str, Any]],
) -> None:
    report = _performance_report(
        None,
        date(2026, 1, 5),
        start_date=date(2026, 1, 2),
        cash_flow_repository=_ReportCashFlowRepository(cashflows),
    )

    assert report.coverage.data_start is None
    assert report.coverage.data_end is None
    assert report.returns.twr is None
    assert report.returns.mwr is None
    assert report.risk.max_drawdown is None
    assert any(
        warning.startswith("NO_DAILY_VALUE_OBSERVATIONS:") for warning in report.coverage.warnings
    )
    if cashflows:
        assert any(
            warning.startswith("DAILY_TERMINAL_OBSERVATION_MISSING:")
            for warning in report.coverage.warnings
        )
        assert not any("无外部现金流记录" in warning for warning in report.coverage.warnings)
    else:
        assert not any(
            warning.startswith("DAILY_TERMINAL_OBSERVATION_MISSING:")
            for warning in report.coverage.warnings
        )


def test_performance_report_full_observation_window_keeps_existing_results() -> None:
    report = _performance_report(None, date(2026, 1, 1))

    assert report.period.days == 365
    assert report.coverage.data_start == report.period.start_date
    assert report.coverage.data_end == report.period.end_date
    assert report.returns.twr == pytest.approx(10.0)
    assert report.returns.annualized_twr == pytest.approx(10.0)
    assert report.returns.mwr is not None
    assert not any(
        warning.startswith("DAILY_OBSERVATION_WINDOW_DIFFERS_FROM_REQUEST:")
        for warning in report.coverage.warnings
    )
