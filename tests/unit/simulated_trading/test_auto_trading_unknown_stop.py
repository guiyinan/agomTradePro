"""Stop one account after uncertain execution while retaining prior confirmations."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.simulated_trading.application.automatic_trade_execution import (
    AutomaticTradeExecutionPreflightBlocked,
)
from apps.simulated_trading.application.manual_trade_execution import (
    SimulatedTradeExecutionReadbackUnknown,
)
from apps.simulated_trading.application.ports import PositionExitAdvice
from apps.simulated_trading.domain.auto_trading_outcomes import AutoTradingOutcome
from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo
from tests.unit.simulated_trading.test_auto_trading_engine_outcomes import (
    _account,
    _engine_with_legacy_candidate,
    _trade_stub,
)


@pytest.mark.parametrize("branch", ["legacy", "strategy"])
@pytest.mark.parametrize("action", ["buy", "sell"])
@pytest.mark.parametrize(
    "error_kind",
    ["unknown", "preflight", "owner_changed", "scope_unavailable", "owner_unavailable"],
)
def test_account_stops_after_unknown_trade_but_continues_after_known_block(
    branch: str,
    action: str,
    error_kind: str,
) -> None:
    """An uncertain second callback cannot authorize a third order or performance update."""
    unknown = error_kind == "unknown"
    must_stop = error_kind in {"unknown", "owner_changed", "scope_unavailable", "owner_unavailable"}
    error_codes = {
        "owner_changed": "AUTO_TRADE_OWNER_CHANGED",
        "scope_unavailable": "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE",
        "owner_unavailable": "AUTO_TRADE_OWNER_UNAVAILABLE",
    }
    account = _account()
    engine, buy = _engine_with_legacy_candidate(account)
    codes = ("000001.SZ", "600000.SH", "600519.SH")
    engine.asset_pool_service.get_investable_assets_with_signals.return_value = (
        [
            {
                "asset_code": code,
                "asset_name": code,
                "asset_type": "equity",
                "score": 90.0,
                "signal_id": None,
            }
            for code in codes
        ]
        if action == "buy"
        else []
    )
    if action == "sell":
        engine.position_repo.get_by_account.return_value = [
            SimpleNamespace(
                asset_code=code,
                asset_name=code,
                quantity=100,
                available_quantity=100,
                available_quantity_known=True,
                valuation_known=True,
                unrealized_pnl_pct=0.0,
            )
            for code in codes
        ]
        engine._get_position_exit_advice = Mock(
            side_effect=lambda position, *_args, **_kwargs: PositionExitAdvice(
                asset_code=position.asset_code,
                should_exit=True,
                quantity=100,
                reason_code="TEST_EXIT",
                reason_text="test exit",
            )
        )
    error = (
        SimulatedTradeExecutionReadbackUnknown("owned readback unavailable")
        if unknown
        else AutomaticTradeExecutionPreflightBlocked(
            "known atomic block",
            code=error_codes.get(error_kind, "AUTO_TRADE_PREFLIGHT_BLOCKED"),
        )
    )
    executor = buy if action == "buy" else engine.sell_use_case
    executor.execute.side_effect = [_trade_stub(1), error, _trade_stub(3)]
    gateway = Mock()
    gateway.execute_for_account.return_value = ExecutionResult(
        success=True,
        signals=[
            SignalInfo(
                signal_id=None,
                asset_code=code,
                asset_name=code,
                action=action,
                quantity=100,
                confidence=0.9,
                reason="test",
            )
            for code in codes
        ],
    )
    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(
                get_active_strategy_id=Mock(return_value=91 if branch == "strategy" else None)
            ),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
        patch(
            "apps.simulated_trading.application.auto_trading_engine.PositionSizingRule.calculate_buy_quantity",
            return_value=100,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]
    assert executor.execute.call_count == (2 if must_stop else 3)
    assert result.confirmed_trade_count == (1 if must_stop else 2)
    assert result.outcome is AutoTradingOutcome.PARTIAL
    assert result.counts_unavailable is unknown
    assert result.stored == (None if unknown else 1 if must_stop else 2)
    assert any(issue.effects_indeterminate for issue in result.issues) is unknown
    if must_stop:
        engine._update_account_performance.assert_not_called()
    else:
        engine._update_account_performance.assert_called_once()


@pytest.mark.parametrize("asset_name", [None, ""])
def test_strategy_buy_missing_name_blocks_without_inventing_identity(
    asset_name: str | None,
) -> None:
    """A signal must provide its security name rather than making one from a code or None."""
    account = _account()
    engine, buy = _engine_with_legacy_candidate(account)
    gateway = Mock()
    gateway.execute_for_account.return_value = ExecutionResult(
        success=True,
        signals=[
            SimpleNamespace(
                signal_id=None,
                asset_code="000001.SZ",
                asset_name=asset_name,
                action="buy",
                quantity=100,
                confidence=0.9,
                reason="test",
                metadata={},
            )
        ],
    )
    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]
    buy.execute.assert_not_called()
    assert result.outcome is AutoTradingOutcome.BLOCKED
    assert result.stored == 0
    assert result.counts_unavailable is False
    assert any(issue.code == "BUY_SIGNAL_METADATA_INCOMPLETE" for issue in result.issues)
