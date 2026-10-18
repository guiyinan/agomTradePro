"""Regression tests for using valuation knowledge in risk-based exits."""

from __future__ import annotations

import logging
from datetime import date

from apps.simulated_trading.application.auto_trading_exit_evaluator import (
    AutoTradingExitEvaluator,
)
from apps.simulated_trading.application.ports import PositionExitAdvice
from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount

_TRADE_DATE = date(2026, 10, 16)


def _position(
    *,
    valuation_known: bool,
    cost_basis_known: bool | None,
    is_invalidated: bool = False,
) -> Position:
    """Build one position whose persisted percentage can be stale."""

    return Position(
        account_id=7,
        asset_code="600000.SH",
        asset_name="Exit knowledge fixture",
        asset_type="equity",
        quantity=100.0,
        available_quantity=100.0,
        avg_cost=10.0,
        total_cost=1000.0,
        current_price=8.0,
        market_value=800.0,
        unrealized_pnl=-200.0,
        unrealized_pnl_pct=-20.0,
        first_buy_date=date(2026, 10, 1),
        last_update_date=_TRADE_DATE,
        valuation_known=valuation_known,
        cost_basis_known=cost_basis_known,
        is_invalidated=is_invalidated,
        invalidation_reason="Independent thesis invalidation" if is_invalidated else None,
    )


def _account() -> SimulatedAccount:
    """Build an account with a stop-loss threshold that stale data would cross."""

    return SimulatedAccount(
        account_id=7,
        account_name="Exit knowledge fixture",
        account_type=AccountType.SIMULATED,
        initial_capital=10000.0,
        current_cash=9000.0,
        current_market_value=800.0,
        total_value=9800.0,
        stop_loss_pct=10.0,
    )


def _evaluate(position: Position) -> PositionExitAdvice | None:
    """Call the real application exit evaluator without external collaborators."""

    return AutoTradingExitEvaluator().get_position_exit_advice(
        position,
        _account(),
        _TRADE_DATE,
        None,
        signal_service=None,
        asset_pool_service=None,
        logger=logging.getLogger(__name__),
    )


def test_unknown_valuation_cannot_trigger_account_stop_loss_from_stale_percentage() -> None:
    """A cached -20% does not prove the current mark crossed a 10% stop."""

    advice = _evaluate(_position(valuation_known=False, cost_basis_known=True))

    assert advice is None or advice.reason_code != "ACCOUNT_STOP_LOSS"


def test_independent_position_invalidation_still_triggers_exit_with_unknown_value() -> None:
    """Thesis invalidation remains actionable even when valuation and basis are unknown."""

    advice = _evaluate(
        _position(
            valuation_known=False,
            cost_basis_known=None,
            is_invalidated=True,
        )
    )

    assert advice is not None
    assert advice.should_exit is True
    assert advice.reason_code == "POSITION_INVALIDATED"
