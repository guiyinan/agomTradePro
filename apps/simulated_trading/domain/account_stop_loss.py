"""Exact account stop-loss decisions from an explicit price and known cost."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .execution_settlement_primitives import SimulatedSettlementContractError


@dataclass(frozen=True, slots=True)
class AccountStopLossEvaluation:
    """The exact threshold decision shared by observation and locked execution."""

    triggered: bool
    average_cost: Decimal
    pnl_pct: Decimal


def evaluate_account_stop_loss(
    *, price: Decimal, quantity: Decimal, total_cost: Decimal, threshold_pct: Decimal
) -> AccountStopLossEvaluation:
    """Trigger strictly below the configured loss percentage using total cost basis."""
    for name, value in (
        ("price", price),
        ("quantity", quantity),
        ("total_cost", total_cost),
        ("threshold_pct", threshold_pct),
    ):
        if type(value) is not Decimal or not value.is_finite() or value <= Decimal(0):
            raise SimulatedSettlementContractError(f"{name} must be an explicit positive Decimal")
    with localcontext() as context:
        context.prec = 80
        average_cost = total_cost / quantity
        pnl_pct = (price * quantity - total_cost) / total_cost * Decimal(100)
        return AccountStopLossEvaluation(pnl_pct < -threshold_pct, average_cost, pnl_pct)
