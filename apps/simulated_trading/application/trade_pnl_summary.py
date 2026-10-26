"""Application facade for filtered trade PnL projections."""

from __future__ import annotations

from collections.abc import Sequence

from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.trade_pnl_summary import (
    TradePnlSummary,
    summarize_trade_pnl,
)


def summarize_portfolio_trade_pnl(trades: Sequence[SimulatedTrade]) -> TradePnlSummary:
    """Delegate a filtered trade sequence to the pure Domain PnL projector."""

    return summarize_trade_pnl(trades)


__all__ = ["summarize_portfolio_trade_pnl"]
