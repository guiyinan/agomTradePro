"""Account performance exposes raw stored values separately from effective results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from apps.simulated_trading.application.use_cases import GetAccountPerformanceUseCase
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount


class _AccountRepository:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if account_id == self.account.account_id else None


class _PositionRepository:
    def get_by_account(self, account_id: int) -> list[object]:
        del account_id
        return []


class _TradeRepository:
    def __init__(self, *, correction_event: bool) -> None:
        self.correction_event = correction_event

    def get_account_history(self, *, account_id: int, as_of: datetime) -> SimpleNamespace:
        del account_id, as_of
        event = SimpleNamespace(posting_date=date(2026, 10, 2))
        events = (event,) if self.correction_event else ()
        return SimpleNamespace(trades=(), cash_events=events)

    def get_by_account(self, account_id: int) -> list[object]:
        del account_id
        return []


class _DailyRepository:
    def __init__(self, *, covered: bool, current_value_matches: bool) -> None:
        self.covered = covered
        self.current_value_matches = current_value_matches

    def list_daily_records(self, account_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        del account_id, kwargs
        last_value = Decimal("900.00" if self.current_value_matches else "850.00")
        return [
            {
                "record_date": date(2026, 10, day),
                "net_value": value,
                "cash": value,
                "market_value": Decimal("0.00"),
                "daily_return": daily,
                "cumulative_return": cumulative,
                "drawdown": drawdown,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 0,
                "correction_event_watermark_sha256": "0" * 64,
                "correction_coverage_known": self.covered,
                "correction_overlay_applied": day == 2,
            }
            for day, value, daily, cumulative, drawdown in (
                (1, Decimal("1000.00"), 0.0, 0.0, 0.0),
                (2, Decimal("800.00"), -20.0, -20.0, 20.0),
                (3, last_value, 12.5, -10.0, 10.0),
            )
        ]


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=5,
        account_name="private-test-account",
        account_type=AccountType.SIMULATED,
        initial_capital=1000.0,
        current_cash=900.0,
        current_market_value=0.0,
        total_value=900.0,
        total_return=40.0,
        annual_return=30.0,
        max_drawdown=2.0,
        sharpe_ratio=3.0,
        start_date=date(2026, 10, 1),
    )


def _use_case(
    *,
    covered: bool,
    current_value_matches: bool,
    correction_event: bool = True,
) -> GetAccountPerformanceUseCase:
    account = _account()
    return GetAccountPerformanceUseCase(
        _AccountRepository(account),
        _PositionRepository(),
        _TradeRepository(correction_event=correction_event),
        _DailyRepository(covered=covered, current_value_matches=current_value_matches),
    )


def test_complete_corrected_daily_history_replaces_stale_account_metrics() -> None:
    result = _use_case(covered=True, current_value_matches=True).execute(5)

    assert result["original_performance"] == {
        "total_return": 40.0,
        "annual_return": 30.0,
        "max_drawdown": 2.0,
        "sharpe_ratio": 3.0,
        "win_rate": 0.0,
    }
    assert result["performance"]["total_return"] == -10.0
    assert result["performance"]["annual_return"] < -99.99
    assert result["performance"]["max_drawdown"] == 20.0
    assert result["performance"]["sharpe_ratio"] is not None
    assert result["performance"]["sharpe_ratio"] != 3.0
    assert result["performance"]["win_rate"] == 0.0
    assert result["performance_metrics_known"] is True
    assert result["performance_reason_code"] is None
    assert result["performance_source"] == "corrected_daily_history"


def test_uncovered_or_stale_history_does_not_expose_persisted_values_as_effective() -> None:
    for result in (
        _use_case(covered=False, current_value_matches=True).execute(5),
        _use_case(covered=True, current_value_matches=False).execute(5),
    ):
        assert result["original_performance"]["total_return"] == 40.0
        assert result["performance"] == {
            "total_return": None,
            "annual_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None,
            "win_rate": 0.0,
        }
        assert result["performance_metrics_known"] is False
        assert result["performance_reason_code"] == "FEE_CORRECTION_PERFORMANCE_HISTORY_UNKNOWN"
        assert result["performance_source"] == "unknown"


def test_unadjusted_account_keeps_legacy_performance_values() -> None:
    result = _use_case(
        covered=True,
        current_value_matches=True,
        correction_event=False,
    ).execute(5)

    assert result["performance"] == {
        "total_return": 40.0,
        "annual_return": 30.0,
        "max_drawdown": 2.0,
        "sharpe_ratio": 3.0,
        "win_rate": 0.0,
    }
    assert result["performance_metrics_known"] is True
    assert result["performance_reason_code"] is None
    assert result["performance_source"] == "account_snapshot"
