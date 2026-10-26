"""Legacy simulated-ledger writers must respect active order resource holds."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import models
from django.template.response import TemplateResponse
from django.test import RequestFactory

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.ports import AccountPerformanceUpdate
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    OrderStatus,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.position_repository import (
    DjangoPositionMutationRepository,
    DjangoPositionRepository,
    PositionMapper,
)
from apps.simulated_trading.interface.admin import (
    SimulatedAccountAdmin,
    SimulatedOrderReservationAdmin,
    SimulatedPositionAdmin,
)
from core.exceptions import BusinessLogicError
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _Clock,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _persist_two_active_fills as _persist_two_real_fills,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _set_consistent_account_mark as _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_receipt as _create_fill_receipt,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_reservation as _create_fill_reservation,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_trade as _create_fill_trade,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _promote_trade_to_v4 as _promote_fill_trade_to_v4,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _receipt_model as _fill_receipt_model,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position as _create_ledger_position,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

AS_OF = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 10, 19)
ASSET_CODE = "600000.SH"


@pytest.fixture
def guard_ledger() -> Iterator[tuple[SimulatedAccountModel, PositionModel]]:
    """Create a real account, one position, and the narrow repository schema."""

    user_model = get_user_model()
    with isolated_schema(
        (
            user_model,
            AccountProfileModel,
            SimulatedAccountModel,
            PositionModel,
            SimulatedTradeModel,
            SimulatedOrderReservationModel,
        )
    ):
        user = user_model.objects.create_user(
            username="order-reservation-legacy-writer",
            password="unused",
        )
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Reservation guard account",
            account_type="simulated",
            initial_capital=Decimal("10000.00"),
            current_cash=Decimal("10000.00"),
            cash_known=True,
            cash_reconciliation_status=AccountCashReconciliationStatus.SIMULATED_LEDGER.value,
            current_market_value=Decimal("1000.00"),
            total_value=Decimal("11000.00"),
            is_active=True,
        )
        position = PositionModel.objects.create(
            account=account,
            asset_code=ASSET_CODE,
            asset_name="Reservation guard security",
            asset_type="equity",
            quantity=Decimal("100.000000"),
            available_quantity=Decimal("60.000000"),
            available_quantity_known=True,
            avg_cost=Decimal("10.0000"),
            total_cost=Decimal("1000.00"),
            cost_basis_known=True,
            current_price=Decimal("10.0000"),
            market_value=Decimal("1000.00"),
            valuation_known=True,
            first_buy_date=TRADE_DATE,
            first_buy_date_known=True,
        )
        yield account, position


@pytest.fixture
def admin_full_app_registry(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel], transactional_db: None
) -> Iterator[None]:
    """Expose Admin URL dependencies and restore each narrow registry layer."""

    del guard_ledger, transactional_db
    expected_partial_names = tuple(
        sorted(
            (
                "apps.simulated_trading",
                "django.contrib.auth",
                "django.contrib.contenttypes",
            )
        )
    )
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
            if django_apps.is_installed("apps.strategy") and django_apps.is_installed(
                "apps.backtest"
            ):
                break
        assert django_apps.is_installed("apps.strategy")
        assert django_apps.is_installed("apps.backtest")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


def _create_active_reservation(
    account: SimulatedAccountModel,
    *,
    side: str = "sell",
    asset_code: str = ASSET_CODE,
) -> SimulatedOrderReservationModel:
    """Persist a constraint-valid active SELL share hold or BUY cash hold."""

    is_buy = side == "buy"
    return SimulatedOrderReservationModel.objects.create(
        account=account,
        owner_user_id=account.user_id,
        idempotency_key=f"legacy-guard-{side}",
        intent_payload_hash="a" * 64,
        reservation_request_hash="b" * 64,
        security_id=f"security:{asset_code}",
        asset_code=asset_code,
        asset_name="Reservation guard security",
        side=side,
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("10.000000"),
        limit_price=Decimal("10.0000"),
        notional=Decimal("100.00"),
        fee_estimate=Decimal("1.00"),
        fee_budget=Decimal("2.00") if is_buy else None,
        commission_estimate=Decimal("0.30"),
        transfer_fee_estimate=Decimal("0.01"),
        stamp_duty_estimate=Decimal("0.00" if is_buy else "0.10"),
        slippage_estimate=Decimal("0.69"),
        cash_reserved=Decimal("102.00") if is_buy else Decimal("0.00"),
        shares_reserved=Decimal("0.000000") if is_buy else Decimal("10.000000"),
        fee_policy_id="fee-policy-v2:test",
        fee_policy_version=1,
        fee_config_id=1,
        fee_policy_hash="c" * 64,
        plan_snapshot_version=1,
        plan_snapshot={"fixture": "sealed-fee-policy-and-order-plan"},
        plan_snapshot_hash="d" * 64,
        source_book_cash=Decimal("10000.00"),
        source_sellable_quantity=Decimal("60.000000") if not is_buy else None,
        source_snapshot_at=AS_OF,
        market_session=TRADE_DATE,
        settlement_lag_sessions=1,
        settlement_release_date=date(2026, 10, 20) if not is_buy else None,
        reserved_at=AS_OF,
    )


def _sell_trade(account_id: int) -> SimulatedTrade:
    """Return a valid ordinary simulated SELL for mutation-path guard tests."""

    return SimulatedTrade(
        trade_id=0,
        account_id=account_id,
        asset_code=ASSET_CODE,
        asset_name="Reservation guard security",
        asset_type="equity",
        action=TradeAction.SELL,
        quantity=10.0,
        price=10.0,
        amount=100.0,
        order_date=TRADE_DATE,
        execution_date=TRADE_DATE,
        execution_time=AS_OF,
        commission=0.30,
        slippage=0.69,
        total_cost=99.01,
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=0.0,
        realized_pnl_pct=0.0,
        status=OrderStatus.EXECUTED,
    )


def _buy_trade_payload(
    account: SimulatedAccountModel,
    *,
    asset_code: str = ASSET_CODE,
) -> dict[str, Any]:
    """Return a valid legacy BUY payload; the reservation guard runs first."""

    return {
        "account": account,
        "asset_code": asset_code,
        "asset_name": "Reservation guard security",
        "asset_type": "equity",
        "action": "buy",
        "quantity": Decimal("10.000000"),
        "price": Decimal("10.0000"),
        "amount": Decimal("100.00"),
        "commission": Decimal("0.30"),
        "transfer_fee": Decimal("0.01"),
        "stamp_duty": Decimal("0.00"),
        "slippage": Decimal("0.69"),
        "total_cost": Decimal("101.00"),
        "order_date": TRADE_DATE,
        "execution_date": TRADE_DATE,
        "execution_time": AS_OF,
        "status": "executed",
    }


def _mutation_position_defaults(
    *,
    asset_name: str,
    quantity: Decimal,
    available_quantity: Decimal,
) -> dict[str, Any]:
    """Build complete scoped defaults for a normal legacy BUY mutation."""

    total_cost = (quantity * Decimal("10.0000")).quantize(Decimal("0.01"))
    market_value = (quantity * Decimal("10.0000")).quantize(Decimal("0.01"))
    return {
        "asset_name": asset_name,
        "asset_type": "equity",
        "quantity": quantity,
        "available_quantity": available_quantity,
        "available_quantity_known": True,
        "avg_cost": Decimal("10.0000"),
        "total_cost": total_cost,
        "cost_basis_known": True,
        "current_price": Decimal("10.0000"),
        "market_value": market_value,
        "valuation_known": True,
        "unrealized_pnl": Decimal("0.00"),
        "unrealized_pnl_pct": 0.0,
        "first_buy_date": TRADE_DATE,
        "first_buy_date_known": True,
    }


def _mutation_scope_snapshot(account_id: int, asset_code: str) -> tuple[object, ...]:
    """Capture all scoped cash, position, order, trade, and receipt rows."""

    account = SimulatedAccountModel.objects.filter(pk=account_id).values().get()
    positions = (
        PositionModel.objects.filter(
            account_id=account_id,
            asset_code=asset_code,
        )
        .order_by("pk")
        .values()
    )
    reservations = (
        SimulatedOrderReservationModel.objects.filter(
            account_id=account_id,
            asset_code=asset_code,
        )
        .order_by("pk")
        .values()
    )
    trades = (
        SimulatedTradeModel.objects.filter(
            account_id=account_id,
            asset_code=asset_code,
        )
        .order_by("pk")
        .values()
    )
    receipts = (
        _fill_receipt_model()
        ._base_manager.filter(
            reservation__account_id=account_id,
            reservation__asset_code=asset_code,
        )
        .order_by("pk")
        .values()
    )
    return (
        tuple(account.items()),
        tuple(tuple(row.items()) for row in positions),
        tuple(tuple(row.items()) for row in reservations),
        tuple(tuple(row.items()) for row in trades),
        tuple(tuple(row.items()) for row in receipts),
    )


def _create_sibling_simulated_account(user_id: int) -> SimulatedAccountModel:
    """Create a second fully known simulated account for scope isolation tests."""

    return SimulatedAccountModel.objects.create(
        user_id=user_id,
        account_name="Unrelated mutation scope",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )


@pytest.mark.parametrize("reservation_side", ["buy", "sell"])
def test_account_repository_rejects_cash_replacement_and_preserves_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    reservation_side: str,
) -> None:
    """The unscoped settings writer cannot replace cash or disturb an active hold."""

    account_row, _ = guard_ledger
    reservation = _create_active_reservation(account_row, side=reservation_side)
    repository = DjangoSimulatedAccountRepository()
    account = repository.get_by_id(account_row.pk)
    assert account is not None

    cash_reserved_before = reservation.cash_reserved
    with pytest.raises(BusinessLogicError) as error:
        repository.save(replace(account, current_cash=account.current_cash - 25.0))

    assert error.value.code == "ACCOUNT_FINANCIAL_SNAPSHOT_CHANGED"
    account_row.refresh_from_db()
    reservation.refresh_from_db()
    assert account_row.current_cash == Decimal("10000.00")
    assert account_row.is_active is True
    assert account_row.auto_trading_enabled is True
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation.cash_reserved == cash_reserved_before


@pytest.mark.parametrize("reservation_side", ["buy", "sell"])
@pytest.mark.parametrize("stop_mode", ["deactivate", "disable_auto_trading", "cleanup"])
def test_account_repository_allows_safe_stops_with_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    reservation_side: str,
    stop_mode: str,
) -> None:
    """An explicit stop leaves the committed cash and order reservation intact."""

    account_row, _ = guard_ledger
    reservation = _create_active_reservation(account_row, side=reservation_side)
    repository = DjangoSimulatedAccountRepository()
    account_row.refresh_from_db()
    account = repository.get_by_id(account_row.pk)
    assert account is not None
    cash_before = account_row.current_cash
    cash_reserved_before = reservation.cash_reserved
    shares_reserved_before = reservation.shares_reserved

    if stop_mode == "deactivate":
        stopped = replace(account, is_active=False)
    elif stop_mode == "disable_auto_trading":
        stopped = replace(account, auto_trading_enabled=False)
    else:
        stopped = replace(account, is_active=False, auto_trading_enabled=False)

    repository.save(stopped)

    account_row.refresh_from_db()
    reservation.refresh_from_db()
    assert account_row.current_cash == cash_before
    assert account_row.is_active is (stop_mode == "disable_auto_trading")
    assert account_row.auto_trading_enabled is (stop_mode == "deactivate")
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation.cash_reserved == cash_reserved_before
    assert reservation.shares_reserved == shares_reserved_before


@pytest.mark.parametrize("enable_field", ["is_active", "auto_trading_enabled", "stale"])
def test_account_repository_blocks_reenable_with_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    enable_field: str,
) -> None:
    """Fresh or stale entities cannot restart account execution under an active hold."""

    account_row, _ = guard_ledger
    reservation = _create_active_reservation(account_row)
    repository = DjangoSimulatedAccountRepository()
    stale_account = repository.get_by_id(account_row.pk)
    assert stale_account is not None
    repository.save(replace(stale_account, is_active=False, auto_trading_enabled=False))

    fresh_account = repository.get_by_id(account_row.pk)
    assert fresh_account is not None
    if enable_field == "is_active":
        attempted_restart = replace(fresh_account, is_active=True)
    elif enable_field == "auto_trading_enabled":
        attempted_restart = replace(fresh_account, auto_trading_enabled=True)
    else:
        attempted_restart = stale_account

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        repository.save(attempted_restart)

    assert error.value.code == "ORDER_RESERVATION_ACTIVE"
    account_row.refresh_from_db()
    reservation.refresh_from_db()
    assert account_row.is_active is False
    assert account_row.auto_trading_enabled is False
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE


def test_django_admin_renders_financial_rows_and_refuses_writes(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    admin_full_app_registry: None,
) -> None:
    """Registered admin views allow review while refusing held-ledger mutations."""

    del admin_full_app_registry
    account_row, position = guard_ledger
    reservation = _create_active_reservation(account_row, side="buy")
    admin_user = get_user_model().objects.get(pk=account_row.user_id)
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.save(update_fields=("is_staff", "is_superuser"))

    account_row.refresh_from_db()
    position.refresh_from_db()
    reservation.refresh_from_db()
    account_cash_before = account_row.current_cash
    position_resources_before = (position.quantity, position.available_quantity)
    reservation_resources_before = (
        reservation.cash_reserved,
        reservation.shares_reserved,
        reservation.status,
    )
    request_factory = RequestFactory()
    admin_rows = (
        (SimulatedAccountModel, account_row, SimulatedAccountAdmin, {"current_cash": "1.00"}),
        (PositionModel, position, SimulatedPositionAdmin, {"quantity": "1.000000"}),
        (
            SimulatedOrderReservationModel,
            reservation,
            SimulatedOrderReservationAdmin,
            {"cash_reserved": "0.00"},
        ),
    )

    for model, row, admin_type, mutation in admin_rows:
        model_admin = admin.site._registry[model]
        assert isinstance(model_admin, admin_type)
        changelist_path = f"/admin/{model._meta.app_label}/{model._meta.model_name}/"
        change_path = f"{changelist_path}{row.pk}/change/"

        list_request = request_factory.get(changelist_path)
        list_request.user = admin_user
        list_request.current_app = admin.site.name
        list_request._dont_enforce_csrf_checks = True
        list_response = model_admin.changelist_view(list_request)
        assert isinstance(list_response, TemplateResponse)
        list_response.render()
        assert list_response.status_code == 200

        detail_request = request_factory.get(change_path)
        detail_request.user = admin_user
        detail_request.current_app = admin.site.name
        detail_request._dont_enforce_csrf_checks = True
        detail_response = model_admin.change_view(detail_request, str(row.pk))
        assert isinstance(detail_response, TemplateResponse)
        detail_response.render()
        assert detail_response.status_code == 200

        # CSRF is explicitly bypassed so refusal comes from ModelAdmin permission checks.
        mutation_request = request_factory.post(change_path, data=mutation)
        mutation_request.user = admin_user
        mutation_request.current_app = admin.site.name
        mutation_request._dont_enforce_csrf_checks = True
        try:
            mutation_response = model_admin.change_view(mutation_request, str(row.pk))
        except PermissionDenied:
            mutation_status = 403
        else:
            mutation_status = mutation_response.status_code
        assert mutation_status == 403

        delete_path = f"{changelist_path}{row.pk}/delete/"
        delete_request = request_factory.post(delete_path, data={"post": "yes"})
        delete_request.user = admin_user
        delete_request.current_app = admin.site.name
        delete_request._dont_enforce_csrf_checks = True
        try:
            delete_response = model_admin.delete_view(delete_request, str(row.pk))
        except PermissionDenied:
            delete_status = 403
        else:
            delete_status = delete_response.status_code
        assert delete_status == 403

    account_row.refresh_from_db()
    position.refresh_from_db()
    reservation.refresh_from_db()
    assert account_row.current_cash == account_cash_before
    assert (position.quantity, position.available_quantity) == position_resources_before
    assert (
        reservation.cash_reserved,
        reservation.shares_reserved,
        reservation.status,
    ) == reservation_resources_before
    assert SimulatedAccountModel.objects.filter(pk=account_row.pk).exists()
    assert PositionModel.objects.filter(pk=position.pk).exists()
    assert SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).exists()


@pytest.mark.parametrize("delete_method", ["delete", "delete_summary", "reset"])
def test_account_repository_blocks_delete_and_reset_before_cascade(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    delete_method: str,
) -> None:
    """Account lifecycle writes cannot remove positions beneath a live hold."""

    account_row, position = guard_ledger
    reservation = _create_active_reservation(account_row)
    repository = DjangoSimulatedAccountRepository()

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if delete_method == "delete":
            repository.delete(account_row.pk)
        elif delete_method == "delete_summary":
            repository.delete_account_with_summary(account_row.pk)
        else:
            repository.reset_account_with_summary(account_row.pk)

    assert error.value.code == "ORDER_RESERVATION_ACTIVE"
    assert SimulatedAccountModel.objects.filter(pk=account_row.pk).exists()
    assert PositionModel.objects.filter(pk=position.pk).exists()
    assert SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).exists()


@pytest.mark.parametrize(
    "repository_write",
    ["record_quantity", "domain_quantity", "delete_position"],
)
def test_position_repository_blocks_legacy_sellable_balance_changes(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    repository_write: str,
) -> None:
    """Scoped writes respect SELL holds; the unscoped entity writer is refused."""

    account_row, position = guard_ledger
    reservation = _create_active_reservation(account_row)
    repository = DjangoPositionRepository()

    if repository_write == "domain_quantity":
        current = PositionMapper.to_entity(position)
        with pytest.raises(BusinessLogicError) as legacy_error:
            repository.save(replace(current, quantity=current.quantity + 10.0))
        assert legacy_error.value.code == "SIMULATED_POSITION_ATOMIC_WRITE_REQUIRED"
        with pytest.raises(SimulatedTradeExecutionBlocked) as error:
            repository.save_position_record(
                account_id=account_row.pk,
                asset_code=ASSET_CODE,
                defaults={
                    "quantity": Decimal("110.000000"),
                    "available_quantity": Decimal("70.000000"),
                },
                expected_position=current,
            )
    else:
        with pytest.raises(SimulatedTradeExecutionBlocked) as error:
            if repository_write == "record_quantity":
                repository.save_position_record(
                    account_id=account_row.pk,
                    asset_code=ASSET_CODE,
                    defaults={
                        "quantity": Decimal("110.000000"),
                        "available_quantity": Decimal("70.000000"),
                    },
                    expected_position=PositionMapper.to_entity(position),
                )
            else:
                repository.delete(account_row.pk, ASSET_CODE)

    assert error.value.code == "ORDER_RESERVATION_ACTIVE"
    position.refresh_from_db()
    reservation.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("60.000000")
    assert SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).exists()
    assert SimulatedTradeModel.objects.filter(account=account_row).count() == 0


@pytest.mark.parametrize("identity_field", ["account_id", "asset_code"])
def test_position_record_rejects_identity_rewrite_even_with_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    identity_field: str,
) -> None:
    """The defaults payload cannot move a held row outside its locked identity scope."""

    account_row, position = guard_ledger
    reservation = _create_active_reservation(account_row)
    position_fields = (
        "account_id",
        "asset_code",
        "asset_type",
        "quantity",
        "available_quantity",
        "available_quantity_known",
        "avg_cost",
        "total_cost",
        "cost_basis_known",
    )
    original_position = tuple(getattr(position, field_name) for field_name in position_fields)
    if identity_field == "account_id":
        other_account = SimulatedAccountModel.objects.create(
            user_id=account_row.user_id,
            account_name="Other reservation guard account",
            account_type="simulated",
            initial_capital=Decimal("5000.00"),
            current_cash=Decimal("5000.00"),
            current_market_value=Decimal("0.00"),
            total_value=Decimal("5000.00"),
            is_active=True,
        )
        identity_value = other_account.pk
    else:
        other_account = None
        identity_value = "600001.SH"

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionRepository().save_position_record(
            account_id=account_row.pk,
            asset_code=ASSET_CODE,
            defaults={identity_field: identity_value, "quantity": position.quantity},
            expected_position=PositionMapper.to_entity(position),
        )

    assert error.value.code == "POSITION_IDENTITY_IMMUTABLE"
    position.refresh_from_db()
    reservation.refresh_from_db()
    refreshed_position = tuple(getattr(position, field_name) for field_name in position_fields)
    assert refreshed_position == original_position
    assert SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).exists()
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert SimulatedTradeModel.objects.filter(account=account_row).count() == 0
    if other_account is not None:
        assert not PositionModel.objects.filter(account=other_account).exists()
    else:
        assert not PositionModel.objects.filter(
            account=account_row,
            asset_code=identity_value,
        ).exists()


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_ordinary_trade_mutations_block_before_position_or_trade_writes(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
    side: str,
) -> None:
    """Legacy BUY and SELL entry points cannot spend resources reserved by an order."""

    account_row, position = guard_ledger
    reservation = _create_active_reservation(account_row, side=side)
    repository = DjangoPositionMutationRepository()

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if side == "buy":
            repository.create_or_merge_position_with_buy_trade(
                account_id=account_row.pk,
                asset_code=ASSET_CODE,
                position_defaults={
                    "asset_name": position.asset_name,
                    "asset_type": position.asset_type,
                    "quantity": Decimal("110.000000"),
                    "available_quantity": Decimal("60.000000"),
                    "available_quantity_known": True,
                    "avg_cost": Decimal("10.0000"),
                    "total_cost": Decimal("1100.00"),
                    "current_price": Decimal("10.0000"),
                    "market_value": Decimal("1100.00"),
                    "unrealized_pnl": Decimal("0.00"),
                    "unrealized_pnl_pct": 0.0,
                    "first_buy_date": TRADE_DATE,
                },
                trade_payload=_buy_trade_payload(account_row),
            )
        else:
            repository.close_position_with_sell_trade(
                account_id=account_row.pk,
                asset_code=ASSET_CODE,
                remaining_position_defaults={
                    "quantity": Decimal("90.000000"),
                    "available_quantity": Decimal("50.000000"),
                },
                expected_position=PositionMapper.to_entity(position),
                trade=_sell_trade(account_row.pk),
            )

    assert error.value.code == "ORDER_RESERVATION_ACTIVE"
    position.refresh_from_db()
    reservation.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("60.000000")
    assert SimulatedTradeModel.objects.filter(account=account_row).count() == 0
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE


@pytest.mark.parametrize("mutation", ("buy", "sell"))
def test_terminal_v4_fill_history_blocks_same_scope_legacy_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    mutation: str,
) -> None:
    """A real cancelled V4 chain still protects its account-and-asset resources."""

    del persisted_receipt_schema
    fill_state = _persist_two_real_fills(reservation_harness)
    reservation = fill_state.rows.reservation
    account = reservation_harness.account
    assert type(account.pk) is int
    assert (
        SimulatedTradeModel.objects.filter(
            account_id=account.pk,
            asset_code=ASSET_CODE,
            settlement_plan_binding_version=4,
        ).count()
        == 2
    )
    assert _fill_receipt_model()._base_manager.filter(reservation_id=reservation.pk).count() == 2

    cancelled = reservation_harness.repository.cancel_order(
        account_id=account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=reservation.idempotency_key,
        clock=_Clock(AS_OF + timedelta(minutes=4)),
    )
    reservation.refresh_from_db()
    assert cancelled.status.value == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert not SimulatedOrderReservationModel.objects.filter(
        account_id=account.pk,
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    ).exists()

    position = PositionModel.objects.get(account_id=account.pk, asset_code=ASSET_CODE)
    before = _mutation_scope_snapshot(account.pk, ASSET_CODE)
    repository = DjangoPositionMutationRepository()
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if mutation == "buy":
            repository.create_or_merge_position_with_buy_trade(
                account_id=account.pk,
                asset_code=ASSET_CODE,
                position_defaults=_mutation_position_defaults(
                    asset_name=position.asset_name,
                    quantity=position.quantity + Decimal("10.000000"),
                    available_quantity=position.available_quantity + Decimal("10.000000"),
                ),
                trade_payload=_buy_trade_payload(account),
                expected_position=PositionMapper.to_entity(position),
            )
        else:
            repository.close_position_with_sell_trade(
                account_id=account.pk,
                asset_code=ASSET_CODE,
                remaining_position_defaults={
                    "quantity": position.quantity - Decimal("10.000000"),
                    "available_quantity": position.available_quantity - Decimal("10.000000"),
                },
                expected_position=PositionMapper.to_entity(position),
                trade=_sell_trade(account.pk),
            )

    assert error.value.code == "ORDER_FILL_HISTORY_RETAINED"
    assert _mutation_scope_snapshot(account.pk, ASSET_CODE) == before


def _mark_orphan_reservation_fill_history(
    reservation: SimulatedOrderReservationModel,
    history_marker: str,
) -> None:
    """Persist one constraint-valid filled parent without Receipt or Trade rows."""

    if history_marker == "filled_quantity":
        changes: dict[str, object] = {
            "status": SimulatedOrderReservationModel.STATUS_CANCELLED,
            "cancelled_at": AS_OF + timedelta(minutes=1),
            "filled_quantity": Decimal("1.000000"),
            "cash_consumed": Decimal("10.00"),
            "cash_released": Decimal("92.00"),
        }
    elif history_marker == "cash_consumed":
        changes = {
            "status": SimulatedOrderReservationModel.STATUS_CANCELLED,
            "cancelled_at": AS_OF + timedelta(minutes=1),
            "cash_consumed": Decimal("1.00"),
            "cash_released": Decimal("101.00"),
        }
    elif history_marker == "shares_consumed":
        changes = {
            "status": SimulatedOrderReservationModel.STATUS_CANCELLED,
            "cancelled_at": AS_OF + timedelta(minutes=1),
            "filled_quantity": Decimal("1.000000"),
            "shares_consumed": Decimal("1.000000"),
            "shares_released": Decimal("9.000000"),
        }
    elif history_marker == "completed":
        changes = {
            "status": SimulatedOrderReservationModel.STATUS_COMPLETED,
            "filled_quantity": reservation.quantity,
            "cash_consumed": reservation.cash_reserved,
        }
    else:
        raise AssertionError(f"unsupported orphan-history marker: {history_marker}")

    reservation_query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
    updated = models.QuerySet.update(reservation_query, **changes)
    assert updated == 1
    reservation.refresh_from_db()


@pytest.mark.parametrize(
    ("history_marker", "reservation_side"),
    (
        ("filled_quantity", "buy"),
        ("cash_consumed", "buy"),
        ("shares_consumed", "sell"),
        ("completed", "buy"),
    ),
)
@pytest.mark.parametrize("mutation", ("buy", "sell"))
def test_orphan_reservation_fill_evidence_blocks_legacy_mutations_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    history_marker: str,
    reservation_side: str,
    mutation: str,
) -> None:
    """Any persisted fill counters or completion retain the scoped history guard."""

    del persisted_receipt_schema
    account = reservation_harness.account
    assert type(account.pk) is int
    position = _create_ledger_position(account)
    reservation = _create_active_reservation(account, side=reservation_side)
    _mark_orphan_reservation_fill_history(reservation, history_marker)
    assert not _fill_receipt_model()._base_manager.filter(reservation_id=reservation.pk).exists()
    assert not SimulatedTradeModel.objects.filter(
        account_id=account.pk,
        asset_code=ASSET_CODE,
    ).exists()
    before = _mutation_scope_snapshot(account.pk, ASSET_CODE)
    repository = DjangoPositionMutationRepository()

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if mutation == "buy":
            repository.create_or_merge_position_with_buy_trade(
                account_id=account.pk,
                asset_code=ASSET_CODE,
                position_defaults=_mutation_position_defaults(
                    asset_name=position.asset_name,
                    quantity=position.quantity + Decimal("10.000000"),
                    available_quantity=position.available_quantity + Decimal("10.000000"),
                ),
                trade_payload=_buy_trade_payload(account),
                expected_position=PositionMapper.to_entity(position),
            )
        else:
            repository.close_position_with_sell_trade(
                account_id=account.pk,
                asset_code=ASSET_CODE,
                remaining_position_defaults={
                    "quantity": position.quantity - Decimal("10.000000"),
                    "available_quantity": position.available_quantity - Decimal("10.000000"),
                },
                expected_position=PositionMapper.to_entity(position),
                trade=_sell_trade(account.pk),
            )

    assert error.value.code == "ORDER_FILL_HISTORY_RETAINED"
    assert _mutation_scope_snapshot(account.pk, ASSET_CODE) == before


@pytest.mark.parametrize("repository_write", ("save", "delete"))
def test_position_repository_blocks_orphan_completed_fill_history_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    repository_write: str,
) -> None:
    """Direct Position persistence and deletion share the orphan-history guard."""

    del persisted_receipt_schema
    account = reservation_harness.account
    assert type(account.pk) is int
    position = _create_ledger_position(account)
    reservation = _create_active_reservation(account, side="buy")
    _mark_orphan_reservation_fill_history(reservation, "completed")
    assert not _fill_receipt_model()._base_manager.filter(reservation_id=reservation.pk).exists()
    assert not SimulatedTradeModel.objects.filter(
        account_id=account.pk,
        asset_code=ASSET_CODE,
    ).exists()
    before = _mutation_scope_snapshot(account.pk, ASSET_CODE)
    repository = DjangoPositionRepository()

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if repository_write == "save":
            repository.save_position_record(
                account_id=account.pk,
                asset_code=ASSET_CODE,
                defaults=_mutation_position_defaults(
                    asset_name=position.asset_name,
                    quantity=position.quantity + Decimal("10.000000"),
                    available_quantity=position.available_quantity + Decimal("10.000000"),
                ),
                expected_position=PositionMapper.to_entity(position),
            )
        else:
            repository.delete(account.pk, ASSET_CODE)

    assert error.value.code == "ORDER_FILL_HISTORY_RETAINED"
    assert _mutation_scope_snapshot(account.pk, ASSET_CODE) == before


@pytest.mark.parametrize("orphan_scope", ("other_asset", "other_account"))
def test_orphan_reservation_history_does_not_block_other_position_scopes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    orphan_scope: str,
) -> None:
    """A completed orphan parent blocks only its own account-and-asset scope."""

    del persisted_receipt_schema
    account = reservation_harness.account
    assert type(account.pk) is int
    target_position = _create_ledger_position(account)
    if orphan_scope == "other_asset":
        orphan_account = account
        orphan_asset = "601398.SH"
    else:
        orphan_account = _create_sibling_simulated_account(account.user_id)
        orphan_asset = ASSET_CODE
    orphan = _create_active_reservation(
        orphan_account,
        side="buy",
        asset_code=orphan_asset,
    )
    _mark_orphan_reservation_fill_history(orphan, "completed")
    assert not _fill_receipt_model()._base_manager.filter(reservation_id=orphan.pk).exists()
    assert not SimulatedTradeModel.objects.filter(
        account_id=orphan_account.pk,
        asset_code=orphan_asset,
    ).exists()
    target_before = _mutation_scope_snapshot(account.pk, ASSET_CODE)
    orphan_before = _mutation_scope_snapshot(orphan_account.pk, orphan_asset)

    updated = DjangoPositionRepository().save_position_record(
        account_id=account.pk,
        asset_code=ASSET_CODE,
        defaults=_mutation_position_defaults(
            asset_name=target_position.asset_name,
            quantity=target_position.quantity + Decimal("10.000000"),
            available_quantity=target_position.available_quantity + Decimal("10.000000"),
        ),
        expected_position=PositionMapper.to_entity(target_position),
    )

    assert updated.pk == target_position.pk
    assert _mutation_scope_snapshot(account.pk, ASSET_CODE) != target_before
    assert _mutation_scope_snapshot(orphan_account.pk, orphan_asset) == orphan_before


def test_zero_fill_cancelled_reservation_allows_legacy_position_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A zero-fill cancellation has no retained fill marker and stays compatible."""

    del persisted_receipt_schema
    account = reservation_harness.account
    assert type(account.pk) is int
    position = _create_ledger_position(account)
    reservation = _create_active_reservation(account, side="buy")
    reservation_query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
    assert (
        models.QuerySet.update(
            reservation_query,
            status=SimulatedOrderReservationModel.STATUS_CANCELLED,
            cancelled_at=AS_OF + timedelta(minutes=1),
            cash_released=reservation.cash_reserved,
        )
        == 1
    )
    reservation.refresh_from_db()
    assert reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert reservation.filled_quantity == Decimal("0.000000")
    assert reservation.cash_consumed == Decimal("0.00")
    assert reservation.cash_released == reservation.cash_reserved
    assert not _fill_receipt_model()._base_manager.filter(reservation_id=reservation.pk).exists()
    assert not SimulatedTradeModel.objects.filter(
        account_id=account.pk,
        asset_code=ASSET_CODE,
    ).exists()

    updated = DjangoPositionRepository().save_position_record(
        account_id=account.pk,
        asset_code=ASSET_CODE,
        defaults=_mutation_position_defaults(
            asset_name=position.asset_name,
            quantity=position.quantity + Decimal("10.000000"),
            available_quantity=position.available_quantity + Decimal("10.000000"),
        ),
        expected_position=PositionMapper.to_entity(position),
    )

    assert updated.pk == position.pk
    position.refresh_from_db()
    assert position.quantity == Decimal("110.000000")
    assert position.available_quantity == Decimal("110.000000")
    reservation.refresh_from_db()
    assert reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED


@pytest.mark.parametrize("mutation", ("buy", "sell"))
def test_v3_without_receipt_keeps_legacy_mutation_compatibility(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    mutation: str,
) -> None:
    """A same-scope V3 trade without fill receipt remains ordinary legacy history."""

    del persisted_receipt_schema
    account = reservation_harness.account
    if mutation == "sell":
        opening_position = _create_ledger_position(account)
        _set_consistent_account_mark(account, market_value=Decimal("1000.00"))
    else:
        opening_position = None
    v3_trade = _create_fill_trade(reservation_harness, key=f"legacy-v3-{mutation}")
    assert v3_trade.settlement_plan_binding_version == 3
    assert not _fill_receipt_model()._base_manager.filter(trade_id=v3_trade.pk).exists()

    position = PositionModel.objects.filter(account_id=account.pk, asset_code=ASSET_CODE).first()
    if position is None:
        position = _create_ledger_position(account)
    if mutation == "sell":
        assert opening_position is not None
        position.refresh_from_db()
        assert position.quantity == Decimal("200.000000")
        assert position.available_quantity == Decimal("100.000000")
        assert v3_trade.settlement_status == "pending"
    repository = DjangoPositionMutationRepository()
    trade_count_before = SimulatedTradeModel.objects.filter(account_id=account.pk).count()
    if mutation == "buy":
        payload = _buy_trade_payload(account)
        payload.pop("account")
        payload["account_id"] = account.pk
        repository.create_or_merge_position_with_buy_trade(
            account_id=account.pk,
            asset_code=ASSET_CODE,
            position_defaults=_mutation_position_defaults(
                asset_name=position.asset_name,
                quantity=position.quantity + Decimal("10.000000"),
                available_quantity=position.available_quantity + Decimal("10.000000"),
            ),
            trade_payload=payload,
            expected_position=PositionMapper.to_entity(position),
        )
    else:
        repository.close_position_with_sell_trade(
            account_id=account.pk,
            asset_code=ASSET_CODE,
            remaining_position_defaults={
                "quantity": position.quantity - Decimal("10.000000"),
                "available_quantity": position.available_quantity - Decimal("10.000000"),
            },
            expected_position=PositionMapper.to_entity(position),
            trade=_sell_trade(account.pk),
        )

    assert SimulatedTradeModel.objects.filter(account_id=account.pk).count() == (
        trade_count_before + 1
    )
    assert not _fill_receipt_model()._base_manager.filter(trade_id=v3_trade.pk).exists()


@pytest.mark.parametrize("target_scope", ("other_asset", "other_account"))
def test_v4_history_does_not_block_an_unrelated_legacy_buy_scope(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    target_scope: str,
) -> None:
    """The retained-history guard remains limited to its exact parent scope."""

    del persisted_receipt_schema
    fill_state = _persist_two_real_fills(reservation_harness)
    source_account = reservation_harness.account
    reservation = fill_state.rows.reservation
    reservation_harness.repository.cancel_order(
        account_id=cast(int, source_account.pk),
        user_id=reservation_harness.user_id,
        idempotency_key=reservation.idempotency_key,
        clock=_Clock(AS_OF + timedelta(minutes=4)),
    )
    if target_scope == "other_account":
        target_account = _create_sibling_simulated_account(source_account.user_id)
        target_asset = ASSET_CODE
    else:
        target_account = source_account
        target_asset = "601398.SH"
    assert type(target_account.pk) is int
    assert not PositionModel.objects.filter(
        account_id=target_account.pk,
        asset_code=target_asset,
    ).exists()
    source_history_before = _mutation_scope_snapshot(cast(int, source_account.pk), ASSET_CODE)
    payload = _buy_trade_payload(target_account, asset_code=target_asset)
    payload.pop("account")
    payload["account_id"] = target_account.pk

    position = DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
        account_id=target_account.pk,
        asset_code=target_asset,
        position_defaults=_mutation_position_defaults(
            asset_name="Unrelated legacy target",
            quantity=Decimal("10.000000"),
            available_quantity=Decimal("10.000000"),
        ),
        trade_payload=payload,
    )

    assert position.account_id == target_account.pk
    assert position.asset_code == target_asset
    assert (
        SimulatedTradeModel.objects.filter(
            account_id=target_account.pk,
            asset_code=target_asset,
        ).count()
        == 1
    )
    assert _mutation_scope_snapshot(cast(int, source_account.pk), ASSET_CODE) == (
        source_history_before
    )


def test_buy_mutation_accepts_matching_account_model_payload(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A scoped model instance remains a supported legacy account payload form."""

    del persisted_receipt_schema
    account = reservation_harness.account
    position = _create_ledger_position(account)
    before = _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE)

    updated = DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
        account_id=cast(int, account.pk),
        asset_code=ASSET_CODE,
        position_defaults=_mutation_position_defaults(
            asset_name=position.asset_name,
            quantity=position.quantity + Decimal("10.000000"),
            available_quantity=position.available_quantity + Decimal("10.000000"),
        ),
        trade_payload=_buy_trade_payload(account),
        expected_position=PositionMapper.to_entity(position),
    )

    position.refresh_from_db()
    assert updated.pk == position.pk
    assert position.quantity == Decimal("110.000000")
    trade = SimulatedTradeModel.objects.get(
        account_id=account.pk,
        asset_code=ASSET_CODE,
    )
    assert trade.account_id == account.pk
    assert trade.asset_code == ASSET_CODE
    assert _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE) != before


@pytest.mark.parametrize(
    "payload_scope",
    (
        "boolean_id",
        "wrong_id",
        "foreign_account",
        "both_keys",
        "wrong_asset",
        "unknown_account",
    ),
)
def test_buy_mutation_rejects_malformed_trade_payload_scope_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    payload_scope: str,
) -> None:
    """BUY identity must be exact and represented by one supported account form."""

    del persisted_receipt_schema
    account = reservation_harness.account
    position = _create_ledger_position(account)
    payload = _buy_trade_payload(account)
    foreign_account: SimulatedAccountModel | None = None
    if payload_scope == "boolean_id":
        payload.pop("account")
        payload["account_id"] = True
    elif payload_scope == "wrong_id":
        payload.pop("account")
        payload["account_id"] = cast(int, account.pk) + 1
    elif payload_scope == "foreign_account":
        foreign_account = _create_sibling_simulated_account(account.user_id)
        payload["account"] = foreign_account
    elif payload_scope == "both_keys":
        payload["account_id"] = account.pk
    elif payload_scope == "wrong_asset":
        payload["asset_code"] = "601398.SH"
    else:
        payload["account"] = object()

    before = _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE)
    foreign_before = (
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE)
        if foreign_account is not None
        else None
    )
    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
            account_id=cast(int, account.pk),
            asset_code=ASSET_CODE,
            position_defaults=_mutation_position_defaults(
                asset_name=position.asset_name,
                quantity=position.quantity + Decimal("10.000000"),
                available_quantity=position.available_quantity + Decimal("10.000000"),
            ),
            trade_payload=payload,
            expected_position=PositionMapper.to_entity(position),
        )

    assert error.value.code == "POSITION_TRADE_SCOPE_MISMATCH"
    assert _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE) == before
    if foreign_account is not None:
        assert _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE) == foreign_before


@pytest.mark.parametrize("default_scope", ("account_id", "account", "asset_code", "id", "pk"))
def test_buy_mutation_rejects_position_default_scope_rewrites_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    default_scope: str,
) -> None:
    """Django defaults cannot redirect the locked account-and-asset identity."""

    del persisted_receipt_schema
    account = reservation_harness.account
    position = _create_ledger_position(account)
    foreign_account = _create_sibling_simulated_account(account.user_id)
    foreign_position = _create_ledger_position(foreign_account)
    defaults = _mutation_position_defaults(
        asset_name=position.asset_name,
        quantity=position.quantity + Decimal("10.000000"),
        available_quantity=position.available_quantity + Decimal("10.000000"),
    )
    scope_values: dict[str, Any] = {
        "account_id": cast(int, foreign_account.pk),
        "account": foreign_account,
        "asset_code": "601398.SH",
        "id": foreign_position.pk,
        "pk": foreign_position.pk,
    }
    defaults[default_scope] = scope_values[default_scope]
    before = (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    )

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
            account_id=cast(int, account.pk),
            asset_code=ASSET_CODE,
            position_defaults=defaults,
            trade_payload=_buy_trade_payload(account),
            expected_position=PositionMapper.to_entity(position),
        )

    assert error.value.code == "POSITION_IDENTITY_IMMUTABLE"
    assert (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    ) == before


@pytest.mark.parametrize("default_scope", ("account_id", "account", "asset_code", "id", "pk"))
def test_sell_mutation_rejects_position_default_scope_rewrites_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    default_scope: str,
) -> None:
    """SELL remaining defaults cannot redirect the locked position identity."""

    del persisted_receipt_schema
    account = reservation_harness.account
    position = _create_ledger_position(account)
    foreign_account = _create_sibling_simulated_account(account.user_id)
    foreign_position = _create_ledger_position(foreign_account)
    defaults = _mutation_position_defaults(
        asset_name=position.asset_name,
        quantity=position.quantity - Decimal("10.000000"),
        available_quantity=position.available_quantity - Decimal("10.000000"),
    )
    scope_values: dict[str, Any] = {
        "account_id": cast(int, foreign_account.pk),
        "account": foreign_account,
        "asset_code": "601398.SH",
        "id": foreign_position.pk,
        "pk": foreign_position.pk,
    }
    defaults[default_scope] = scope_values[default_scope]
    before = (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    )

    with pytest.raises(BusinessLogicError) as error:
        DjangoPositionMutationRepository().close_position_with_sell_trade(
            account_id=cast(int, account.pk),
            asset_code=ASSET_CODE,
            remaining_position_defaults=defaults,
            expected_position=PositionMapper.to_entity(position),
            trade=_sell_trade(cast(int, account.pk)),
        )

    assert error.value.code == "POSITION_IDENTITY_IMMUTABLE"
    assert (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    ) == before


@pytest.mark.parametrize("mutation", ("buy", "sell"))
def test_legacy_mutations_reject_unknown_position_defaults_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    mutation: str,
) -> None:
    """Both ordinary mutation methods reject unknown fields before any ledger write."""

    del persisted_receipt_schema
    account = reservation_harness.account
    position = _create_ledger_position(account)
    foreign_account = _create_sibling_simulated_account(account.user_id)
    _create_ledger_position(foreign_account)
    before = (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    )

    with pytest.raises(BusinessLogicError) as error:
        if mutation == "buy":
            defaults = _mutation_position_defaults(
                asset_name=position.asset_name,
                quantity=position.quantity + Decimal("10.000000"),
                available_quantity=position.available_quantity + Decimal("10.000000"),
            )
            defaults["unregistered_position_field"] = "unexpected"
            DjangoPositionMutationRepository().create_or_merge_position_with_buy_trade(
                account_id=cast(int, account.pk),
                asset_code=ASSET_CODE,
                position_defaults=defaults,
                trade_payload=_buy_trade_payload(account),
                expected_position=PositionMapper.to_entity(position),
            )
        else:
            defaults = _mutation_position_defaults(
                asset_name=position.asset_name,
                quantity=position.quantity - Decimal("10.000000"),
                available_quantity=position.available_quantity - Decimal("10.000000"),
            )
            defaults["unregistered_position_field"] = "unexpected"
            DjangoPositionMutationRepository().close_position_with_sell_trade(
                account_id=cast(int, account.pk),
                asset_code=ASSET_CODE,
                remaining_position_defaults=defaults,
                expected_position=PositionMapper.to_entity(position),
                trade=_sell_trade(cast(int, account.pk)),
            )

    assert error.value.code == "POSITION_WRITE_FIELDS_INVALID"
    assert (
        _mutation_scope_snapshot(cast(int, account.pk), ASSET_CODE),
        _mutation_scope_snapshot(cast(int, account.pk), "601398.SH"),
        _mutation_scope_snapshot(cast(int, foreign_account.pk), ASSET_CODE),
    ) == before


def test_price_refresh_remains_available_and_cannot_overwrite_held_cash(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
) -> None:
    """A valuation refresh changes marks only while the account cash hold remains intact."""

    account_row, position = guard_ledger
    _create_active_reservation(account_row, side="buy")
    repository = DjangoPositionRepository()

    updated = repository.save_position_record(
        account_id=account_row.pk,
        asset_code=ASSET_CODE,
        defaults={
            "current_price": Decimal("11.0000"),
            "market_value": Decimal("1100.00"),
            "unrealized_pnl": Decimal("100.00"),
            "unrealized_pnl_pct": 10.0,
            "valuation_known": True,
        },
        expected_position=PositionMapper.to_entity(position),
    )
    assert updated.current_price == Decimal("11.0000")

    account_row.refresh_from_db()
    position.refresh_from_db()
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("60.000000")
    assert position.current_price == Decimal("11.0000")
    assert account_row.current_cash == Decimal("10000.00")

    result = repository.update_position_prices({ASSET_CODE: Decimal("12.0000")})
    assert len(result) == 1
    account_row.refresh_from_db()
    position.refresh_from_db()
    assert position.current_price == Decimal("12.0000")
    assert position.market_value == Decimal("1200.00")
    assert account_row.current_cash == Decimal("10000.00")


def test_price_refresh_does_not_certify_unknown_valuation_during_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
) -> None:
    """A mark update may proceed, but an unknown valuation flag remains unknown."""

    account_row, position = guard_ledger
    position.valuation_known = False
    position.save(update_fields=["valuation_known"])
    _create_active_reservation(account_row, side="buy")

    updated = DjangoPositionRepository().save_position_record(
        account_id=account_row.pk,
        asset_code=ASSET_CODE,
        defaults={
            "current_price": Decimal("11.0000"),
            "market_value": Decimal("1100.00"),
            "unrealized_pnl": Decimal("100.00"),
            "unrealized_pnl_pct": 10.0,
            "valuation_known": True,
        },
        expected_position=PositionMapper.to_entity(position),
    )

    account_row.refresh_from_db()
    updated.refresh_from_db()
    assert updated.current_price == Decimal("11.0000")
    assert updated.valuation_known is False
    assert account_row.current_cash == Decimal("10000.00")


def test_performance_metrics_update_preserves_cash_under_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
) -> None:
    """The explicit performance writer updates metrics without replacing held cash."""

    account_row, _ = guard_ledger
    account_row.total_trades = 5
    account_row.save(update_fields=["total_trades"])
    reservation = _create_active_reservation(account_row, side="buy")
    repository = DjangoSimulatedAccountRepository()
    account = repository.get_by_id(account_row.pk)
    assert account is not None

    repository.update_performance_metrics(
        account_id=account_row.pk,
        expected_account=account,
        metrics=AccountPerformanceUpdate(
            total_return=1.5,
            annual_return=2.5,
            max_drawdown=3.5,
            sharpe_ratio=1.25,
            win_rate=40.0,
            winning_trades=2,
        ),
    )

    account_row.refresh_from_db()
    reservation.refresh_from_db()
    assert account_row.current_cash == Decimal("10000.00")
    assert account_row.total_trades == 5
    assert account_row.winning_trades == 2
    assert account_row.total_return == 1.5
    assert account_row.win_rate == 40.0
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation.cash_reserved == Decimal("102.00")


def test_legacy_position_quantity_write_remains_available_without_active_hold(
    guard_ledger: tuple[SimulatedAccountModel, PositionModel],
) -> None:
    """The new guard preserves ordinary legacy writes after all holds are terminal or absent."""

    account_row, position = guard_ledger

    updated = DjangoPositionRepository().save_position_record(
        account_id=account_row.pk,
        asset_code=ASSET_CODE,
        defaults={
            "quantity": Decimal("110.000000"),
            "available_quantity": Decimal("70.000000"),
        },
        expected_position=PositionMapper.to_entity(position),
    )

    position.refresh_from_db()
    assert updated.pk == position.pk
    assert position.quantity == Decimal("110.000000")
    assert position.available_quantity == Decimal("70.000000")


@pytest.mark.parametrize("history_kind", ["receipt", "v4_trade"])
def test_account_reset_preserves_fill_receipt_and_v4_trade_history(
    reservation_harness: _Harness,
    history_kind: str,
) -> None:
    """Reset rejects either persisted fill marker before changing the account ledger."""

    account = reservation_harness.account
    assert type(account.pk) is int
    trade = _create_fill_trade(
        reservation_harness,
        key=f"reset-fill-trade-{history_kind}",
    )
    position = PositionModel.objects.get(account_id=account.pk, asset_code=ASSET_CODE)
    reservation = _create_fill_reservation(
        reservation_harness,
        key=f"reset-fill-order-{history_kind}",
    )

    receipt_model = _fill_receipt_model()
    with isolated_schema((receipt_model,)):
        receipt_id: int | None = None
        event_id = f"reset-fill-event-{history_kind}"
        assert not receipt_model._base_manager.filter(reservation_id=reservation.pk).exists()
        cancelled = reservation_harness.repository.cancel_order(
            account_id=account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=reservation.idempotency_key,
            clock=_Clock(AS_OF),
        )
        assert cancelled.status.value == "cancelled"
        # This synthetic marker is for reset retention; cancellation sees an empty chain.
        if history_kind == "receipt":
            assert trade.settlement_plan_binding_version < 4
            # Keep this case independent of the V4 marker: even a receipt whose
            # sibling Trade binding is incomplete must be retained fail-closed.
            receipt = _create_fill_receipt(
                reservation,
                trade,
                namespace="reset-history-test",
                event_id=event_id,
            )
            assert type(receipt.pk) is int
            receipt_id = receipt.pk
        else:
            trade = _promote_fill_trade_to_v4(
                trade,
                reservation,
                namespace="reset-history-test",
                event_id=event_id,
            )

        account.refresh_from_db()
        position.refresh_from_db()
        trade.refresh_from_db()
        reservation.refresh_from_db()
        account_before = (
            account.current_cash,
            account.initial_capital,
            account.total_value,
            account.total_trades,
        )
        position_before = (
            position.quantity,
            position.available_quantity,
            position.total_cost,
            position.market_value,
        )
        reservation_before = (
            reservation.status,
            reservation.cash_released,
            reservation.shares_released,
        )
        repository = DjangoSimulatedAccountRepository()

        with pytest.raises(SimulatedTradeExecutionBlocked) as error:
            repository.reset_account_with_summary(account.pk)

        assert error.value.code == "ORDER_FILL_HISTORY_RETAINED"
        account.refresh_from_db()
        position.refresh_from_db()
        trade.refresh_from_db()
        reservation.refresh_from_db()
        assert (
            account.current_cash,
            account.initial_capital,
            account.total_value,
            account.total_trades,
        ) == account_before
        assert (
            position.quantity,
            position.available_quantity,
            position.total_cost,
            position.market_value,
        ) == position_before
        assert SimulatedTradeModel.objects.filter(pk=trade.pk).exists()
        assert SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).exists()
        assert (
            reservation.status,
            reservation.cash_released,
            reservation.shares_released,
        ) == reservation_before
        if receipt_id is not None:
            assert _fill_receipt_model()._base_manager.filter(pk=receipt_id).exists()
        else:
            assert not _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).exists()


def test_account_reset_still_removes_legacy_non_v4_trade_history(
    reservation_harness: _Harness,
) -> None:
    """The fill-history guard leaves existing non-V4 ledger reset behavior intact."""

    account = reservation_harness.account
    assert type(account.pk) is int
    trade = _create_fill_trade(reservation_harness, key="reset-legacy-trade")
    position = PositionModel.objects.get(account_id=account.pk, asset_code=ASSET_CODE)
    assert trade.settlement_plan_binding_version < 4

    with isolated_schema((_fill_receipt_model(),)):
        summary = DjangoSimulatedAccountRepository().reset_account_with_summary(account.pk)

    assert summary is not None
    assert SimulatedAccountModel.objects.filter(pk=account.pk).exists()
    assert not PositionModel.objects.filter(pk=position.pk).exists()
    assert not SimulatedTradeModel.objects.filter(pk=trade.pk).exists()


def test_account_reset_blocks_receipt_whose_trade_belongs_to_reset_account(
    reservation_harness: _Harness,
) -> None:
    """Either protected parent keeps a structurally persisted cross-account receipt."""

    account_a = reservation_harness.account
    reservation_a = _create_fill_reservation(
        reservation_harness,
        key="reset-cross-fk-reservation-a",
    )
    account_b = SimulatedAccountModel.objects.create(
        user_id=reservation_harness.user_id,
        account_name="Cross-FK reset target",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        cash_known=True,
        cash_reconciliation_status=(AccountCashReconciliationStatus.SIMULATED_LEDGER.value),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
        is_active=True,
    )
    trade_harness = replace(reservation_harness, account=account_b)
    trade_b = _create_fill_trade(trade_harness, key="reset-cross-fk-trade-b")
    assert trade_b.account_id == account_b.pk
    assert trade_b.settlement_plan_binding_version == 3
    position_b = PositionModel.objects.get(
        account_id=account_b.pk,
        asset_code=trade_b.asset_code,
    )

    with isolated_schema((_fill_receipt_model(),)):
        receipt = _create_fill_receipt(
            reservation_a,
            trade_b,
            namespace="reset-cross-fk-test",
            event_id="reservation-a-trade-b",
        )
        assert type(receipt.pk) is int
        assert reservation_a.account_id == account_a.pk
        assert receipt.reservation_id == reservation_a.pk
        assert receipt.trade_id == trade_b.pk
        assert receipt.source_event_payload["account_id"] == account_a.pk
        assert not SimulatedOrderReservationModel.objects.filter(account_id=account_b.pk).exists()

        account_a_before = SimulatedAccountModel.objects.filter(pk=account_a.pk).values().get()
        reservation_a_before = (
            SimulatedOrderReservationModel.objects.filter(pk=reservation_a.pk).values().get()
        )
        account_b_before = SimulatedAccountModel.objects.filter(pk=account_b.pk).values().get()
        position_b_before = PositionModel.objects.filter(pk=position_b.pk).values().get()
        trade_b_before = SimulatedTradeModel.objects.filter(pk=trade_b.pk).values().get()
        receipt_before = _fill_receipt_model()._base_manager.filter(pk=receipt.pk).values().get()

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            DjangoSimulatedAccountRepository().reset_account_with_summary(account_b.pk)

        assert blocked.value.code == "ORDER_FILL_HISTORY_RETAINED"
        assert (
            SimulatedAccountModel.objects.filter(pk=account_a.pk).values().get() == account_a_before
        )
        assert (
            SimulatedOrderReservationModel.objects.filter(pk=reservation_a.pk).values().get()
            == reservation_a_before
        )
        assert (
            SimulatedAccountModel.objects.filter(pk=account_b.pk).values().get() == account_b_before
        )
        assert PositionModel.objects.filter(pk=position_b.pk).values().get() == position_b_before
        assert SimulatedTradeModel.objects.filter(pk=trade_b.pk).values().get() == trade_b_before
        assert (
            _fill_receipt_model()._base_manager.filter(pk=receipt.pk).values().get()
            == receipt_before
        )
