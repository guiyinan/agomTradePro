"""Fail-closed validation of locked simulated positions before settlement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
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
