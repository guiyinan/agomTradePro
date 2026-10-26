"""Daily net-value API must not relabel stale stored metrics as corrected values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.simulated_trading.application.daily_net_value_service import DailyNetValueService
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount


class _DailyRepository:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.requested_range: tuple[date | None, date | None] | None = None

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        del account_id
        self.requested_range = (start_date, end_date)
        return list(self.records)


class _AccountRepository:
    def get_by_id(self, account_id: int) -> SimulatedAccount:
        del account_id
        return SimulatedAccount(
            account_id=1,
            account_name="curve-test",
            account_type=AccountType.SIMULATED,
            initial_capital=100.0,
            current_cash=100.0,
            current_market_value=0.0,
            total_value=100.0,
            start_date=date(2026, 10, 1),
        )


def _record(day: int, value: str, *, overlay: bool, known: bool = True) -> dict[str, Any]:
    return {
        "record_date": date(2026, 10, day),
        "net_value": Decimal(value),
        "cash": Decimal(value),
        "market_value": Decimal("0.00"),
        "daily_return": -77.0,
        "cumulative_return": 88.0,
        "drawdown": 99.0,
        "total_trades": 0,
        "positions_count": 0,
        "correction_event_watermark": 0,
        "correction_event_watermark_sha256": "0" * 64,
        "correction_coverage_known": known,
        "correction_overlay_applied": overlay,
    }


def test_curve_recalculates_the_full_history_then_returns_requested_window() -> None:
    repo = _DailyRepository(
        [
            _record(1, "100.00", overlay=False),
            _record(2, "80.00", overlay=True),
            _record(3, "90.00", overlay=False),
        ]
    )
    service = DailyNetValueService(_AccountRepository(), object(), object(), repo)  # type: ignore[arg-type]

    points = service.get_equity_curve(1, start_date=date(2026, 10, 2))

    assert repo.requested_range == (None, None)
    assert [point["daily_return"] for point in points] == [-20.0, 12.5]
    assert [point["cumulative_return"] for point in points] == [-20.0, -10.0]
    assert [point["drawdown"] for point in points] == [20.0, 10.0]
    assert points[0]["original_daily_return"] == -77.0
    assert points[0]["effective_metrics_known"] is True
    assert points[0]["effective_metrics_reason_code"] is None


def test_curve_marks_uncovered_corrected_rows_unknown_instead_of_returning_old_metrics() -> None:
    repo = _DailyRepository(
        [
            _record(1, "100.00", overlay=False),
            _record(2, "80.00", overlay=False, known=False),
            _record(3, "90.00", overlay=False),
        ]
    )
    service = DailyNetValueService(_AccountRepository(), object(), object(), repo)  # type: ignore[arg-type]

    points = service.get_equity_curve(1)

    assert points[1]["daily_return"] is None
    assert points[1]["cumulative_return"] is None
    assert points[1]["drawdown"] is None
    assert points[2]["daily_return"] is None
    assert points[1]["original_daily_return"] == -77.0
    assert points[1]["effective_metrics_known"] is False
    assert points[1]["effective_metrics_reason_code"] == "FEE_CORRECTION_COVERAGE_UNKNOWN"
