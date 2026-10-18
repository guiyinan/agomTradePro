"""Pure accounting calculations shared by settlement execution paths."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from math import isfinite

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import validate_ledger_price

_PRICE_TICK = Decimal("0.0001")


def _average_cost(total_cost: Decimal, quantity: Decimal) -> Decimal:
    """Return four-decimal average cost from the exact stored cost basis."""

    if quantity <= 0:
        raise SimulatedTradeExecutionBlocked("position quantity must remain positive")
    try:
        with localcontext() as context:
            context.prec = 80
            value = (total_cost / quantity).quantize(_PRICE_TICK, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise SimulatedTradeExecutionBlocked("position average cost is invalid") from error
    return validate_ledger_price(value, "avg_cost", allow_zero=False)


def _percentage(numerator: Decimal, denominator: Decimal) -> float:
    """Convert an exact ledger ratio to the legacy FloatField representation."""

    if denominator <= 0:
        raise SimulatedTradeExecutionBlocked("percentage denominator must be positive")
    with localcontext() as context:
        context.prec = 80
        value = float((numerator / denominator) * Decimal("100"))
    if not isfinite(value):
        raise SimulatedTradeExecutionBlocked("percentage exceeds the persisted float range")
    return value
