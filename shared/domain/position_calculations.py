"""
Shared Position Derived Field Calculations.

Pure Python domain service for computing position market_value,
unrealized_pnl, and unrealized_pnl_pct from core fields.

Used by both apps/account and apps/simulated_trading to ensure
consistent derived-field semantics across the unified ledger.
"""

from __future__ import annotations


def recalculate_derived_fields(
    shares: float,
    avg_cost: float,
    current_price: float,
) -> tuple[float, float, float]:
    """Recalculate position derived fields from core inputs.

    Args:
        shares: Position quantity (may be fractional for funds).
        avg_cost: Average cost basis per unit.
        current_price: Latest market price per unit.

    Returns:
        (market_value, unrealized_pnl, unrealized_pnl_pct)
        where pnl_pct is expressed as a percentage (e.g. 5.0 means +5%).
    """
    market_value = shares * current_price
    cost_basis = shares * avg_cost
    unrealized_pnl = market_value - cost_basis
    if cost_basis > 0:
        unrealized_pnl_pct = (unrealized_pnl / cost_basis) * 100
    else:
        unrealized_pnl_pct = 0.0
    return market_value, unrealized_pnl, unrealized_pnl_pct
