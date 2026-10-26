"""Serialize the exact current PositionManagementRule source for M1 binding."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.strategy.application.inspection_risk_contracts import StrategyRiskLimitField
from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel


def invalid_strategy_risk_limit_fields(
    strategy: StrategyModel | None,
) -> tuple[StrategyRiskLimitField, ...]:
    """Preserve corrupt stored risk columns separately from legitimate NULL stop-loss."""

    if strategy is None:
        return ()
    invalid_fields: list[StrategyRiskLimitField] = []
    for field_name, nullable in (
        ("max_position_pct", False),
        ("max_total_position_pct", False),
        ("stop_loss_pct", True),
    ):
        value = getattr(strategy, field_name)
        if value is None:
            if not nullable:
                invalid_fields.append(_public_risk_field_name(field_name))
            continue
        if type(value) not in (int, float, Decimal):
            invalid_fields.append(_public_risk_field_name(field_name))
            continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            invalid_fields.append(_public_risk_field_name(field_name))
            continue
        if not parsed.is_finite() or parsed < Decimal("0") or parsed > Decimal("100"):
            invalid_fields.append(_public_risk_field_name(field_name))
    return tuple(invalid_fields)


def position_rule_source_json(rule: PositionManagementRuleModel | None) -> str | None:
    """Return complete current rule content, never a version or effective timestamp."""

    if rule is None or type(rule.pk) is not int or type(rule.strategy_id) is not int:
        return None
    source: dict[str, Any] = {
        "rule_id": rule.pk,
        "strategy_id": rule.strategy_id,
        "name": rule.name,
        "description": rule.description,
        "is_active": rule.is_active,
        "price_precision": rule.price_precision,
        "variables_schema": rule.variables_schema,
        "buy_condition_expr": rule.buy_condition_expr,
        "sell_condition_expr": rule.sell_condition_expr,
        "buy_price_expr": rule.buy_price_expr,
        "sell_price_expr": rule.sell_price_expr,
        "stop_loss_expr": rule.stop_loss_expr,
        "take_profit_expr": rule.take_profit_expr,
        "position_size_expr": rule.position_size_expr,
        "metadata": rule.metadata,
    }
    try:
        return json.dumps(
            source,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None


def _public_risk_field_name(field_name: str) -> StrategyRiskLimitField:
    """Map one ORM column name to the Strategy Application's typed field label."""

    field_names: dict[str, StrategyRiskLimitField] = {
        "max_position_pct": "max_single_position_pct",
        "max_total_position_pct": "max_total_position_pct",
        "stop_loss_pct": "stop_loss_pct",
    }
    return field_names[field_name]


__all__: tuple[str, ...] = (
    "invalid_strategy_risk_limit_fields",
    "position_rule_source_json",
)
