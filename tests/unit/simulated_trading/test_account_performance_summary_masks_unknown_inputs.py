"""Account performance values require complete cash, valuation, and trade evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Literal

import pytest

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
)
from apps.simulated_trading.application.use_cases import (
    AccountPerformanceResult,
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    AccountType,
    OrderStatus,
    Position,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)

_CURRENT_METRICS: tuple[
    Literal["total_return"],
    Literal["annual_return"],
    Literal["max_drawdown"],
    Literal["sharpe_ratio"],
] = ("total_return", "annual_return", "max_drawdown", "sharpe_ratio")


def _account() -> SimulatedAccount:
    """Return an account with representative persisted summary metrics."""

    return SimulatedAccount(
        account_id=41,
        account_name="performance-mask-fixture",
        account_type=AccountType.SIMULATED,
        initial_capital=1000.0,
        current_cash=500.0,
        current_market_value=500.0,
        total_value=1000.0,
        total_return=12.5,
        annual_return=8.0,
        max_drawdown=3.5,
        sharpe_ratio=1.25,
        win_rate=100.0,
    )


def _position() -> Position:
    """Return one position with complete valuation evidence."""

    return Position(
        account_id=41,
        asset_code="000001.SZ",
        asset_name="performance-mask-position",
        asset_type="equity",
        quantity=10.0,
        available_quantity=10.0,
        avg_cost=10.0,
        total_cost=100.0,
        current_price=12.0,
        market_value=120.0,
        unrealized_pnl=20.0,
        unrealized_pnl_pct=20.0,
        first_buy_date=date(2026, 10, 15),
        last_update_date=date(2026, 10, 19),
        valuation_known=True,
        cost_basis_known=True,
    )


def _executed_sell() -> SimulatedTrade:
    """Return an executed SELL with complete cost and fee evidence."""

    return SimulatedTrade(
        trade_id=51,
        account_id=41,
        asset_code="000001.SZ",
        asset_name="performance-mask-position",
        asset_type="equity",
        action=TradeAction.SELL,
        quantity=5.0,
        price=12.0,
        amount=60.0,
        order_date=date(2026, 10, 19),
        execution_date=date(2026, 10, 19),
        execution_time=datetime(2026, 10, 19, 2, 0, tzinfo=UTC),
        commission=0.1,
        slippage=0.1,
        total_cost=0.2,
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=9.8,
        realized_pnl_pct=19.6,
        status=OrderStatus.EXECUTED,
    )


def _execute(
    account: SimulatedAccount,
    positions: list[Position],
    trades: list[SimulatedTrade],
) -> AccountPerformanceResult:
    """Execute the performance use case with explicit in-memory repository doubles."""

    account_repo = SimpleNamespace(get_by_id=lambda account_id: account)
    position_repo = SimpleNamespace(get_by_account=lambda account_id: positions)

    def get_account_history(
        *, account_id: int, as_of: datetime
    ) -> FeeCorrectionAccountHistoryProjection:
        return FeeCorrectionAccountHistoryProjection(
            account_id=account_id,
            as_of=as_of,
            trades=tuple(trades),
            cash_events=(),
        )

    trade_repo = SimpleNamespace(
        get_by_account=lambda account_id: trades,
        get_account_history=get_account_history,
    )
    return GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo).execute(41)


@pytest.mark.parametrize(
    "unknown_source",
    ("cash", "position_valuation", "executed_sell_cost_or_fees"),
)
def test_current_performance_metrics_are_null_when_any_required_evidence_is_unknown(
    unknown_source: Literal["cash", "position_valuation", "executed_sell_cost_or_fees"],
) -> None:
    """Each incomplete evidence source masks all four persisted performance metrics."""

    account = _account()
    positions = [_position()]
    trades = [_executed_sell()]

    if unknown_source == "cash":
        account = replace(
            account,
            account_type=AccountType.REAL,
            cash_known=False,
            cash_reconciliation_status=AccountCashReconciliationStatus.UNVERIFIED,
        )
    elif unknown_source == "position_valuation":
        positions = [replace(positions[0], valuation_known=False)]
    else:
        trades = [replace(trades[0], cost_basis_known=None, fee_amounts_known=False)]

    result = _execute(account, positions, trades)

    for metric in _CURRENT_METRICS:
        assert result["performance"][metric] is None

    if unknown_source == "executed_sell_cost_or_fees":
        assert result["win_rate"] is None
        assert result["win_rate_known"] is False
        assert result["winning_trades"] is None
    else:
        assert result["win_rate"] == 100.0
        assert result["win_rate_known"] is True
        assert result["winning_trades"] == 1


def test_complete_performance_inputs_preserve_values_and_cost_based_win_rate() -> None:
    """Complete evidence retains persisted metrics and computes the known SELL win rate."""

    result = _execute(_account(), [_position()], [_executed_sell()])

    assert result["performance"] == {
        "total_return": 12.5,
        "annual_return": 8.0,
        "max_drawdown": 3.5,
        "sharpe_ratio": 1.25,
        "win_rate": 100.0,
    }
    assert result["win_rate"] == 100.0
    assert result["win_rate_known"] is True
    assert result["winning_trades"] == 1


@pytest.mark.parametrize("status", (OrderStatus.PENDING, OrderStatus.CANCELLED, OrderStatus.FAILED))
@pytest.mark.parametrize("cost_complete", (True, False))
def test_unexecuted_sells_do_not_change_win_rate_or_performance_coverage(
    status: OrderStatus, cost_complete: bool
) -> None:
    """Neither a quoted gain nor missing evidence on an unexecuted order is a trade."""
    executed_loss = replace(_executed_sell(), realized_pnl=-9.8, realized_pnl_pct=-19.6)
    unexecuted = replace(
        _executed_sell(),
        trade_id=52,
        status=status,
        cost_basis_known=True if cost_complete else None,
        fee_amounts_known=True if cost_complete else None,
        realized_pnl=100.0,
        realized_pnl_pct=100.0,
    )
    result = _execute(_account(), [_position()], [executed_loss, unexecuted])
    assert result["total_trades"] == 2
    assert result["win_rate_known"] is True
    assert result["winning_trades"] == 0
    assert result["win_rate"] == 0.0
    assert result["performance"]["total_return"] == 12.5
    assert result["performance"]["annual_return"] == 8.0
    assert result["performance"]["max_drawdown"] == 3.5
    assert result["performance"]["sharpe_ratio"] == 1.25
