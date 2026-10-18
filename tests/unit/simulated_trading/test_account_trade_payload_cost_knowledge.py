"""Cross-app trade payloads expose realized PnL only with complete SELL evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import interface_services


def _knowledge_status(value: bool | None) -> str:
    """Return the stable knowledge label expected from the trade entity."""

    if value is True:
        return "known"
    if value is False:
        return "partial"
    return "unknown"


def _trade(
    trade_id: str,
    action: str,
    *,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
    realized_pnl: Decimal | None,
    realized_pnl_pct: float | None,
) -> SimpleNamespace:
    """Build the complete simulated-trade row contract consumed by the payload reader."""

    return SimpleNamespace(
        trade_id=trade_id,
        account_id=3,
        asset_code="000001.SZ",
        asset_name="payload fixture",
        asset_type="equity",
        action=SimpleNamespace(value=action),
        quantity=Decimal("10.000000"),
        price=Decimal("11.0000"),
        amount=Decimal("110.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("100.00"),
        fee_amounts_known=fee_amounts_known,
        fee_amounts_status=_knowledge_status(fee_amounts_known),
        cost_basis_known=cost_basis_known,
        cost_basis_status=_knowledge_status(cost_basis_known),
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        reason="fixture",
        signal_id=None,
        order_date=date(2026, 10, 19),
        execution_date=date(2026, 10, 19),
        execution_time=datetime(2026, 10, 19, 1, 30, tzinfo=UTC),
        status=SimpleNamespace(value="executed"),
    )


def test_account_trade_payload_hides_unverified_sell_pnl_and_preserves_complete_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete SELL's numeric placeholder cannot appear as realized PnL."""

    trades = [
        _trade(
            "incomplete-sell",
            "sell",
            cost_basis_known=None,
            fee_amounts_known=None,
            realized_pnl=Decimal("7.00"),
            realized_pnl_pct=7.0,
        ),
        _trade(
            "complete-sell",
            "sell",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=Decimal("25.00"),
            realized_pnl_pct=12.5,
        ),
        _trade(
            "buy",
            "buy",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=None,
            realized_pnl_pct=None,
        ),
    ]
    monkeypatch.setattr(
        interface_services,
        "get_simulated_trade_repository",
        lambda: SimpleNamespace(get_by_account=lambda account_id: trades),
    )

    payloads = interface_services.list_account_trade_payloads(account_id=3, limit=10)
    by_trade_id = {payload["trade_id"]: payload for payload in payloads}

    incomplete = by_trade_id["incomplete-sell"]
    assert incomplete["realized_pnl"] is None
    assert incomplete["realized_pnl_pct"] is None
    assert incomplete["cost_basis_known"] is None
    assert incomplete["cost_basis_status"] == "unknown"
    assert incomplete["fee_amounts_known"] is None
    assert incomplete["fee_amounts_status"] == "unknown"

    complete = by_trade_id["complete-sell"]
    assert complete["realized_pnl"] == "25.00"
    assert complete["realized_pnl_pct"] == 12.5
    assert complete["cost_basis_known"] is True
    assert complete["cost_basis_status"] == "known"
    assert complete["fee_amounts_known"] is True
    assert complete["fee_amounts_status"] == "known"

    buy = by_trade_id["buy"]
    assert buy["action"] == "buy"
    assert buy["realized_pnl"] is None
    assert buy["realized_pnl_pct"] is None
