"""Failure-first tests for direct Position writes after retained V4 receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection, models
from django.test.utils import CaptureQueriesContext

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.position_mapper import PositionMapper
from apps.simulated_trading.infrastructure.position_repository import DjangoPositionRepository
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
    _current_v3_plan,
    _intent,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _invoke,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


def _persist_terminal_v4_fill(
    harness: _Harness,
) -> tuple[SimulatedOrderReservationModel, SimulatedTradeModel, SimulatedOrderFillReceiptModel]:
    """Persist a real final fill using the established reservation/fill writers."""

    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    event = replace(
        rows.event,
        event_kind=LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("100.000000"),
        event_payload_hash="f" * 64,
    )
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    result = _invoke(repository, event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
    reservation = SimulatedOrderReservationModel.objects.get(pk=result.reservation_id)
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade_id=trade.pk)
    assert reservation.status == SimulatedOrderReservationModel.STATUS_COMPLETED
    assert trade.settlement_plan_binding_version == 4
    assert receipt.reservation_id == reservation.pk
    return reservation, trade, receipt


def _position_scope_snapshot(account_id: int, asset_code: str) -> tuple[object, ...]:
    """Capture every local ledger row that direct Position writes could disturb."""

    positions = tuple(
        PositionModel._base_manager.filter(
            account_id=account_id, asset_code=asset_code
        ).values_list(
            "asset_type",
            "quantity",
            "available_quantity",
            "available_quantity_known",
            "avg_cost",
            "total_cost",
            "cost_basis_known",
            "current_price",
            "market_value",
            "valuation_known",
            "first_buy_date",
            "first_buy_date_known",
            "last_update_date",
            "is_invalidated",
            "invalidation_reason",
            "invalidation_checked_at",
        )
    )
    account = tuple(
        SimulatedAccountModel._base_manager.filter(pk=account_id)
        .values_list("current_cash", "current_market_value", "total_value", "total_trades")
        .get()
    )
    trades = tuple(
        SimulatedTradeModel._base_manager.filter(account_id=account_id)
        .order_by("pk")
        .values_list(
            "pk",
            "asset_code",
            "quantity",
            "total_cost",
            "settlement_plan_binding_version",
        )
    )
    reservations = tuple(
        SimulatedOrderReservationModel._base_manager.filter(account_id=account_id)
        .order_by("pk")
        .values_list(
            "pk",
            "status",
            "filled_quantity",
            "cash_consumed",
            "cash_released",
            "shares_consumed",
            "shares_released",
        )
    )
    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            models.Q(reservation__account_id=account_id, reservation__asset_code=asset_code)
            | models.Q(trade__account_id=account_id, trade__asset_code=asset_code)
        )
        .order_by("pk")
        .values_list("pk", "reservation_id", "trade_id", "receipt_hash")
    )
    return positions, account, trades, reservations, receipts


def _assert_blocked_without_writes(
    operation: Callable[[], object],
    *,
    account_id: int,
    asset_code: str,
    expected_state: tuple[object, ...],
) -> None:
    """Require the typed history block before any financial SQL write."""

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            operation()
    assert blocked.value.code == "ORDER_FILL_HISTORY_RETAINED"
    write_statements = tuple(
        query["sql"].lstrip().split(None, 1)[0].upper()
        for query in captured.captured_queries
        if query["sql"].lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    )
    assert write_statements == ()
    assert _position_scope_snapshot(account_id, asset_code) == expected_state


def _position_defaults() -> dict[str, object]:
    """Return a complete Position create payload using declared model fields."""

    return {
        "asset_name": "Unrelated test security",
        "asset_type": "equity",
        "quantity": Decimal("2.000000"),
        "available_quantity": Decimal("2.000000"),
        "avg_cost": Decimal("10.0000"),
        "total_cost": Decimal("20.00"),
        "current_price": Decimal("10.0000"),
        "market_value": Decimal("20.00"),
        "unrealized_pnl": Decimal("0.00"),
        "first_buy_date": date(2026, 10, 16),
    }


def _create_other_account(account: SimulatedAccountModel) -> SimulatedAccountModel:
    """Create a separate simulated owner scope for cross-link fixtures."""

    return SimulatedAccountModel.objects.create(
        user_id=account.user_id,
        account_name=f"unrelated-{account.pk}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
        is_active=True,
    )


def test_terminal_v4_fill_blocks_unledgered_position_resources_and_delete(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Direct quantity, sellability, cost, type, and delete changes write nothing."""

    del persisted_receipt_schema
    _persist_terminal_v4_fill(reservation_harness)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    position_entity = PositionMapper.to_entity(position)
    changed_position = replace(
        position_entity,
        quantity=position_entity.quantity + 1.0,
        total_cost=position_entity.total_cost + position_entity.avg_cost,
    )
    repository = DjangoPositionRepository()
    expected_state = _position_scope_snapshot(
        reservation_harness.account.pk,
        position.asset_code,
    )
    operations: tuple[Callable[[], object], ...] = (
        lambda: repository.save(changed_position),
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code=position.asset_code,
            defaults={"available_quantity": position.available_quantity - Decimal("1.000000")},
        ),
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code=position.asset_code,
            defaults={"avg_cost": position.avg_cost + Decimal("0.1000")},
        ),
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code=position.asset_code,
            defaults={"asset_type": "fund"},
        ),
        lambda: repository.delete(reservation_harness.account.pk, position.asset_code),
    )
    for operation in operations:
        _assert_blocked_without_writes(
            operation,
            account_id=reservation_harness.account.pk,
            asset_code=position.asset_code,
            expected_state=expected_state,
        )


def test_terminal_v4_history_blocks_recreating_a_missing_position(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A missing projection row cannot be rebuilt by an unledgered direct save."""

    del persisted_receipt_schema
    _persist_terminal_v4_fill(reservation_harness)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    position_entity = PositionMapper.to_entity(position)
    models.QuerySet.delete(PositionModel._base_manager.filter(pk=position.pk))
    assert not PositionModel.objects.filter(pk=position.pk).exists()
    expected_state = _position_scope_snapshot(
        reservation_harness.account.pk,
        "600000.SH",
    )
    repository = DjangoPositionRepository()
    _assert_blocked_without_writes(
        lambda: repository.save(position_entity),
        account_id=reservation_harness.account.pk,
        asset_code="600000.SH",
        expected_state=expected_state,
    )
    _assert_blocked_without_writes(
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code="600000.SH",
            defaults=_position_defaults(),
        ),
        account_id=reservation_harness.account.pk,
        asset_code="600000.SH",
        expected_state=expected_state,
    )


def test_price_and_invalidation_updates_remain_available_after_terminal_v4_fill(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Non-resource quote and invalidation updates remain outside the new gate."""

    del persisted_receipt_schema
    _persist_terminal_v4_fill(reservation_harness)
    repository = DjangoPositionRepository()
    changes = repository.update_position_prices({"600000.SH": Decimal("11.0000")})
    assert len(changes) == 1
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    assert position.current_price == Decimal("11.0000")
    assert position.quantity == Decimal("200.000000")
    assert repository.mark_invalidated(
        reservation_harness.account.pk,
        "600000.SH",
        "component test invalidation",
        AS_OF,
    )
    position.refresh_from_db()
    assert position.is_invalidated is True
    assert position.quantity == Decimal("200.000000")


def test_unrelated_account_or_asset_position_writes_remain_available(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """History blocks only its account-and-asset scope."""

    del persisted_receipt_schema
    _persist_terminal_v4_fill(reservation_harness)
    repository = DjangoPositionRepository()
    same_account_other_asset = repository.save_position_record(
        account_id=reservation_harness.account.pk,
        asset_code="600001.SH",
        defaults=_position_defaults(),
    )
    other_account = _create_other_account(reservation_harness.account)
    other_account_same_asset = repository.save_position_record(
        account_id=other_account.pk,
        asset_code="600000.SH",
        defaults=_position_defaults(),
    )
    assert same_account_other_asset.account_id == reservation_harness.account.pk
    assert same_account_other_asset.asset_code == "600001.SH"
    assert other_account_same_asset.account_id == other_account.pk
    assert other_account_same_asset.asset_code == "600000.SH"


def test_legacy_v3_trade_without_receipt_does_not_trigger_the_v4_position_gate(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A genuine V3 UoW Trade remains compatible with direct legacy calibration."""

    del persisted_receipt_schema
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    assert type(reservation_harness.account.pk) is int
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=reservation_harness.account.pk,
        key="legacy-v3-position-write-guard",
    )
    plan, bundle, _ = _current_v3_plan(
        repository=repository,
        intent=intent,
        as_of=AS_OF,
    )
    receipt = repository.execute_trade(
        plan=plan,
        execution_bundle=bundle,
        clock=_Clock(AS_OF),
    )
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    assert trade.settlement_plan_binding_version == 3
    assert not SimulatedOrderFillReceiptModel.objects.filter(trade=trade).exists()

    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=intent.asset_code,
    )
    entity = PositionMapper.to_entity(position)
    next_quantity = entity.quantity + 1.0
    updated_entity = replace(
        entity,
        quantity=next_quantity,
        available_quantity=entity.available_quantity + 1.0,
        total_cost=entity.avg_cost * next_quantity,
    )
    saved_id = DjangoPositionRepository().save(updated_entity)
    position.refresh_from_db()
    assert saved_id == position.pk
    assert position.quantity == Decimal(str(next_quantity))


@pytest.mark.parametrize("crossed_side", ("reservation", "trade"))
def test_corrupt_cross_scope_receipt_is_found_from_either_relation_side(
    crossed_side: str,
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A moved Receipt cannot hide behind the other account/asset foreign key."""

    del persisted_receipt_schema
    reservation, trade, receipt = _persist_terminal_v4_fill(reservation_harness)
    other_account = _create_other_account(reservation_harness.account)
    foreign_asset = "600001.SH"

    if crossed_side == "reservation":
        trade_query = SimulatedTradeModel._base_manager.filter(pk=trade.pk)
        models.QuerySet.update(
            trade_query,
            account_id=other_account.pk,
            asset_code=foreign_asset,
        )
        receipt.refresh_from_db()
        assert receipt.reservation_id == reservation.pk
        assert receipt.trade.account_id == other_account.pk
        assert receipt.trade.asset_code == foreign_asset
    else:
        reservation_query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
        models.QuerySet.update(
            reservation_query,
            account_id=other_account.pk,
            asset_code=foreign_asset,
        )
        trade_payload = dict(trade.settlement_plan_binding_payload)
        trade_payload["schema"] = "corrupt-v3-fixture"
        trade_query = SimulatedTradeModel._base_manager.filter(pk=trade.pk)
        models.QuerySet.update(
            trade_query,
            settlement_plan_binding_version=3,
            settlement_plan_binding_payload=trade_payload,
        )
        receipt.refresh_from_db()
        trade.refresh_from_db()
        reservation.refresh_from_db()
        assert receipt.reservation_id == reservation.pk
        assert receipt.reservation.account_id == other_account.pk
        assert receipt.reservation.asset_code == foreign_asset
        assert trade.account_id == reservation_harness.account.pk
        assert trade.asset_code == "600000.SH"
        assert trade.settlement_plan_binding_version == 3

    target_trade_markers = SimulatedTradeModel._base_manager.filter(
        account_id=reservation_harness.account.pk,
        asset_code="600000.SH",
        settlement_plan_binding_version=4,
    )
    assert not target_trade_markers.exists()
    expected_state = _position_scope_snapshot(
        reservation_harness.account.pk,
        "600000.SH",
    )
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    repository = DjangoPositionRepository()
    _assert_blocked_without_writes(
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code="600000.SH",
            defaults={"quantity": position.quantity + Decimal("1.000000")},
        ),
        account_id=reservation_harness.account.pk,
        asset_code="600000.SH",
        expected_state=expected_state,
    )


@pytest.mark.parametrize("marker_mode", ("scalar", "payload"))
def test_v4_marker_without_receipt_still_blocks_position_calibration(
    marker_mode: str,
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Either redundant V4 marker prevents rebuilding resources without a receipt."""

    del persisted_receipt_schema
    _, trade, receipt = _persist_terminal_v4_fill(reservation_harness)
    models.QuerySet.delete(SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipt.pk))
    if marker_mode == "payload":
        trade_query = SimulatedTradeModel._base_manager.filter(pk=trade.pk)
        models.QuerySet.update(trade_query, settlement_plan_binding_version=3)
        trade.refresh_from_db()
        assert trade.settlement_plan_binding_version == 3
        assert trade.settlement_plan_binding_payload["schema"] == "simulated-order-fill-binding.v4"
    else:
        assert trade.settlement_plan_binding_version == 4
    assert not SimulatedOrderFillReceiptModel.objects.filter(trade=trade).exists()
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    expected_state = _position_scope_snapshot(
        reservation_harness.account.pk,
        position.asset_code,
    )
    repository = DjangoPositionRepository()
    _assert_blocked_without_writes(
        lambda: repository.save_position_record(
            account_id=reservation_harness.account.pk,
            asset_code=position.asset_code,
            defaults={"total_cost": position.total_cost + Decimal("1.00")},
        ),
        account_id=reservation_harness.account.pk,
        asset_code=position.asset_code,
        expected_state=expected_state,
    )
