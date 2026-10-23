"""Re-evaluate the persisted strategy rule against the preview quote snapshot."""

from __future__ import annotations

from decimal import Decimal

from apps.simulated_trading.application.rebalance_preview_context import (
    build_position_rule_context,
    object_payload,
)
from apps.simulated_trading.application.rebalance_preview_execution_evidence import (
    PositionRuleEvaluator,
)
from apps.simulated_trading.application.rebalance_preview_valuation import _decimal_value
from apps.simulated_trading.domain.entities import Position


def evaluate_current_position_rule(
    *,
    evaluator: PositionRuleEvaluator,
    position_rule_id: int | None,
    position: Position | None,
    price: Decimal | None,
    portfolio_value: Decimal | None,
) -> tuple[dict[str, object] | None, str | None, str | None]:
    """Evaluate one configured rule only when every required input is present."""

    if type(position_rule_id) is not int or position_rule_id <= 0:
        return None, "STRATEGY_RULE_EVALUATION_UNAVAILABLE", None
    current_quantity = _decimal_value(position.quantity) if position is not None else Decimal("0")
    if current_quantity is None or current_quantity < 0:
        return None, "STRATEGY_RULE_CONTEXT_UNKNOWN", None
    entry_price_basis = (
        "prospective_current_quote" if current_quantity == 0 else "position_cost_basis"
    )
    if current_quantity > 0 and position is not None and position.cost_basis_known is not True:
        reason = (
            "POSITION_COST_BASIS_PARTIAL"
            if position.cost_basis_known is False
            else "POSITION_COST_BASIS_UNKNOWN"
        )
        return None, reason, entry_price_basis
    entry_price = (
        _decimal_value(position.avg_cost)
        if position is not None and current_quantity > 0
        else price
    )
    if (
        price is None
        or price <= 0
        or entry_price is None
        or entry_price <= 0
        or portfolio_value is None
        or portfolio_value <= 0
    ):
        return None, "STRATEGY_RULE_CONTEXT_UNKNOWN", entry_price_basis
    context = build_position_rule_context(
        current_price=float(price),
        entry_price=float(entry_price),
        account_equity=float(portfolio_value),
    )
    try:
        raw_result = evaluator.evaluate_position_rule(position_rule_id, context)
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        raw_result = None
    result = object_payload(raw_result)
    required_numeric_fields = (
        "buy_price",
        "sell_price",
        "stop_loss_price",
        "take_profit_price",
        "position_size",
    )
    if (
        result is None
        or type(result.get("should_buy")) is not bool
        or type(result.get("should_sell")) is not bool
        or any(_decimal_value(result.get(name)) is None for name in required_numeric_fields)
        or (
            result.get("risk_reward_ratio") is not None
            and _decimal_value(result.get("risk_reward_ratio")) is None
        )
    ):
        return None, "STRATEGY_RULE_EVALUATION_UNAVAILABLE", entry_price_basis
    return result, None, entry_price_basis


__all__: tuple[str, ...] = ("evaluate_current_position_rule",)
