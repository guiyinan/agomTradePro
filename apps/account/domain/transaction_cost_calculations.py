"""Pure variance calculation for the fee-availability candidate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.account.domain.transaction_cost_contracts import TransactionCostRecord


@dataclass(frozen=True)
class TransactionCostVariance:
    """Current actual-versus-estimated variance and its optional fraction."""

    cost_variance: Decimal | None
    cost_variance_pct: float | None


def canonical_fee_amount(amount: Decimal | None, known: bool | None) -> Decimal | None:
    """Expose an amount only when its collection state is explicitly true."""
    return amount if known is True else None


def complete_actual_cost(record: TransactionCostRecord) -> Decimal | None:
    """Sum actual fees only when every component is explicitly known."""
    if (
        record["commission_known"] is not True
        or record["commission"] is None
        or record["slippage_known"] is not True
        or record["slippage"] is None
        or record["stamp_duty_known"] is not True
        or record["stamp_duty"] is None
        or record["transfer_fee_known"] is not True
        or record["transfer_fee"] is None
    ):
        return None
    return record["commission"] + record["slippage"] + record["stamp_duty"] + record["transfer_fee"]


def derive_actual_cost_variance(record: TransactionCostRecord) -> TransactionCostVariance:
    """Derive variance only from a complete, explicitly known actual-fee set."""
    actual = complete_actual_cost(record)
    if actual is None:
        return TransactionCostVariance(cost_variance=None, cost_variance_pct=None)

    estimate = record["estimated_cost"]
    if estimate is None:
        return TransactionCostVariance(cost_variance=None, cost_variance_pct=None)

    variance = actual - estimate
    variance_pct = float(variance / estimate) if estimate > 0 else None
    return TransactionCostVariance(cost_variance=variance, cost_variance_pct=variance_pct)
