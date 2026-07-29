"""Completed-backtest persistence boundary regressions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast

import pytest

from apps.backtest.domain.entities import BacktestCompletionPayload
from apps.backtest.infrastructure.models import BacktestResultModel


def _completion_payload() -> BacktestCompletionPayload:
    """Return one valid mutable payload for boundary tests."""

    return {
        "total_return": 0.12,
        "annualized_return": 0.08,
        "max_drawdown": 0.05,
        "sharpe_ratio": 1.2,
        "equity_curve": [{"date": "2026-01-01", "value": 112_000.0}],
        "regime_history": [
            {
                "date": "2026-01-01",
                "regime": "RECOVERY",
                "confidence": 0.8,
                "portfolio_value": 112_000.0,
            }
        ],
        "trades": [
            {
                "trade_date": "2026-01-01",
                "asset_class": "EQUITY",
                "action": "buy",
            }
        ],
        "warnings": ["price fallback"],
    }


@pytest.fixture
def pending_backtest(db: object) -> BacktestResultModel:
    """Persist one pending result that can cross the completion boundary."""

    del db
    return BacktestResultModel._default_manager.create(
        name="boundary-test",
        status="pending",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        initial_capital=Decimal("100000.00"),
        rebalance_frequency="monthly",
    )


def test_mark_completed_persists_exact_decimal_and_detached_json(
    pending_backtest: BacktestResultModel,
) -> None:
    """Valid completion evidence is detached from caller-owned containers."""

    payload = _completion_payload()
    pending_backtest.mark_completed(112000.25, payload)
    payload["equity_curve"][0]["value"] = 0.0
    payload["warnings"].append("mutated")

    pending_backtest.refresh_from_db()
    assert pending_backtest.status == "completed"
    assert pending_backtest.final_capital == Decimal("112000.25")
    assert pending_backtest.equity_curve[0]["value"] == 112_000.0
    assert pending_backtest.warnings == ["price fallback"]
    assert pending_backtest.completed_at is not None


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("total_return", float("nan")),
        ("annualized_return", float("inf")),
        ("max_drawdown", float("-inf")),
        ("sharpe_ratio", True),
    ],
)
def test_mark_completed_rejects_non_finite_or_boolean_metrics_without_partial_write(
    pending_backtest: BacktestResultModel,
    field_name: str,
    invalid_value: object,
) -> None:
    """Damaged metrics cannot publish a partially completed result."""

    dynamic_payload: dict[str, object] = dict(_completion_payload())
    dynamic_payload[field_name] = invalid_value
    payload = cast(BacktestCompletionPayload, dynamic_payload)

    with pytest.raises(ValueError, match=field_name):
        pending_backtest.mark_completed(112000.25, payload)

    pending_backtest.refresh_from_db()
    assert pending_backtest.status == "pending"
    assert pending_backtest.final_capital is None


def test_mark_completed_rejects_nested_non_finite_json(
    pending_backtest: BacktestResultModel,
) -> None:
    """NaN nested in the curve is rejected before any evidence mutation."""

    payload = _completion_payload()
    payload["equity_curve"][0]["value"] = float("nan")

    with pytest.raises(ValueError, match="equity_curve"):
        pending_backtest.mark_completed(112000.25, payload)

    pending_backtest.refresh_from_db()
    assert pending_backtest.status == "pending"


def test_mark_completed_rejects_non_json_and_invalid_warning_payloads(
    pending_backtest: BacktestResultModel,
) -> None:
    """Dynamic objects and non-string warnings fail closed at the ORM boundary."""

    payload = _completion_payload()
    payload["trades"][0]["dynamic"] = object()
    with pytest.raises(ValueError, match="trades"):
        pending_backtest.mark_completed(112000.25, payload)

    payload = _completion_payload()
    payload["warnings"] = cast(list[str], [1])
    with pytest.raises(ValueError, match="warnings"):
        pending_backtest.mark_completed(112000.25, payload)
