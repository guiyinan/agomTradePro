"""Unit tests for position management rule evaluation."""

from types import SimpleNamespace

import pytest

from apps.strategy.application.position_management_service import (
    PositionManagementService,
    PositionRuleError,
)


def _build_rule(**kwargs):
    data = {
        "buy_condition_expr": "current_price <= buy_price",
        "sell_condition_expr": "current_price >= sell_price",
        "buy_price_expr": "support_price + atr * 0.2",
        "sell_price_expr": "resistance_price - atr * 0.1",
        "stop_loss_expr": "min(structure_low, buy_price - 2 * atr)",
        "take_profit_expr": "buy_price + 2 * (buy_price - stop_loss_price)",
        "position_size_expr": "(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
        "price_precision": 2,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_evaluate_position_management_rule_success():
    rule = _build_rule()
    context = {
        "current_price": 98.0,
        "support_price": 97.5,
        "resistance_price": 108.0,
        "structure_low": 94.0,
        "atr": 1.5,
        "account_equity": 100000.0,
        "risk_per_trade_pct": 0.01,
    }

    result = PositionManagementService.evaluate(rule, context)

    assert result.buy_price == 97.8
    assert result.sell_price == 107.85
    assert result.stop_loss_price == 94.0
    assert result.take_profit_price == 105.4
    assert result.position_size > 0
    assert result.should_buy is False
    assert result.should_sell is False
    assert result.risk_reward_ratio is not None


def test_validate_expression_blocks_unsafe_calls():
    with pytest.raises(PositionRuleError):
        PositionManagementService.validate_expression("__import__('os').system('dir')")


def test_evaluate_raises_on_missing_variable():
    rule = _build_rule(buy_price_expr="support_price + unknown_var")
    context = {"support_price": 10.0}

    with pytest.raises(PositionRuleError):
        PositionManagementService.evaluate(rule, context)
