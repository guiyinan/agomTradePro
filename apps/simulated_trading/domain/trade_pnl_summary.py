"""Pure read projections for original and effective simulated-trade PnL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .entities import OrderStatus, SimulatedTrade, TradeAction
from .fee_correction import FeeCorrectionContractError, sum_signed_ledger_money


class TradePnlEvidenceStatus(Enum):
    """Evidence state used by the trade API's original PnL status field."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class TradePnlRowProjection:
    """Original/effective values and evidence flags for one source Trade."""

    trade_id: int
    original_realized_pnl: float | None
    effective_realized_pnl: float | None
    original_realized_pnl_pct: float | None
    effective_realized_pnl_pct: float | None
    realized_pnl_known: bool | None
    realized_pnl_status: TradePnlEvidenceStatus
    effective_realized_pnl_known: bool | None
    realized_pnl_pct_known: bool | None
    effective_realized_pnl_pct_known: bool | None


@dataclass(frozen=True, slots=True)
class TradePnlSummary:
    """Exact aggregate PnL and row projections for an ordered trade sequence."""

    rows: tuple[TradePnlRowProjection, ...]
    original_total_pnl: Decimal | None
    original_total_pnl_known: bool
    effective_total_pnl: Decimal | None
    effective_total_pnl_known: bool


def _as_signed_money(value: object, field_name: str) -> Decimal:
    """Convert a persisted numeric value to Decimal for exact money validation."""

    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as error:
        raise FeeCorrectionContractError(
            f"{field_name} cannot be represented as exact ledger money"
        ) from error


def _project_trade(trade: SimulatedTrade) -> TradePnlRowProjection:
    """Project one Trade without mutating its original or correction fields."""

    is_sell = trade.action is TradeAction.SELL
    original_pnl = trade.realized_pnl
    effective_pnl = trade.current_realized_pnl
    original_pnl_pct = trade.realized_pnl_pct
    effective_pnl_pct = trade.current_realized_pnl_pct
    original_known = (
        is_sell
        and trade.cost_basis_known is True
        and trade.fee_amounts_known is True
        and original_pnl is not None
    )
    effective_known = (
        is_sell
        and trade.cost_basis_known is True
        and trade.fee_amounts_known is True
        and effective_pnl is not None
    )
    if not is_sell:
        status = TradePnlEvidenceStatus.NOT_APPLICABLE
    elif original_known:
        status = TradePnlEvidenceStatus.KNOWN
    else:
        status = TradePnlEvidenceStatus.UNKNOWN

    return TradePnlRowProjection(
        trade_id=trade.trade_id,
        original_realized_pnl=original_pnl,
        effective_realized_pnl=effective_pnl,
        original_realized_pnl_pct=original_pnl_pct,
        effective_realized_pnl_pct=effective_pnl_pct,
        realized_pnl_known=original_known if is_sell else None,
        realized_pnl_status=status,
        effective_realized_pnl_known=effective_known if is_sell else None,
        realized_pnl_pct_known=(
            original_known and original_pnl_pct is not None if is_sell else None
        ),
        effective_realized_pnl_pct_known=(
            effective_known and effective_pnl_pct is not None if is_sell else None
        ),
    )


def summarize_trade_pnl(trades: Sequence[SimulatedTrade]) -> TradePnlSummary:
    """Build fee-aware PnL rows and exact totals for the supplied filtered trades.

    Row evidence follows the trade's original/effective source fields. Aggregate
    totals include only executed SELLs. An empty executed-SELL set is a known zero,
    while any unknown financial evidence makes its corresponding total ``None``.
    """

    if not isinstance(trades, Sequence) or isinstance(trades, (str, bytes)):
        raise FeeCorrectionContractError("trades must be an ordered SimulatedTrade sequence")
    if any(not isinstance(trade, SimulatedTrade) for trade in trades):
        raise FeeCorrectionContractError("trade sequence contains an untyped row")

    rows = tuple(_project_trade(trade) for trade in trades)
    executed_sells = tuple(
        trade
        for trade in trades
        if trade.action is TradeAction.SELL and trade.status is OrderStatus.EXECUTED
    )
    original_total_known = all(
        trade.cost_basis_known is True
        and trade.fee_amounts_known is True
        and trade.realized_pnl is not None
        for trade in executed_sells
    )
    effective_total_known = all(
        trade.cost_basis_known is True
        and trade.fee_amounts_known is True
        and trade.current_realized_pnl is not None
        for trade in executed_sells
    )
    original_total = (
        sum_signed_ledger_money(
            tuple(
                _as_signed_money(trade.realized_pnl, "trade_api.original_realized_pnl")
                for trade in executed_sells
            ),
            "trade_api.original_realized_pnl",
        )
        if original_total_known
        else None
    )
    effective_total = (
        sum_signed_ledger_money(
            tuple(
                _as_signed_money(
                    trade.current_realized_pnl,
                    "trade_api.effective_realized_pnl",
                )
                for trade in executed_sells
            ),
            "trade_api.effective_realized_pnl",
        )
        if effective_total_known
        else None
    )
    return TradePnlSummary(
        rows=rows,
        original_total_pnl=original_total,
        original_total_pnl_known=original_total_known,
        effective_total_pnl=effective_total,
        effective_total_pnl_known=effective_total_known,
    )


__all__ = [
    "TradePnlEvidenceStatus",
    "TradePnlRowProjection",
    "TradePnlSummary",
    "summarize_trade_pnl",
]
