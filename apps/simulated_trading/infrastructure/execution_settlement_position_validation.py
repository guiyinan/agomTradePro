"""Fail-closed validation of locked simulated positions before settlement."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
    _execution_quantity_deny_code,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)

if TYPE_CHECKING:
    from apps.simulated_trading.infrastructure.models import PositionModel


def validate_execution_position(position: PositionModel) -> None:
    """Reject malformed historic aggregates without rebuilding missing lot history."""

    if position.valuation_known is not True:
        raise SimulatedTradeExecutionBlocked(
            "position valuation is unknown", code="POSITION_VALUATION_UNKNOWN"
        )
    if position.available_quantity_known is not True:
        raise SimulatedTradeExecutionBlocked(
            "position sellable quantity is unknown",
            code="SELLABLE_BALANCE_UNKNOWN",
        )
    quantity = validate_ledger_quantity(position.quantity, "position.quantity")
    available = validate_ledger_quantity(
        position.available_quantity,
        "position.available_quantity",
    )
    validate_ledger_money(position.total_cost, "position.total_cost")
    validate_ledger_money(position.market_value, "position.market_value")
    validate_ledger_price(position.current_price, "position.current_price", allow_zero=False)
    validate_ledger_price(position.avg_cost, "position.avg_cost", allow_zero=False)
    if quantity <= 0 or available > quantity:
        raise SimulatedTradeExecutionBlocked(
            "historic position aggregate has inconsistent total/available quantities"
        )


def validate_execution_rule_quantity(
    *,
    intent: SimulatedTradeIntent,
    bundle: ExecutionSettlementBundleV3,
    locked_position: tuple[Decimal, Decimal] | None = None,
) -> None:
    """Enforce one V3 quantity rule, using locked balance only for SELL exceptions."""

    rule = bundle.execution_submission_v2.execution_rule_v1
    quantity_rule = (
        rule.buy_quantity if intent.side is SimulatedTradeSide.BUY else rule.sell_quantity
    )
    deny_code = _execution_quantity_deny_code(
        side=intent.side,
        quantity=intent.quantity,
        minimum=quantity_rule.minimum,
        step=quantity_rule.step,
        maximum=quantity_rule.maximum,
        sell_odd_lot_mode=rule.sell_odd_lot_mode.value,
        locked_position=locked_position,
    )
    if deny_code is not None:
        raise SimulatedTradeExecutionBlocked(
            "trade quantity violates the exact Risk V3 quantity rule",
            code=deny_code,
        )
