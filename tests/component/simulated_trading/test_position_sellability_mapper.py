"""Persistence regressions for Position sellability knowledge."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.position_repository import (
    DjangoPositionMutationRepository,
    DjangoPositionRepository,
    PositionMapper,
)
from core.exceptions import BusinessLogicError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@pytest.fixture
def simulated_account() -> Iterator[SimulatedAccountModel]:
    """Create or reuse only the schema required for a persisted position mapping."""

    user_model = get_user_model()
    with isolated_schema(
        (
            user_model,
            AccountProfileModel,
            SimulatedAccountModel,
            PositionModel,
            SimulatedTradeModel,
        )
    ):
        user = user_model.objects.create_user(
            username="position-sellability-owner",
            password="unused",
        )
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="position-sellability-account",
            account_type="simulated",
            initial_capital=Decimal("100000.00"),
            current_cash=Decimal("100000.00"),
            current_market_value=Decimal("0.00"),
            total_value=Decimal("100000.00"),
            is_active=True,
        )
        yield account


def _install_interleaved_position_insert(
    monkeypatch: pytest.MonkeyPatch,
    *,
    competing_position: dict[str, Any],
) -> list[PositionModel]:
    """Insert a real competing row after an empty lookup or before its replacement lookup."""

    inserted: list[PositionModel] = []
    original_first = QuerySet.first
    original_get_or_create = QuerySet.get_or_create

    def insert_competing_position(queryset: QuerySet[PositionModel]) -> None:
        if queryset.model is PositionModel and not inserted:
            inserted.append(PositionModel._default_manager.create(**competing_position))

    def first_with_interleaving(
        queryset: QuerySet[PositionModel],
    ) -> PositionModel | None:
        result = original_first(queryset)
        if queryset.model is PositionModel and result is None:
            insert_competing_position(queryset)
        return result

    def get_or_create_with_interleaving(
        queryset: QuerySet[PositionModel],
        defaults: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[PositionModel, bool]:
        insert_competing_position(queryset)
        return original_get_or_create(queryset, defaults=defaults, **kwargs)

    monkeypatch.setattr(QuerySet, "first", first_with_interleaving)
    monkeypatch.setattr(QuerySet, "get_or_create", get_or_create_with_interleaving)
    return inserted


def test_position_mapper_and_repository_save_preserve_unknown_sellability(
    simulated_account: SimulatedAccountModel,
) -> None:
    """False survives Domain/ORM mapping and a real repository insert/read roundtrip."""

    position = Position(
        account_id=simulated_account.pk,
        asset_code="600000.SH",
        asset_name="Sellability fixture",
        asset_type="equity",
        quantity=100.0,
        available_quantity=40.0,
        avg_cost=10.0,
        total_cost=1000.0,
        current_price=10.0,
        market_value=1000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
        last_update_date=date(2026, 10, 1),
        available_quantity_known=False,
    )

    mapped_model = PositionMapper.to_model(position)
    assert mapped_model.available_quantity_known is False
    mapped_entity = PositionMapper.to_entity(mapped_model)
    assert mapped_entity.available_quantity_known is False

    repository = DjangoPositionRepository()
    persisted_model = repository.save_position_record(
        account_id=simulated_account.pk,
        asset_code=mapped_entity.asset_code,
        defaults={
            "asset_name": mapped_entity.asset_name,
            "asset_type": mapped_entity.asset_type,
            "quantity": mapped_model.quantity,
            "available_quantity": mapped_model.available_quantity,
            "available_quantity_known": mapped_model.available_quantity_known,
            "avg_cost": mapped_model.avg_cost,
            "total_cost": mapped_model.total_cost,
            "current_price": mapped_model.current_price,
            "market_value": mapped_model.market_value,
            "unrealized_pnl": mapped_model.unrealized_pnl,
            "unrealized_pnl_pct": mapped_model.unrealized_pnl_pct,
            "first_buy_date": mapped_model.first_buy_date,
            "first_buy_date_known": mapped_model.first_buy_date_known,
            "valuation_known": mapped_model.valuation_known,
            "cost_basis_known": mapped_model.cost_basis_known,
        },
    )
    position_id = persisted_model.pk
    assert position_id is not None
    persisted = PositionModel.objects.get(pk=position_id)
    assert persisted.available_quantity_known is False

    persisted_entity = repository.get_position(simulated_account.pk, "600000.SH")
    assert persisted_entity is not None
    assert persisted_entity.available_quantity_known is False


def test_save_position_record_does_not_upgrade_flags_when_row_appears_after_empty_read(
    simulated_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The incoming numeric facts update a row while both unknown flags stay false."""

    asset_code = "600001.SH"
    inserted = _install_interleaved_position_insert(
        monkeypatch,
        competing_position={
            "account": simulated_account,
            "asset_code": asset_code,
            "asset_name": "Concurrent row",
            "asset_type": "equity",
            "quantity": Decimal("60.000000"),
            "available_quantity": Decimal("20.000000"),
            "available_quantity_known": False,
            "avg_cost": Decimal("9.0000"),
            "total_cost": Decimal("540.00"),
            "current_price": Decimal("10.0000"),
            "market_value": Decimal("600.00"),
            "unrealized_pnl": Decimal("60.00"),
            "unrealized_pnl_pct": 11.1111,
            "first_buy_date": date(2026, 9, 30),
            "first_buy_date_known": False,
        },
    )
    defaults: dict[str, Any] = {
        "asset_name": "Latest repository facts",
        "asset_type": "equity",
        "quantity": Decimal("125.000000"),
        "available_quantity": Decimal("45.000000"),
        "available_quantity_known": True,
        "avg_cost": Decimal("10.0000"),
        "total_cost": Decimal("1250.00"),
        "current_price": Decimal("10.5000"),
        "market_value": Decimal("1312.50"),
        "unrealized_pnl": Decimal("62.50"),
        "unrealized_pnl_pct": 5.0,
        "first_buy_date": date(2026, 10, 1),
        "first_buy_date_known": True,
    }

    result = DjangoPositionRepository().save_position_record(
        account_id=simulated_account.pk,
        asset_code=asset_code,
        defaults=defaults,
    )

    persisted = PositionModel.objects.get(
        account_id=simulated_account.pk,
        asset_code=asset_code,
    )
    assert len(inserted) == 1
    assert result.pk == inserted[0].pk == persisted.pk
    assert persisted.available_quantity_known is False
    assert persisted.first_buy_date_known is False
    assert persisted.quantity == Decimal("125.000000")
    assert persisted.available_quantity == Decimal("45.000000")
    assert persisted.total_cost == Decimal("1250.00")


@pytest.mark.parametrize(
    ("concurrent_sellability_known", "expected_error_code"),
    [(False, "SELLABLE_BALANCE_UNKNOWN"), (True, "POSITION_CHANGED_RETRY_REQUIRED")],
)
def test_buy_mutation_rejects_changed_position_when_row_appears_after_empty_read(
    simulated_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    concurrent_sellability_known: bool,
    expected_error_code: str,
) -> None:
    """A competing balance blocks stale buy defaults without a trade or cash mutation."""

    asset_code = "600002.SH"
    inserted = _install_interleaved_position_insert(
        monkeypatch,
        competing_position={
            "account": simulated_account,
            "asset_code": asset_code,
            "asset_name": "Concurrent unknown row",
            "asset_type": "equity",
            "quantity": Decimal("100.000000"),
            "available_quantity": Decimal("35.000000"),
            "available_quantity_known": concurrent_sellability_known,
            "avg_cost": Decimal("10.0000"),
            "total_cost": Decimal("1000.00"),
            "current_price": Decimal("10.0000"),
            "market_value": Decimal("1000.00"),
            "unrealized_pnl": Decimal("0.00"),
            "unrealized_pnl_pct": 0.0,
            "first_buy_date": date(2026, 9, 30),
            "first_buy_date_known": False,
        },
    )
    position_defaults: dict[str, Any] = {
        "asset_name": "Racing buy request",
        "asset_type": "equity",
        "quantity": Decimal("150.000000"),
        "available_quantity": Decimal("35.000000"),
        "available_quantity_known": True,
        "avg_cost": Decimal("10.1755"),
        "total_cost": Decimal("1526.33"),
        "current_price": Decimal("10.5000"),
        "market_value": Decimal("1575.00"),
        "unrealized_pnl": Decimal("48.67"),
        "unrealized_pnl_pct": 3.1875,
        "first_buy_date": date(2026, 9, 30),
        "first_buy_date_known": True,
    }
    trade_payload: dict[str, Any] = {
        "account": simulated_account,
        "asset_code": asset_code,
        "asset_name": "Racing buy request",
        "asset_type": "equity",
        "action": "buy",
        "quantity": Decimal("50.000000"),
        "price": Decimal("10.5000"),
        "amount": Decimal("525.00"),
        "commission": Decimal("1.05"),
        "transfer_fee": Decimal("0.03"),
        "stamp_duty": Decimal("0.00"),
        "slippage": Decimal("0.25"),
        "total_cost": Decimal("526.33"),
        "order_date": date(2026, 10, 2),
        "execution_date": date(2026, 10, 2),
        "execution_time": datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
        "status": "executed",
    }

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
            account_id=simulated_account.pk,
            asset_code=asset_code,
            position_defaults=position_defaults,
            trade_payload=trade_payload,
        )

    assert error.value.code == expected_error_code
    assert len(inserted) == 1
    assert inserted[0].available_quantity_known is concurrent_sellability_known
    assert inserted[0].first_buy_date_known is False
    assert inserted[0].quantity == Decimal("100.000000")
    assert SimulatedTradeModel.objects.filter(account=simulated_account).count() == 0
    simulated_account.refresh_from_db()
    assert simulated_account.current_cash == Decimal("100000.00")
