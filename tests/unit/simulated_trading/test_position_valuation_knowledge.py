"""A numeric valuation placeholder cannot authorize decisions or look like a quote."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import query_services
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    Position,
)
from apps.simulated_trading.domain.rules import TradingConstraintRule


def _position() -> Position:
    """Create a holding with true quantities and a zero valuation storage placeholder."""
    return Position(
        account_id=7,
        asset_code="600000.SH",
        asset_name="Unvalued economic holding",
        asset_type="equity",
        quantity=300,
        available_quantity=300,
        avg_cost=10,
        total_cost=3000,
        current_price=0,
        market_value=0,
        unrealized_pnl=0,
        unrealized_pnl_pct=0,
        first_buy_date=date(2020, 5, 20),
        last_update_date=date(2020, 5, 20),
    )


def _install_repositories(monkeypatch: pytest.MonkeyPatch, position: Position) -> None:
    """Inject a complete read scope without creating any account or price source."""
    account = SimpleNamespace(
        account_id=7,
        account_name="Actual holdings",
        account_type="simulated",
        is_active=True,
        total_value=1000,
        current_cash=1000,
        current_market_value=0,
        initial_capital=1000,
        total_return=0,
        cash_known=True,
        cash_reconciliation_status=AccountCashReconciliationStatus.SIMULATED_LEDGER,
    )
    monkeypatch.setattr(
        query_services,
        "get_simulated_account_repository",
        lambda: SimpleNamespace(get_by_user=lambda user_id: [account]),
    )
    monkeypatch.setattr(
        query_services,
        "get_simulated_position_repository",
        lambda: SimpleNamespace(get_by_account=lambda account_id: [position]),
    )


def test_existing_valuation_default_is_compatible_but_not_a_freshness_proof() -> None:
    """Existing valid numerical valuations retain their old compatibility semantics."""
    assert _position().valuation_known is True


def test_unknown_valuation_does_not_authorize_an_ordinary_simulated_sell() -> None:
    """Explicit fill price does not establish the rest of the portfolio valuation."""
    position = _position()
    position.valuation_known = False
    allowed, reason = TradingConstraintRule.validate_sell_order(position, 100, 11.25)
    assert allowed is False
    assert "估值" in reason


def test_unknown_valuation_blocks_live_risk_projection_even_when_sellability_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete risk projection must not present a storage zero as market value."""
    position = _position()
    position.valuation_known = False
    _install_repositories(monkeypatch, position)
    assert query_services.get_account_execution_projection(user_id=19, account_id=7) is None


def test_unknown_valuation_is_null_in_user_position_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quantity and cost remain visible while unknown price and PnL are explicit."""
    position = _position()
    position.valuation_known = False
    _install_repositories(monkeypatch, position)
    rows = query_services.list_user_position_payloads(user_id=19)
    assert len(rows) == 1
    row = rows[0]
    assert row["shares"] == 300
    assert row["avg_cost"] == 10
    assert row["current_price"] is None
    assert row["market_value"] is None
    assert row["unrealized_pnl"] is None
    assert row["unrealized_pnl_pct"] is None
    assert row["valuation_known"] is False
    assert row["valuation_status"] == "unknown"


def test_unknown_holding_makes_account_totals_incomplete_without_hiding_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account's cached numeric placeholder is not complete portfolio equity."""
    position = _position()
    position.valuation_known = False
    _install_repositories(monkeypatch, position)
    totals = query_services.get_user_account_totals(19)
    assert totals is not None
    assert totals["cash_balance"] == 1000
    assert totals["initial_capital"] == 1000
    for field in (
        "total_assets",
        "invested_value",
        "invested_ratio",
        "total_return",
        "total_return_pct",
    ):
        assert totals[field] is None


def test_unknown_holding_is_explicit_in_dashboard_account_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached account values cannot turn an unvalued position into verified zero."""
    position = _position()
    position.valuation_known = False
    _install_repositories(monkeypatch, position)
    card = query_services.list_dashboard_account_payloads(19)[0]
    assert card["cash"] == 1000
    assert card["market_value"] is None
    assert card["total_value"] is None
    assert card["total_return"] is None
    assert card["valuation_known"] is False
    assert card["blocking_reason_codes"] == ["POSITION_VALUATION_UNKNOWN"]


def test_dashboard_gateway_preserves_nullable_account_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-app gateway must retain null rather than drop unknown values."""
    from apps.dashboard.application.integration_gateways import DashboardApplicationGateway

    position = _position()
    position.valuation_known = False
    _install_repositories(monkeypatch, position)
    totals = DashboardApplicationGateway().get_user_account_totals(19)
    assert totals is not None
    assert "total_assets" in totals
    assert totals["total_assets"] is None
    assert totals["invested_value"] is None
    assert totals["cash_balance"] == 1000
