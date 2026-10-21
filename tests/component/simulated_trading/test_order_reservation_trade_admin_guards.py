"""Django Admin must preserve append-only simulated fill history."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.test import RequestFactory

from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.interface import admin as simulated_trade_admin_module
from apps.simulated_trading.interface.admin import SimulatedTradeAdmin
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
    _current_v3_plan,
    _intent,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _persist_two_active_fills as _persist_two_active_fills,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_reservation as _create_fill_reservation,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _promote_trade_to_v4 as _promote_fill_trade_to_v4,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _receipt_model as _fill_receipt_model,
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


@pytest.fixture
def fill_admin_full_app_registry(
    persisted_receipt_schema: None,
    transactional_db: None,
) -> Iterator[None]:
    """Expose Admin URL dependencies after the ledger and receipt schema exist."""

    del persisted_receipt_schema, transactional_db
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
        with isolated_schema((LogEntry,)):
            yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


def _admin_owner(user_id: int) -> Any:
    """Return the account owner with real staff permissions for the Admin request."""

    user_model = get_user_model()
    user = user_model.objects.get(pk=user_id)
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=("is_staff", "is_superuser"))
    return user


def _attach_admin_messages(request: HttpRequest) -> None:
    """Provide the messages middleware contract for direct Admin view calls."""

    request._messages = CookieStorage(request)


def _create_admin_legacy_v3_trade(
    harness: _Harness,
    *,
    key: str,
) -> SimulatedTradeModel:
    """Create a real legacy V3 Trade through the explicit V3 settlement plan."""

    account_id = harness.account.pk
    assert type(account_id) is int and account_id > 0
    assert type(harness.user_id) is int and harness.user_id > 0
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    plan, bundle, _ = _current_v3_plan(
        repository=repository,
        intent=_intent(
            user_id=harness.user_id,
            account_id=account_id,
            key=key,
        ),
        as_of=AS_OF,
        source_exchange="SH",
    )
    result = repository.execute_trade(
        plan=plan,
        execution_bundle=bundle,
        clock=_Clock(AS_OF),
    )
    trade = SimulatedTradeModel._base_manager.get(pk=result.trade_id)
    assert trade.settlement_plan_binding_version == 3
    return trade


@pytest.mark.parametrize(
    "history_kind",
    ["receipt_backed_scalar_downgraded", "v4_marker_without_receipt"],
    ids=["receipt-backed-even-if-v3-scalar", "v4-marker-without-receipt"],
)
def test_trade_admin_keeps_fill_history_readable_but_rejects_change_and_delete(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    fill_admin_full_app_registry: None,
    history_kind: str,
) -> None:
    """Staff can inspect sealed or marker-V4 Trades but cannot rewrite or remove them."""

    del persisted_receipt_schema, fill_admin_full_app_registry
    if history_kind == "receipt_backed_scalar_downgraded":
        fills = _persist_two_active_fills(reservation_harness)
        trade = SimulatedTradeModel.objects.get(pk=fills.first_result.trade_id)
        assert trade.settlement_plan_binding_version == 4
        assert _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).exists()
        updated = SimulatedTradeModel._base_manager.filter(pk=trade.pk).update(
            settlement_plan_binding_version=3
        )
        assert updated == 1
        trade.refresh_from_db()
        assert trade.settlement_plan_binding_version == 3
    else:
        trade = _create_admin_legacy_v3_trade(
            reservation_harness,
            key="trade-admin-marker-only-v3-trade",
        )
        reservation = _create_fill_reservation(
            reservation_harness,
            key="trade-admin-marker-only-reservation",
        )
        trade = _promote_fill_trade_to_v4(
            trade,
            reservation,
            namespace="trade-admin-marker-only",
            event_id="trade-admin-marker-only-event",
        )
        assert trade.settlement_plan_binding_version == 4
        assert not _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).exists()

    admin_user = _admin_owner(reservation_harness.user_id)
    trade_admin = admin.site._registry[SimulatedTradeModel]
    assert isinstance(trade_admin, SimulatedTradeAdmin)
    list_path = "/admin/simulated_trading/simulatedtrademodel/"
    change_path = f"{list_path}{trade.pk}/change/"
    request_factory = RequestFactory()

    list_request = request_factory.get(list_path)
    list_request.user = admin_user
    list_request.current_app = admin.site.name
    list_request._dont_enforce_csrf_checks = True
    list_response = trade_admin.changelist_view(list_request)
    assert isinstance(list_response, TemplateResponse)
    list_response.render()
    assert list_response.status_code == 200

    get_request = request_factory.get(change_path)
    get_request.user = admin_user
    get_request.current_app = admin.site.name
    get_request._dont_enforce_csrf_checks = True
    detail_response = trade_admin.change_view(get_request, str(trade.pk))
    assert isinstance(detail_response, TemplateResponse)
    detail_response.render()
    assert detail_response.status_code == 200

    trade_before = SimulatedTradeModel._base_manager.filter(pk=trade.pk).values().get()
    receipt_rows = _fill_receipt_model()._base_manager.filter(trade_id=trade.pk)
    receipt_before = tuple(receipt_rows.order_by("pk").values())

    change_request = request_factory.post(
        change_path,
        data={"quantity": "999.000000", "action": "sell", "status": "cancelled"},
    )
    change_request.user = admin_user
    change_request.current_app = admin.site.name
    change_request._dont_enforce_csrf_checks = True
    with pytest.raises(PermissionDenied):
        trade_admin.change_view(change_request, str(trade.pk))

    delete_path = f"{list_path}{trade.pk}/delete/"
    delete_request = request_factory.post(delete_path, data={"post": "yes"})
    delete_request.user = admin_user
    delete_request.current_app = admin.site.name
    delete_request._dont_enforce_csrf_checks = True
    with pytest.raises(PermissionDenied):
        trade_admin.delete_view(delete_request, str(trade.pk))

    bulk_delete_request = request_factory.post(
        list_path,
        data={
            "action": "delete_selected",
            "index": "0",
            "_selected_action": str(trade.pk),
            "post": "yes",
        },
    )
    bulk_delete_request.user = admin_user
    bulk_delete_request.current_app = admin.site.name
    bulk_delete_request._dont_enforce_csrf_checks = True
    if history_kind == "v4_marker_without_receipt":
        with pytest.raises(PermissionDenied):
            trade_admin.changelist_view(bulk_delete_request)
    else:
        bulk_response = trade_admin.changelist_view(bulk_delete_request)
        assert isinstance(bulk_response, TemplateResponse)
        bulk_response.render()
        assert bulk_response.status_code == 200
        assert bulk_response.context_data is not None
        assert bulk_response.context_data["protected"]

    with pytest.raises(PermissionDenied):
        trade_admin.delete_queryset(
            delete_request,
            SimulatedTradeModel._base_manager.filter(pk=trade.pk),
        )

    assert SimulatedTradeModel._base_manager.filter(pk=trade.pk).values().get() == trade_before
    assert (
        tuple(_fill_receipt_model()._base_manager.filter(trade_id=trade.pk).order_by("pk").values())
        == receipt_before
    )


def test_trade_admin_keeps_legacy_v3_trade_edit_and_delete_available(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    fill_admin_full_app_registry: None,
) -> None:
    """Rows without V4 or receipt history retain the existing Admin workflow."""

    del persisted_receipt_schema, fill_admin_full_app_registry
    trade = _create_admin_legacy_v3_trade(
        reservation_harness,
        key="trade-admin-legacy-v3-editable",
    )
    assert trade.settlement_plan_binding_version == 3
    assert not _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).exists()

    admin_user = _admin_owner(reservation_harness.user_id)
    trade_admin = admin.site._registry[SimulatedTradeModel]
    assert isinstance(trade_admin, SimulatedTradeAdmin)
    request_factory = RequestFactory()
    list_path = "/admin/simulated_trading/simulatedtrademodel/"
    change_path = f"{list_path}{trade.pk}/change/"
    get_request = request_factory.get(change_path)
    get_request.user = admin_user
    get_request.current_app = admin.site.name
    get_request._dont_enforce_csrf_checks = True
    detail_response = trade_admin.change_view(get_request, str(trade.pk))
    assert isinstance(detail_response, TemplateResponse)
    detail_response.render()
    assert detail_response.status_code == 200

    change_request = request_factory.post(
        change_path,
        data={
            "account": str(trade.account_id),
            "asset_code": trade.asset_code,
            "asset_name": trade.asset_name,
            "asset_type": trade.asset_type,
            "action": trade.action,
            "quantity": str(trade.quantity),
            "price": str(trade.price),
            "reason": "legacy admin correction",
            "signal_id": "" if trade.signal_id is None else str(trade.signal_id),
            "status": trade.status,
            "_save": "Save",
        },
    )
    change_request.user = admin_user
    change_request.current_app = admin.site.name
    change_request._dont_enforce_csrf_checks = True
    _attach_admin_messages(change_request)
    change_response = trade_admin.change_view(change_request, str(trade.pk))
    assert change_response.status_code == 302
    trade.refresh_from_db()
    assert trade.reason == "legacy admin correction"

    delete_request = request_factory.post(
        f"{list_path}{trade.pk}/delete/",
        data={"post": "yes"},
    )
    delete_request.user = admin_user
    delete_request.current_app = admin.site.name
    delete_request._dont_enforce_csrf_checks = True
    _attach_admin_messages(delete_request)
    delete_response = trade_admin.delete_view(delete_request, str(trade.pk))
    assert delete_response.status_code == 302
    assert not SimulatedTradeModel._base_manager.filter(pk=trade.pk).exists()


def test_bulk_delete_uses_checked_ids_when_real_fills_arrive_after_guard(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    fill_admin_full_app_registry: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Admin delete cannot expand to sealed rows inserted after its guard query."""

    del persisted_receipt_schema, fill_admin_full_app_registry
    owner = get_user_model().objects.get(pk=reservation_harness.user_id)
    legacy_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="trade-admin-bulk-race-legacy",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    assert type(legacy_account.pk) is int
    legacy_repository = DjangoSimulatedTradeExecutionRepository(using="default")
    legacy_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=legacy_account.pk,
        key="trade-admin-bulk-race-legacy-trade",
    )
    legacy_plan, legacy_bundle, _ = _current_v3_plan(
        repository=legacy_repository,
        intent=legacy_intent,
        as_of=AS_OF,
        source_exchange="SH",
    )
    legacy_result = legacy_repository.execute_trade(
        plan=legacy_plan,
        execution_bundle=legacy_bundle,
        clock=_Clock(AS_OF),
    )
    legacy_trade = SimulatedTradeModel._base_manager.get(pk=legacy_result.trade_id)
    assert legacy_trade.settlement_plan_binding_version == 3
    assert not _fill_receipt_model()._base_manager.filter(trade_id=legacy_trade.pk).exists()

    admin_user = _admin_owner(reservation_harness.user_id)
    trade_admin = admin.site._registry[SimulatedTradeModel]
    assert isinstance(trade_admin, SimulatedTradeAdmin)
    request = RequestFactory().post("/admin/simulated_trading/simulatedtrademodel/")
    request.user = admin_user

    live_queryset = SimulatedTradeModel._base_manager.all().order_by("pk")
    assert tuple(live_queryset.values_list("pk", flat=True)) == (legacy_trade.pk,)
    original_guard = simulated_trade_admin_module.get_admin_read_only_trade_ids
    inserted_trade_ids: tuple[int, ...] = ()
    inserted_trade_snapshot: tuple[dict[str, object], ...] = ()
    inserted_receipt_snapshot: tuple[dict[str, object], ...] = ()
    inserted_account_snapshot: dict[str, object] = {}
    inserted_position_snapshot: tuple[dict[str, object], ...] = ()
    inserted_reservation_snapshot: tuple[dict[str, object], ...] = ()

    def _guard_then_write_real_fills(trade_ids: tuple[int, ...]) -> frozenset[int]:
        """Run the actual writer after the read-only guard returned its result."""

        nonlocal inserted_trade_ids
        nonlocal inserted_trade_snapshot
        nonlocal inserted_receipt_snapshot
        nonlocal inserted_account_snapshot
        nonlocal inserted_position_snapshot
        nonlocal inserted_reservation_snapshot

        protected_ids = original_guard(trade_ids)
        assert trade_ids == (legacy_trade.pk,)
        assert protected_ids == frozenset()
        fills = _persist_two_active_fills(reservation_harness)
        inserted_trade_ids = (
            fills.first_result.trade_id,
            fills.second_result.trade_id,
        )
        assert all(type(trade_id) is int and trade_id > 0 for trade_id in inserted_trade_ids)
        assert set(live_queryset.values_list("pk", flat=True)) == {
            legacy_trade.pk,
            *inserted_trade_ids,
        }
        inserted_trade_snapshot = tuple(
            SimulatedTradeModel._base_manager.filter(pk__in=inserted_trade_ids)
            .order_by("pk")
            .values()
        )
        inserted_receipt_snapshot = tuple(
            _fill_receipt_model()
            ._base_manager.filter(trade_id__in=inserted_trade_ids)
            .order_by("trade_id")
            .values()
        )
        inserted_account_snapshot = (
            SimulatedAccountModel._base_manager.filter(pk=reservation_harness.account.pk)
            .values()
            .get()
        )
        inserted_position_snapshot = tuple(
            PositionModel._base_manager.filter(account_id=reservation_harness.account.pk)
            .order_by("pk")
            .values()
        )
        inserted_reservation_snapshot = tuple(
            SimulatedOrderReservationModel._base_manager.filter(
                account_id=reservation_harness.account.pk
            )
            .order_by("pk")
            .values()
        )
        assert len(inserted_trade_snapshot) == 2
        assert len(inserted_receipt_snapshot) == 2
        assert all(row["settlement_plan_binding_version"] == 4 for row in inserted_trade_snapshot)
        receipt_trade_ids = tuple(
            int(row["trade_id"])
            for row in inserted_receipt_snapshot
            if type(row["trade_id"]) is int
        )
        assert set(receipt_trade_ids) == set(inserted_trade_ids)
        assert inserted_position_snapshot
        assert inserted_reservation_snapshot
        return protected_ids

    monkeypatch.setattr(
        simulated_trade_admin_module,
        "get_admin_read_only_trade_ids",
        _guard_then_write_real_fills,
    )
    trade_admin.delete_queryset(request, live_queryset)

    assert not SimulatedTradeModel._base_manager.filter(pk=legacy_trade.pk).exists()
    assert set(
        SimulatedTradeModel._base_manager.filter(pk__in=inserted_trade_ids).values_list(
            "pk", flat=True
        )
    ) == set(inserted_trade_ids)
    assert (
        tuple(
            SimulatedTradeModel._base_manager.filter(pk__in=inserted_trade_ids)
            .order_by("pk")
            .values()
        )
        == inserted_trade_snapshot
    )
    assert (
        tuple(
            _fill_receipt_model()
            ._base_manager.filter(trade_id__in=inserted_trade_ids)
            .order_by("trade_id")
            .values()
        )
        == inserted_receipt_snapshot
    )
    assert (
        SimulatedAccountModel._base_manager.filter(pk=reservation_harness.account.pk).values().get()
        == inserted_account_snapshot
    )
    assert (
        tuple(
            PositionModel._base_manager.filter(account_id=reservation_harness.account.pk)
            .order_by("pk")
            .values()
        )
        == inserted_position_snapshot
    )
    assert (
        tuple(
            SimulatedOrderReservationModel._base_manager.filter(
                account_id=reservation_harness.account.pk
            )
            .order_by("pk")
            .values()
        )
        == inserted_reservation_snapshot
    )


@pytest.mark.parametrize(
    "caller_kind",
    ["anonymous", "unsaved_user", "persisted_without_delete_permission"],
    ids=["anonymous", "unsaved-user", "persisted-user-without-delete-permission"],
)
def test_trade_admin_delete_queryset_rejects_unauthorized_callers_without_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    caller_kind: str,
) -> None:
    """Direct bulk-delete hooks reject unauthenticated or unauthorized callers."""

    del persisted_receipt_schema
    trade = _create_admin_legacy_v3_trade(
        reservation_harness,
        key=f"trade-admin-delete-unauthorized-{caller_kind}",
    )
    assert trade.settlement_plan_binding_version == 3
    assert not _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).exists()

    trade_admin = admin.site._registry[SimulatedTradeModel]
    assert isinstance(trade_admin, SimulatedTradeAdmin)
    user_model = get_user_model()
    if caller_kind == "anonymous":
        caller = AnonymousUser()
    elif caller_kind == "unsaved_user":
        caller = user_model(username="trade-admin-unsaved-user")
    else:
        caller = user_model.objects.get(pk=reservation_harness.user_id)
        assert caller.is_authenticated
        assert type(caller.pk) is int
        assert not caller.has_perm("simulated_trading.delete_simulatedtrademodel")

    request = RequestFactory().post("/admin/simulated_trading/simulatedtrademodel/")
    request.user = caller
    trade_queryset = SimulatedTradeModel._base_manager.filter(pk=trade.pk)

    trade_before = SimulatedTradeModel._base_manager.filter(pk=trade.pk).values().get()
    receipt_before = tuple(
        _fill_receipt_model()._base_manager.filter(trade_id=trade.pk).order_by("pk").values()
    )
    account_before = (
        SimulatedAccountModel._base_manager.filter(pk=reservation_harness.account.pk).values().get()
    )
    positions_before = tuple(
        PositionModel._base_manager.filter(account_id=reservation_harness.account.pk)
        .order_by("pk")
        .values()
    )
    reservations_before = tuple(
        SimulatedOrderReservationModel._base_manager.filter(
            account_id=reservation_harness.account.pk
        )
        .order_by("pk")
        .values()
    )

    with pytest.raises(PermissionDenied):
        trade_admin.delete_queryset(request, trade_queryset)

    assert SimulatedTradeModel._base_manager.filter(pk=trade.pk).values().get() == trade_before
    assert (
        tuple(_fill_receipt_model()._base_manager.filter(trade_id=trade.pk).order_by("pk").values())
        == receipt_before
    )
    assert (
        SimulatedAccountModel._base_manager.filter(pk=reservation_harness.account.pk).values().get()
        == account_before
    )
    assert (
        tuple(
            PositionModel._base_manager.filter(account_id=reservation_harness.account.pk)
            .order_by("pk")
            .values()
        )
        == positions_before
    )
    assert (
        tuple(
            SimulatedOrderReservationModel._base_manager.filter(
                account_id=reservation_harness.account.pk
            )
            .order_by("pk")
            .values()
        )
        == reservations_before
    )
