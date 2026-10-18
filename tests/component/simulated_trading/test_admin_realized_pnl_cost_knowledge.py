"""Admin realized-PnL coverage respects cost and fee knowledge on executed sells."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository


@pytest.mark.django_db
def test_admin_realized_pnl_marks_executed_sell_total_unknown_with_incomplete_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only fully known executed SELLs contribute to a known total."""

    suffix = uuid4().hex[:10]
    account = SimulatedAccountModel._default_manager.create(
        account_name=f"admin-pnl-{suffix}",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
    )
    day = date.today()

    def add_sell(
        *,
        code: str,
        status: str,
        cost_basis_known: bool | None,
        fee_amounts_known: bool | None,
        realized_pnl: Decimal | None,
    ) -> SimulatedTradeModel:
        return SimulatedTradeModel._default_manager.create(
            account=account,
            asset_code=code,
            asset_name="Coverage fixture",
            asset_type="equity",
            action="sell",
            quantity=Decimal("10.000000"),
            price=Decimal("11.0000"),
            amount=Decimal("110.00"),
            commission=Decimal("0.00"),
            total_cost=Decimal("100.00"),
            cost_basis_known=cost_basis_known,
            fee_amounts_known=fee_amounts_known,
            realized_pnl=realized_pnl,
            realized_pnl_pct=10.0 if realized_pnl is not None else None,
            order_date=day,
            execution_date=day,
            status=status,
        )

    complete = add_sell(
        code=f"A{suffix[:8]}",
        status="executed",
        cost_basis_known=True,
        fee_amounts_known=True,
        realized_pnl=Decimal("10.00"),
    )
    cancelled = add_sell(
        code=f"C{suffix[:8]}",
        status="cancelled",
        cost_basis_known=None,
        fee_amounts_known=None,
        realized_pnl=None,
    )
    monkeypatch.setattr(
        interface_services,
        "get_simulated_account_repository",
        lambda: SimpleNamespace(
            count_active_account_models=lambda: 1,
            sum_active_total_value=lambda: Decimal("10000.00"),
            get_active_accounts=lambda: [
                SimpleNamespace(
                    account_id=int(account.pk),
                    cash_known=True,
                    total_value=Decimal("10000.00"),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        interface_services,
        "get_simulated_position_repository",
        lambda: SimpleNamespace(
            count_position_models=lambda: 0,
            get_by_account=lambda account_id: [],
        ),
    )
    monkeypatch.setattr(
        interface_services,
        "get_simulated_trade_repository",
        lambda: DjangoTradeRepository(),
    )

    known_dashboard = interface_services.build_admin_dashboard_context()
    assert known_dashboard["total_capital"] == Decimal("10000.00")
    assert known_dashboard["total_pnl"] == Decimal("10.00")
    assert known_dashboard["total_pnl_known"] is True
    assert known_dashboard["total_pnl_covered_sell_count"] == 1
    assert known_dashboard["total_pnl_executed_sell_count"] == 1

    # Add incomplete executed sells after checking the non-executed contrast.
    incomplete = [
        add_sell(
            code=f"F{suffix[:6]}",
            status="executed",
            cost_basis_known=False,
            fee_amounts_known=True,
            realized_pnl=Decimal("7.00"),
        ),
        add_sell(
            code=f"N{suffix[:6]}",
            status="executed",
            cost_basis_known=None,
            fee_amounts_known=True,
            realized_pnl=Decimal("8.00"),
        ),
        add_sell(
            code=f"G{suffix[:6]}",
            status="executed",
            cost_basis_known=True,
            fee_amounts_known=False,
            realized_pnl=Decimal("9.00"),
        ),
        add_sell(
            code=f"M{suffix[:6]}",
            status="executed",
            cost_basis_known=True,
            fee_amounts_known=None,
            realized_pnl=Decimal("10.00"),
        ),
        add_sell(
            code=f"P{suffix[:6]}",
            status="executed",
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=None,
        ),
    ]
    dashboard = interface_services.build_admin_dashboard_context()

    assert dashboard["total_capital"] == Decimal("10000.00")
    assert dashboard["total_pnl"] is None
    assert dashboard["total_pnl_known"] is False
    assert dashboard["total_pnl_covered_sell_count"] == 1
    assert dashboard["total_pnl_executed_sell_count"] == 6
    cancelled.refresh_from_db()
    assert cancelled.status == "cancelled"
    assert complete.realized_pnl == Decimal("10.00")
    for trade in incomplete:
        trade.refresh_from_db()
        assert trade.quantity == Decimal("10.000000")
        assert trade.total_cost == Decimal("100.00")
