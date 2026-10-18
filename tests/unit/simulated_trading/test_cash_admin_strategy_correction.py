"""Regression coverage for cash and cost knowledge at admin/strategy boundaries."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from django.contrib.admin.sites import AdminSite

from apps.simulated_trading.application import interface_services as simulated_interface_services
from apps.simulated_trading.interface import admin as simulated_admin
from apps.simulated_trading.models import SimulatedAccountModel, SimulatedTradeModel
from apps.strategy.application.script_engine import ScriptAPI
from apps.strategy.infrastructure.providers import DjangoPortfolioDataProvider
from core.exceptions import BusinessLogicError


@pytest.mark.parametrize(
    ("valuation_flags", "expected"),
    [([], True), ([True, True], True), ([True, False], False), ([True, None], False)],
)
def test_application_position_valuation_helper_requires_every_position_known(
    monkeypatch: pytest.MonkeyPatch,
    valuation_flags: list[bool | None],
    expected: bool,
) -> None:
    """The application helper reads through its repository provider and fails closed."""

    repository = Mock()
    repository.get_by_account.return_value = [
        SimpleNamespace(valuation_known=flag) for flag in valuation_flags
    ]
    monkeypatch.setattr(
        simulated_interface_services,
        "get_simulated_position_repository",
        lambda: repository,
    )

    assert simulated_interface_services.has_current_position_valuation(73) is expected
    repository.get_by_account.assert_called_once_with(73)


def test_admin_knowledge_helpers_use_application_services_and_reject_unsaved_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin presentation delegates persisted-account checks and fails closed without a key."""

    valuation_check = Mock(return_value=True)
    costs_check = Mock(return_value=True)
    monkeypatch.setattr(simulated_admin, "has_current_position_valuation", valuation_check)
    monkeypatch.setattr(simulated_admin, "has_complete_closed_trade_costs", costs_check)
    account_admin = simulated_admin.SimulatedAccountAdmin(
        SimulatedAccountModel,
        AdminSite(),
    )
    unsaved_account = cast(SimulatedAccountModel, SimpleNamespace(pk=None))
    persisted_account = cast(SimulatedAccountModel, SimpleNamespace(pk=73))

    assert account_admin._has_current_valuation(unsaved_account) is False
    assert account_admin._has_complete_closed_trade_costs(unsaved_account) is False
    valuation_check.assert_not_called()
    costs_check.assert_not_called()

    assert account_admin._has_current_valuation(persisted_account) is True
    assert account_admin._has_complete_closed_trade_costs(persisted_account) is True
    valuation_check.assert_called_once_with(73)
    costs_check.assert_called_once_with(73)


@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known"),
    [(None, True), (False, True), (True, None), (True, False)],
)
def test_trade_admin_hides_realized_pnl_if_cost_or_fee_evidence_is_not_complete(
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> None:
    """A stored numeric realized PnL is hidden when either evidence flag is incomplete."""

    trade_admin = simulated_admin.SimulatedTradeAdmin(SimulatedTradeModel, AdminSite())
    trade = cast(
        SimulatedTradeModel,
        SimpleNamespace(
            cost_basis_known=cost_basis_known,
            fee_amounts_known=fee_amounts_known,
            realized_pnl=Decimal("25.00"),
        ),
    )

    assert trade_admin.realized_pnl_display(trade) == "成本或费用未核实"


def test_trade_admin_keeps_known_realized_pnl_format() -> None:
    """Fully known trade evidence preserves the existing formatted value."""

    trade_admin = simulated_admin.SimulatedTradeAdmin(SimulatedTradeModel, AdminSite())
    trade = cast(
        SimulatedTradeModel,
        SimpleNamespace(
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl=Decimal("25.00"),
        ),
    )

    assert str(trade_admin.realized_pnl_display(trade)) == (
        '<span style="color: green; font-weight: bold;">¥+25.00</span>'
    )


def test_unknown_cash_error_propagates_through_strategy_provider_and_script_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown account cash never becomes the strategy provider's numeric zero fallback."""

    unknown_cash = BusinessLogicError(
        "账户现金未核实",
        code="ACCOUNT_CASH_UNKNOWN",
    )
    facade = Mock()
    facade.get_cash.side_effect = unknown_cash
    provider = DjangoPortfolioDataProvider()
    monkeypatch.setattr(provider, "_get_facade", lambda: facade)

    with pytest.raises(BusinessLogicError) as provider_error:
        provider.get_cash(73)
    assert provider_error.value is unknown_cash

    script_api = ScriptAPI(
        macro_provider=Mock(),
        regime_provider=Mock(),
        asset_pool_provider=Mock(),
        signal_provider=Mock(),
        portfolio_provider=provider,
        portfolio_id=73,
    )
    with pytest.raises(BusinessLogicError) as script_error:
        script_api.get_portfolio_cash()
    assert script_error.value is unknown_cash
    assert script_error.value.code == "ACCOUNT_CASH_UNKNOWN"
