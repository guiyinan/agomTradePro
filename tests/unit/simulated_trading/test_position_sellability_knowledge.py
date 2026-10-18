"""Unknown sellability must remain distinct from a verified available balance."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import query_services
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.domain.rules import TradingConstraintRule


def _position(*, available: float) -> Position:
    """Build a complete position whose recorded numeric balance may be unverified."""
    return Position(
        account_id=7,
        asset_code="600000.SH",
        asset_name="holding",
        asset_type="equity",
        quantity=300.0,
        available_quantity=available,
        avg_cost=10.0,
        total_cost=3000.0,
        current_price=10.0,
        market_value=3000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 1, 5),
        last_update_date=date(2026, 1, 5),
    )


@pytest.mark.parametrize("available", [0.0, 300.0])
def test_unverified_numeric_balance_cannot_authorize_a_sell(available: float) -> None:
    """Neither a storage zero nor all shares establishes known sellability."""
    position = _position(available=available)
    position.available_quantity_known = False

    allowed, reason = TradingConstraintRule.validate_sell_order(position, 100.0, 10.0)

    assert allowed is False
    assert "未核实" in reason


def test_existing_known_position_keeps_its_successful_sell_contract() -> None:
    """The compatibility default does not prevent an existing valid simulated sell."""
    position = _position(available=300.0)

    assert position.available_quantity_known is True
    assert TradingConstraintRule.validate_sell_order(position, 100.0, 10.0) == (True, "")


@pytest.mark.parametrize("available", [0.0, 300.0])
def test_execution_risk_projection_rejects_unknown_sellability(
    monkeypatch: pytest.MonkeyPatch,
    available: float,
) -> None:
    """Live risk consumers cannot treat an unverified stored number as evidence."""
    position = _position(available=available)
    position.available_quantity_known = False
    account = SimpleNamespace(
        account_id=7,
        account_type="real",
        is_active=True,
        total_value=4000.0,
        current_cash=1000.0,
        cash_known=True,
        current_market_value=3000.0,
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

    assert query_services.get_account_execution_projection(user_id=19, account_id=7) is None
