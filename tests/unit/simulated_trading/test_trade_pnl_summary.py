"""Pure contract tests for the fee-aware trade PnL projection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, localcontext
from typing import cast

import pytest

from apps.simulated_trading.application.trade_pnl_summary import (
    summarize_portfolio_trade_pnl,
)
from apps.simulated_trading.domain.entities import OrderStatus, SimulatedTrade, TradeAction
from apps.simulated_trading.domain.fee_correction import FeeCorrectionContractError
from apps.simulated_trading.domain.trade_pnl_summary import TradePnlEvidenceStatus


def _trade(
    trade_id: int,
    *,
    action: TradeAction = TradeAction.SELL,
    status: OrderStatus = OrderStatus.EXECUTED,
    realized_pnl: float | None = 1.25,
    realized_pnl_pct: float | None = 12.5,
    effective_realized_pnl: float | None = None,
    effective_realized_pnl_pct: float | None = None,
    fee_amounts_known: bool | None = True,
    cost_basis_known: bool | None = True,
    corrected: bool = False,
) -> SimulatedTrade:
    """Build a complete immutable-source trade with an optional correction overlay."""

    return SimulatedTrade(
        trade_id=trade_id,
        account_id=7,
        asset_code="000001.SZ",
        asset_name="fixture",
        asset_type="equity",
        action=action,
        quantity=1.0,
        price=10.0,
        amount=10.0,
        order_date=date(2026, 10, 20),
        execution_date=date(2026, 10, 20),
        execution_time=datetime(2026, 10, 20, 2, 0, tzinfo=UTC),
        fee_amounts_known=fee_amounts_known,
        cost_basis_known=cost_basis_known,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        status=status,
        effective_realized_pnl=effective_realized_pnl,
        effective_realized_pnl_pct=effective_realized_pnl_pct,
        fee_correction_revision=1 if corrected else None,
        fee_correction_overlay_applied=corrected,
    )


def test_original_and_effective_pnl_stay_separate_and_sum_exactly() -> None:
    trade = _trade(
        1,
        realized_pnl=1.25,
        realized_pnl_pct=12.5,
        effective_realized_pnl=2.75,
        effective_realized_pnl_pct=27.5,
        corrected=True,
    )

    summary = summarize_portfolio_trade_pnl((trade,))

    assert summary.original_total_pnl == Decimal("1.25")
    assert summary.original_total_pnl_known is True
    assert summary.effective_total_pnl == Decimal("2.75")
    assert summary.effective_total_pnl_known is True
    row = summary.rows[0]
    assert row.original_realized_pnl == 1.25
    assert row.effective_realized_pnl == 2.75
    assert row.original_realized_pnl_pct == 12.5
    assert row.effective_realized_pnl_pct == 27.5
    assert row.realized_pnl_known is True
    assert row.effective_realized_pnl_known is True
    assert row.realized_pnl_pct_known is True
    assert row.effective_realized_pnl_pct_known is True
    assert row.realized_pnl_status is TradePnlEvidenceStatus.KNOWN
    assert trade.realized_pnl == 1.25
    assert trade.effective_realized_pnl == 2.75


@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known"),
    [(False, True), (True, None)],
)
def test_incomplete_cost_or_fee_evidence_masks_both_aggregate_totals(
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> None:
    summary = summarize_portfolio_trade_pnl(
        (_trade(1, cost_basis_known=cost_basis_known, fee_amounts_known=fee_amounts_known),)
    )

    row = summary.rows[0]
    assert summary.original_total_pnl is None
    assert summary.original_total_pnl_known is False
    assert summary.effective_total_pnl is None
    assert summary.effective_total_pnl_known is False
    assert row.realized_pnl_known is False
    assert row.effective_realized_pnl_known is False
    assert row.realized_pnl_pct_known is False
    assert row.effective_realized_pnl_pct_known is False
    assert row.realized_pnl_status is TradePnlEvidenceStatus.UNKNOWN


def test_missing_effective_value_does_not_replace_known_original_evidence() -> None:
    summary = summarize_portfolio_trade_pnl((_trade(1, corrected=True),))

    row = summary.rows[0]
    assert summary.original_total_pnl == Decimal("1.25")
    assert summary.original_total_pnl_known is True
    assert summary.effective_total_pnl is None
    assert summary.effective_total_pnl_known is False
    assert row.realized_pnl_known is True
    assert row.effective_realized_pnl_known is False
    assert row.realized_pnl_pct_known is True
    assert row.effective_realized_pnl_pct_known is False


def test_totals_include_only_executed_sells_but_rows_keep_sell_evidence() -> None:
    executed = _trade(1, realized_pnl=1.50)
    pending = _trade(2, status=OrderStatus.PENDING, realized_pnl=7.00)
    failed = _trade(3, status=OrderStatus.FAILED, realized_pnl=9.00)
    buy = _trade(4, action=TradeAction.BUY, realized_pnl=50.00)

    summary = summarize_portfolio_trade_pnl((executed, pending, failed, buy))

    assert summary.original_total_pnl == Decimal("1.50")
    assert summary.original_total_pnl_known is True
    assert summary.effective_total_pnl == Decimal("1.50")
    assert summary.effective_total_pnl_known is True
    assert summary.rows[0].realized_pnl_known is True
    assert summary.rows[1].realized_pnl_known is True
    assert summary.rows[2].realized_pnl_known is True
    assert summary.rows[3].realized_pnl_known is None
    assert summary.rows[3].effective_realized_pnl_known is None
    assert summary.rows[3].realized_pnl_status is TradePnlEvidenceStatus.NOT_APPLICABLE


def test_empty_or_buy_only_input_has_known_zero_totals() -> None:
    empty = summarize_portfolio_trade_pnl(())
    buy_only = summarize_portfolio_trade_pnl((_trade(1, action=TradeAction.BUY),))

    assert empty.rows == ()
    assert empty.original_total_pnl == Decimal("0.00")
    assert empty.original_total_pnl_known is True
    assert empty.effective_total_pnl == Decimal("0.00")
    assert empty.effective_total_pnl_known is True
    assert buy_only.original_total_pnl == Decimal("0.00")
    assert buy_only.effective_total_pnl == Decimal("0.00")


def test_money_sums_ignore_hostile_ambient_decimal_context() -> None:
    trades = (_trade(1, realized_pnl=1234.56), _trade(2, realized_pnl=-234.55))

    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        summary = summarize_portfolio_trade_pnl(trades)
        assert context.prec == 3
        assert context.traps[Inexact] is True

    assert summary.original_total_pnl == Decimal("1000.01")
    assert summary.effective_total_pnl == Decimal("1000.01")


def test_signed_total_refuses_ledger_range_overflow() -> None:
    trades = (
        _trade(1, realized_pnl=9_000_000_000_000.0),
        _trade(2, realized_pnl=9_000_000_000_000.0),
    )

    with pytest.raises(FeeCorrectionContractError, match="ledger range"):
        summarize_portfolio_trade_pnl(trades)


@pytest.mark.parametrize("bad_sequence", [None, "not-a-trade-sequence"])
def test_rejects_non_sequence_trade_input(bad_sequence: object) -> None:
    with pytest.raises(FeeCorrectionContractError, match="ordered SimulatedTrade sequence"):
        summarize_portfolio_trade_pnl(cast(tuple[SimulatedTrade, ...], bad_sequence))


def test_rejects_untyped_trade_rows() -> None:
    with pytest.raises(FeeCorrectionContractError, match="untyped row"):
        summarize_portfolio_trade_pnl((cast(SimulatedTrade, object()),))


def test_rejects_a_malformed_signed_pnl_value() -> None:
    trade = _trade(1, realized_pnl=cast(float, object()))

    with pytest.raises(FeeCorrectionContractError, match="exact ledger money"):
        summarize_portfolio_trade_pnl((trade,))
