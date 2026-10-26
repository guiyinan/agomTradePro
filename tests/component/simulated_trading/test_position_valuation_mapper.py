"""Persist and expose unknown valuation without upgrading numeric placeholders."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel
from apps.simulated_trading.infrastructure.position_repository import (
    DjangoPositionRepository,
    PositionMapper,
)
from core.exceptions import BusinessLogicError

pytestmark = pytest.mark.django_db


@pytest.fixture
def unknown_valuation_position() -> PositionModel:
    """Create actual holdings with cost and quantity, but no market-price observation."""
    owner = User.objects.create_user(username="valuation-knowledge-owner")
    account = SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name="Unvalued real holdings",
        account_type="real",
        initial_capital=Decimal("0"),
        current_cash=Decimal("0"),
        current_market_value=Decimal("0"),
        total_value=Decimal("0"),
        auto_trading_enabled=False,
    )
    return PositionModel._default_manager.create(
        account=account,
        asset_code="000001.SZ",
        asset_name="Actual holding",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("0"),
        available_quantity_known=False,
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("0"),
        market_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=0,
        first_buy_date=date(2020, 5, 20),
        first_buy_date_known=False,
        valuation_known=False,
    )


def test_mapper_round_trip_preserves_unknown_valuation(
    unknown_valuation_position: PositionModel,
) -> None:
    """Both mappings retain the knowledge flag independently of numerical values."""
    entity = PositionMapper.to_entity(unknown_valuation_position)
    assert entity.valuation_known is False
    assert entity.cost_basis_known is None
    assert entity.quantity == 100
    assert entity.avg_cost == 10
    model = PositionMapper.to_model(entity)
    assert model.valuation_known is False
    assert model.cost_basis_known is None


def test_generic_entity_save_is_rejected_without_snapshot_path(
    unknown_valuation_position: PositionModel,
) -> None:
    """The deprecated unscoped entity writer cannot mutate a persisted position."""
    position = unknown_valuation_position
    before = PositionMapper.to_entity(position)
    stale = replace(PositionMapper.to_entity(position), valuation_known=True)

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionRepository().save(stale)

    assert error.value.code == "SIMULATED_POSITION_ATOMIC_WRITE_REQUIRED"
    position.refresh_from_db()
    assert PositionMapper.to_entity(position) == before
    assert position.valuation_known is False
    assert position.cost_basis_known is None
    assert position.quantity == Decimal("100")
    assert position.total_cost == Decimal("1000")


def test_snapshot_record_save_cannot_upgrade_unknown_valuation(
    unknown_valuation_position: PositionModel,
) -> None:
    """A supplied numerical price is not an implicit grant of valuation knowledge."""
    position = unknown_valuation_position
    saved = DjangoPositionRepository().save_position_record(
        account_id=position.account_id,
        asset_code=position.asset_code,
        defaults={"current_price": Decimal("12"), "valuation_known": True},
        expected_position=PositionMapper.to_entity(position),
    )
    assert saved.pk == position.pk
    position.refresh_from_db()
    assert position.valuation_known is False
    assert position.cost_basis_known is None


def test_snapshot_save_preserves_explicit_partial_cost_basis(
    unknown_valuation_position: PositionModel,
) -> None:
    """A snapshot-bound compatibility update cannot certify an explicit partial basis."""
    position = unknown_valuation_position
    position.cost_basis_known = False
    position.save(update_fields=["cost_basis_known"])

    saved = DjangoPositionRepository().save_position_record(
        account_id=position.account_id,
        asset_code=position.asset_code,
        defaults={"cost_basis_known": True},
        expected_position=PositionMapper.to_entity(position),
    )

    assert saved.pk == position.pk
    position.refresh_from_db()
    assert position.cost_basis_known is False


def test_price_refresh_does_not_silently_certify_unqualified_valuation(
    unknown_valuation_position: PositionModel,
) -> None:
    """The legacy price-only updater lacks the source evidence to upgrade the flag."""
    position = unknown_valuation_position
    DjangoPositionRepository().update_position_prices({position.asset_code: Decimal("12")})
    position.refresh_from_db()
    assert position.valuation_known is False
    assert PositionMapper.to_entity(position).valuation_known is False
    position.account.refresh_from_db()
    assert position.account.current_market_value == Decimal("0")
    assert position.account.total_value == Decimal("0")


def test_decision_snapshot_retains_holdings_but_blocks_unknown_valuation(
    unknown_valuation_position: PositionModel,
) -> None:
    """Decision inputs cannot reinterpret a missing valuation as zero market value."""
    position = unknown_valuation_position
    snapshots = DjangoPositionRepository().get_position_snapshots(position.account_id)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["quantity"] == Decimal("100")
    assert snapshot["current_price"] is None
    assert snapshot["market_value"] is None
    assert snapshot["unrealized_pnl_pct"] is None
    assert snapshot["valuation_known"] is False
    assert snapshot["must_not_use_for_decision"] is True
    assert snapshot["blocking_reason_codes"] == ["POSITION_VALUATION_UNKNOWN"]
    assert snapshot["cost_basis_known"] is None
    assert snapshot["cost_basis_status"] == "unknown"
    assert snapshot["cost_basis_usable_for_decision"] is False


def test_decision_snapshot_hides_pnl_when_cost_basis_is_unknown(
    unknown_valuation_position: PositionModel,
) -> None:
    """A known mark does not make a historical cost-dependent return usable."""
    position = unknown_valuation_position
    position.valuation_known = True
    position.current_price = Decimal("12")
    position.market_value = Decimal("1200")
    position.unrealized_pnl_pct = 20.0
    position.save(
        update_fields=["valuation_known", "current_price", "market_value", "unrealized_pnl_pct"]
    )

    snapshot = DjangoPositionRepository().get_position_snapshots(position.account_id)[0]

    assert snapshot["valuation_known"] is True
    assert snapshot["market_value"] == Decimal("1200")
    assert snapshot["cost_basis_status"] == "unknown"
    assert snapshot["cost_basis_usable_for_decision"] is False
    assert snapshot["unrealized_pnl_pct"] is None
