"""Cross-app trade payloads expose realized PnL only with complete SELL evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.domain.entities import OrderStatus, SimulatedTrade, TradeAction


def _trade(
    trade_id: int,
    action: str,
    *,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
    realized_pnl: float | None,
    realized_pnl_pct: float | None,
    commission: float = 0.0,
    transfer_fee: float | None = None,
    stamp_duty: float | None = None,
    total_cost: float = 100.0,
    effective_realized_pnl: float | None = None,
    effective_realized_pnl_pct: float | None = None,
    fee_correction_revision: int | None = None,
    fee_correction_overlay_applied: bool = False,
) -> SimulatedTrade:
    """Build a real Trade entity with the payload reader's current fields."""

    return SimulatedTrade(
        trade_id=trade_id,
        account_id=3,
        asset_code="000001.SZ",
        asset_name="payload fixture",
        asset_type="equity",
        action=TradeAction(action),
        quantity=10.0,
        price=11.0,
        amount=110.0,
        commission=commission,
        slippage=0.0,
        total_cost=total_cost,
        fee_amounts_known=fee_amounts_known,
        cost_basis_known=cost_basis_known,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        effective_realized_pnl=effective_realized_pnl,
        effective_realized_pnl_pct=effective_realized_pnl_pct,
        transfer_fee=transfer_fee,
        stamp_duty=stamp_duty,
        fee_correction_revision=fee_correction_revision,
        fee_correction_overlay_applied=fee_correction_overlay_applied,
        reason="fixture",
        signal_id=None,
        order_date=date(2026, 10, 19),
        execution_date=date(2026, 10, 19),
        execution_time=datetime(2026, 10, 19, 1, 30, tzinfo=UTC),
        status=OrderStatus.EXECUTED,
    )


def test_account_trade_payload_hides_unverified_sell_pnl_and_preserves_complete_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete SELL's numeric placeholder cannot appear as realized PnL."""

    trades = [
        _trade(
            1,
            "sell",
            cost_basis_known=None,
            fee_amounts_known=None,
            realized_pnl=7.0,
            realized_pnl_pct=7.0,
        ),
        _trade(
            2,
            "sell",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=25.0,
            realized_pnl_pct=12.5,
        ),
        _trade(
            3,
            "buy",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=None,
            realized_pnl_pct=None,
        ),
        _trade(
            4,
            "sell",
            cost_basis_known=None,
            fee_amounts_known=True,
            realized_pnl=3.0,
            realized_pnl_pct=3.0,
        ),
        _trade(
            5,
            "sell",
            cost_basis_known=True,
            fee_amounts_known=None,
            realized_pnl=4.0,
            realized_pnl_pct=4.0,
        ),
        _trade(
            6,
            "sell",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=0.0,
            realized_pnl_pct=0.0,
            commission=0.0,
            transfer_fee=0.0,
            stamp_duty=0.0,
            total_cost=0.0,
        ),
        _trade(
            7,
            "sell",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=25.0,
            realized_pnl_pct=12.5,
            effective_realized_pnl=20.0,
            effective_realized_pnl_pct=10.0,
            fee_correction_revision=1,
            fee_correction_overlay_applied=True,
        ),
        _trade(
            8,
            "sell",
            cost_basis_known=True,
            fee_amounts_known=False,
            realized_pnl=5.0,
            realized_pnl_pct=5.0,
            commission=0.0,
            total_cost=0.0,
        ),
    ]
    monkeypatch.setattr(
        interface_services,
        "get_simulated_trade_repository",
        lambda: SimpleNamespace(get_by_account=lambda account_id: trades),
    )

    payloads = interface_services.list_account_trade_payloads(account_id=3, limit=10)
    by_trade_id = {payload["trade_id"]: payload for payload in payloads}

    incomplete = by_trade_id[1]
    assert incomplete["realized_pnl"] is None
    assert incomplete["realized_pnl_pct"] is None
    assert incomplete["effective_realized_pnl"] is None
    assert incomplete["effective_realized_pnl_pct"] is None
    assert incomplete["effective_realized_pnl_known"] is False
    assert incomplete["original_realized_pnl"] == "7.0"
    assert incomplete["original_realized_pnl_pct"] == 7.0
    assert incomplete["cost_basis_known"] is None
    assert incomplete["cost_basis_status"] == "unknown"
    assert incomplete["fee_amounts_known"] is None
    assert incomplete["fee_amounts_status"] == "unknown"
    assert incomplete["effective_commission"] is None
    assert incomplete["effective_transfer_fee"] is None
    assert incomplete["effective_stamp_duty"] is None
    assert incomplete["effective_total_cost"] is None

    complete = by_trade_id[2]
    assert complete["realized_pnl"] == "25.0"
    assert complete["realized_pnl_pct"] == 12.5
    assert complete["effective_realized_pnl"] == "25.0"
    assert complete["effective_realized_pnl_pct"] == 12.5
    assert complete["effective_realized_pnl_known"] is True
    assert complete["cost_basis_known"] is True
    assert complete["cost_basis_status"] == "known"
    assert complete["fee_amounts_known"] is True
    assert complete["fee_amounts_status"] == "known"

    buy = by_trade_id[3]
    assert buy["action"] == "buy"
    assert buy["realized_pnl"] is None
    assert buy["realized_pnl_pct"] is None
    assert buy["effective_realized_pnl_pct"] is None

    unknown_cost = by_trade_id[4]
    assert unknown_cost["effective_realized_pnl_known"] is False
    assert unknown_cost["effective_realized_pnl_pct"] is None
    assert unknown_cost["original_realized_pnl"] == "3.0"
    assert unknown_cost["original_realized_pnl_pct"] == 3.0

    unknown_fees = by_trade_id[5]
    assert unknown_fees["effective_realized_pnl_known"] is False
    assert unknown_fees["effective_realized_pnl_pct"] is None
    assert unknown_fees["original_realized_pnl"] == "4.0"
    assert unknown_fees["original_realized_pnl_pct"] == 4.0
    assert unknown_fees["effective_commission"] is None
    assert unknown_fees["effective_transfer_fee"] is None
    assert unknown_fees["effective_stamp_duty"] is None
    assert unknown_fees["effective_total_cost"] is None

    partial_fees = by_trade_id[8]
    assert partial_fees["fee_amounts_known"] is False
    assert partial_fees["fee_amounts_status"] == "partial"
    assert partial_fees["effective_commission"] is None
    assert partial_fees["effective_transfer_fee"] is None
    assert partial_fees["effective_stamp_duty"] is None
    assert partial_fees["effective_total_cost"] is None

    known_zero = by_trade_id[6]
    assert known_zero["effective_realized_pnl_known"] is True
    assert known_zero["effective_realized_pnl"] == "0.0"
    assert known_zero["effective_realized_pnl_pct"] == 0.0
    assert known_zero["effective_commission"] == "0.0"
    assert known_zero["effective_transfer_fee"] == "0.0"
    assert known_zero["effective_stamp_duty"] == "0.0"
    assert known_zero["effective_total_cost"] == "0.0"

    overlaid = by_trade_id[7]
    assert overlaid["effective_realized_pnl_known"] is True
    assert overlaid["effective_realized_pnl"] == "20.0"
    assert overlaid["effective_realized_pnl_pct"] == 10.0
    assert overlaid["original_realized_pnl"] == "25.0"
    assert overlaid["original_realized_pnl_pct"] == 12.5
