import logging
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, models
from rest_framework.test import APIClient

from apps.simulated_trading.application.manual_trade_execution import (
    SimulatedTradeExecutionReadbackUnknown,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.interface import sdk_contract_views as sdk_contract_view_module
from tests.api.test_manual_trade_current_reference import (
    _backdate_account_for_fixture_cutoff,
    _CallerState,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    _Harness,
    _persist_v4_fill,
)
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_read_compat import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_reservation as _create_fill_reservation,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position as _create_ledger_position,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_login(auth_user)
    return api_client


@pytest.fixture
def owned_account(auth_user):
    return SimulatedAccountModel.objects.create(
        user=auth_user,
        account_name="edge-account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )


@pytest.mark.django_db
def test_trade_list_rejects_invalid_start_date(authenticated_client, owned_account):
    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/trades/?start_date=2026/04/02"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "start_date" in payload["error"]

    invalid_limit = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/trades/?limit=bad"
    )
    assert invalid_limit.status_code == 400
    assert "limit" in invalid_limit.json()["error"]


@pytest.mark.django_db
def test_trade_list_keeps_total_count_and_zero_realized_pnl_with_pagination(
    authenticated_client,
    owned_account,
):
    common = {
        "account": owned_account,
        "asset_name": "CSI 300 ETF",
        "asset_type": "fund",
        "quantity": Decimal("10"),
        "price": Decimal("4.0000"),
        "amount": Decimal("40.00"),
        "commission": Decimal("0.00"),
        "slippage": Decimal("0.00"),
        "total_cost": Decimal("40.00"),
        "status": "executed",
    }
    SimulatedTradeModel.objects.create(
        **common,
        asset_code="510300.SH",
        action="sell",
        realized_pnl=Decimal("0.00"),
        realized_pnl_pct=0.0,
        cost_basis_known=True,
        fee_amounts_known=True,
        order_date=date(2026, 7, 2),
        execution_date=date(2026, 7, 2),
    )
    SimulatedTradeModel.objects.create(
        **common,
        asset_code="510500.SH",
        action="buy",
        realized_pnl=None,
        order_date=date(2026, 7, 1),
        execution_date=date(2026, 7, 1),
    )

    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/trades/?limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_trades"] == 2
    assert payload["total_buy_count"] == 1
    assert payload["total_sell_count"] == 1
    assert payload["total_realized_pnl_known"] is True
    assert Decimal(payload["total_realized_pnl"]) == Decimal("0")
    assert len(payload["trades"]) == 1
    assert payload["trades"][0]["realized_pnl_known"] is True
    assert payload["trades"][0]["realized_pnl_status"] == "known"
    assert Decimal(payload["trades"][0]["realized_pnl"]) == Decimal("0")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cost_basis_known", "fee_amounts_known"),
    [
        (False, True),
        (None, True),
        (True, False),
        (True, None),
    ],
    ids=["basis-partial", "basis-unknown", "fees-partial", "fees-unknown"],
)
def test_trade_list_hides_stored_zero_pnl_when_cost_or_fee_evidence_is_incomplete(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    cost_basis_known: bool | None,
    fee_amounts_known: bool | None,
) -> None:
    """Expose unknown evidence as null without rewriting stored numeric placeholders."""
    stored_trade = SimulatedTradeModel.objects.create(
        account=owned_account,
        asset_code="510300.SH",
        asset_name="CSI 300 ETF",
        asset_type="fund",
        action="sell",
        quantity=Decimal("10"),
        price=Decimal("4.0000"),
        amount=Decimal("40.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("40.00"),
        cost_basis_known=cost_basis_known,
        fee_amounts_known=fee_amounts_known,
        realized_pnl=Decimal("0.00"),
        realized_pnl_pct=0.0,
        status="executed",
        order_date=date(2026, 7, 2),
        execution_date=date(2026, 7, 2),
    )

    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/trades/?limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_trades"] == 1
    assert payload["total_buy_count"] == 0
    assert payload["total_sell_count"] == 1
    assert payload["total_realized_pnl"] is None
    assert payload["total_realized_pnl_known"] is False
    assert len(payload["trades"]) == 1

    trade_payload = payload["trades"][0]
    assert trade_payload["trade_id"] == stored_trade.pk
    assert trade_payload["cost_basis_known"] is cost_basis_known
    assert trade_payload["fee_amounts_known"] is fee_amounts_known
    assert trade_payload["realized_pnl"] is None
    assert trade_payload["realized_pnl_pct"] is None
    assert trade_payload["realized_pnl_known"] is False
    assert trade_payload["realized_pnl_pct_known"] is False
    assert trade_payload["realized_pnl_status"] == "unknown"

    stored_trade.refresh_from_db()
    assert stored_trade.realized_pnl == Decimal("0.00")
    assert stored_trade.realized_pnl_pct == 0.0
    assert stored_trade.commission == Decimal("0.00")
    assert stored_trade.total_cost == Decimal("40.00")


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_capital", ["not-a-number", "NaN"])
def test_account_page_rejects_invalid_initial_capital_without_server_error(
    authenticated_client,
    owned_account,
    invalid_capital,
):
    account_count_before = SimulatedAccountModel.objects.count()

    response = authenticated_client.post(
        "/simulated-trading/my-accounts/",
        {
            "account_name": "invalid-capital-account",
            "account_type": "simulated",
            "initial_capital": invalid_capital,
        },
    )

    assert response.status_code == 302
    assert response.url == "/simulated-trading/my-accounts/"
    assert SimulatedAccountModel.objects.count() == account_count_before


@pytest.mark.django_db
def test_equity_curve_rejects_reversed_date_range(authenticated_client, owned_account):
    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/equity-curve/?start_date=2026-04-03&end_date=2026-04-02"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "start_date 不能晚于 end_date"


@pytest.mark.django_db
def test_daily_inspection_list_rejects_invalid_limit(authenticated_client, owned_account):
    response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/inspections/?limit=bad"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "limit" in payload["error"]


@pytest.mark.django_db
def test_daily_inspection_list_returns_stable_empty_envelope(
    authenticated_client,
    owned_account,
):
    response = authenticated_client.get(
        f"/api/account/accounts/{owned_account.id}/inspections/?limit=10"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload == {
        "success": True,
        "count": 0,
        "reports": [],
    }


@pytest.mark.django_db
def test_inspection_notification_api_enforces_owner_scope_and_validates_emails(
    authenticated_client,
    owned_account,
    django_user_model,
):
    read_response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{owned_account.id}/inspection-notification/"
    )
    assert read_response.status_code == 200
    assert read_response.json()["config"]["notify_on"] == "warning_error"

    invalid_response = authenticated_client.patch(
        f"/api/simulated-trading/accounts/{owned_account.id}/inspection-notification/",
        {
            "is_enabled": True,
            "notify_on": "all",
            "include_owner_email": False,
            "recipient_emails": ["invalid-email"],
        },
        format="json",
    )
    assert invalid_response.status_code == 400
    assert "recipient_emails" in invalid_response.json()["details"]

    update_response = authenticated_client.patch(
        f"/api/simulated-trading/accounts/{owned_account.id}/inspection-notification/",
        {
            "is_enabled": False,
            "notify_on": "all",
            "include_owner_email": False,
            "recipient_emails": ["ops@example.com"],
        },
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.json()["config"] == {
        "is_enabled": False,
        "notify_on": "all",
        "include_owner_email": False,
        "recipient_emails": ["ops@example.com"],
        "updated_at": update_response.json()["config"]["updated_at"],
    }

    other_user = django_user_model.objects.create_user(username="notification-other")
    foreign_account = SimulatedAccountModel.objects.create(
        user=other_user,
        account_name="foreign-account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )
    forbidden_response = authenticated_client.get(
        f"/api/simulated-trading/accounts/{foreign_account.id}/inspection-notification/"
    )
    assert forbidden_response.status_code == 404


@pytest.mark.django_db
def test_close_position_endpoint_requires_exact_trade_intent(
    authenticated_client,
    owned_account,
):
    PositionModel.objects.create(
        account=owned_account,
        asset_code="000001.SZ",
        asset_name="Ping An Bank",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("11"),
        market_value=Decimal("1100"),
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=10.0,
        first_buy_date="2026-01-02",
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/positions/close/",
        {"asset_code": "000001.SZ"},
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "success": False,
        "error": "平仓请求无效。",
        "code": "SIMULATED_TRADE_INPUT_INVALID",
    }
    assert PositionModel.objects.filter(account=owned_account).count() == 1
    assert not owned_account.trades.filter(asset_code="000001.SZ", action="sell").exists()


@pytest.mark.django_db
def test_reset_account_endpoint_clears_ledger_and_resets_capital(
    authenticated_client,
    owned_account,
):
    PositionModel.objects.create(
        account=owned_account,
        asset_code="510300.SH",
        asset_name="CSI 300 ETF",
        asset_type="fund",
        quantity=Decimal("10"),
        available_quantity=Decimal("10"),
        avg_cost=Decimal("4"),
        total_cost=Decimal("40"),
        current_price=Decimal("4.2"),
        market_value=Decimal("42"),
        unrealized_pnl=Decimal("2"),
        unrealized_pnl_pct=5.0,
        first_buy_date="2026-01-02",
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/reset/",
        {"new_initial_capital": "200000.00"},
        format="json",
    )

    assert response.status_code == 200
    owned_account.refresh_from_db()
    assert owned_account.initial_capital == Decimal("200000.00")
    assert owned_account.current_cash == Decimal("200000.00")
    assert owned_account.total_value == Decimal("200000.00")
    assert owned_account.positions.count() == 0


@pytest.mark.django_db
def test_close_position_endpoint_rejects_legacy_aliases_without_ledger_mutation(
    authenticated_client,
    owned_account,
):
    position = PositionModel.objects.create(
        account=owned_account,
        asset_code="000001.SZ",
        asset_name="Ping An Bank",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("11"),
        market_value=Decimal("1100"),
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=10.0,
        first_buy_date="2026-01-02",
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/positions/close/",
        {
            "asset_code": "000001.SZ",
            "quantity": "101",
            "price": "11.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="legacy-close-alias-001",
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "success": False,
        "error": "平仓请求无效。",
        "code": "SIMULATED_TRADE_INPUT_INVALID",
    }
    position.refresh_from_db()
    assert position.quantity == Decimal("100")
    assert not owned_account.trades.exists()


@pytest.mark.django_db
def test_close_position_endpoint_redacts_unknown_validation_error(
    authenticated_client,
    owned_account,
    mocker,
    caplog,
):
    unknown = SimulatedTradeExecutionReadbackUnknown(
        "postgresql://admin:raw-secret@example.test/simulated"
    )
    use_case = mocker.Mock()
    use_case.execute.side_effect = unknown
    mocker.patch(
        "apps.simulated_trading.interface.sdk_contract_views."
        "build_current_reference_manual_trade_use_case",
        return_value=use_case,
        create=True,
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/positions/close/",
        {
            "asset_code": "000001.SZ",
            "close_shares": 10,
            "close_price": "11.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="unknown-close-001",
    )

    assert response.status_code == 503
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "success": False,
        "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
        "code": "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN",
        "effects_indeterminate": True,
    }
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=SimulatedTradeExecutionReadbackUnknown" in caplog.text


@pytest.mark.django_db
def test_close_position_endpoint_checks_account_owner_before_use_case(
    authenticated_client,
    mocker,
):
    owner = get_user_model().objects.create_user(username="close-foreign-owner")
    foreign_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="foreign-close-account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )
    use_case = mocker.Mock()
    builder = mocker.patch(
        "apps.simulated_trading.interface.sdk_contract_views."
        "build_current_reference_manual_trade_use_case",
        return_value=use_case,
        create=True,
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{foreign_account.pk}/positions/close/",
        {
            "asset_code": "000001.SZ",
            "close_shares": 10,
            "close_price": "11.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="foreign-close-key-001",
    )

    assert response.status_code == 403
    assert response["Content-Type"] == "application/json"
    assert builder.call_count == 0
    assert use_case.execute.call_count == 0
    assert not SimulatedTradeModel.objects.filter(account=foreign_account).exists()


@pytest.mark.django_db
def test_reset_account_endpoint_redacts_repository_error(
    authenticated_client,
    owned_account,
    mocker,
    caplog,
):
    mocker.patch(
        "apps.simulated_trading.interface.sdk_contract_views.interface_services."
        "reset_account_with_summary",
        side_effect=DatabaseError("postgresql://admin:reset-secret@example.test/simulated"),
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/reset/",
        {},
        format="json",
    )

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "simulated_account_reset_unavailable",
    }
    assert "reset-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=DatabaseError" in caplog.text


@pytest.mark.django_db
def test_reset_account_endpoint_returns_stable_missing_account_error(
    authenticated_client,
):
    response = authenticated_client.post(
        "/api/simulated-trading/accounts/999999/reset/",
        {},
        format="json",
    )

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "simulated_account_not_found",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("damage", "internal_reason"),
    [
        ("downgrade", "a receipt-backed Trade is not V4"),
        ("receipt_hash", "receipt hash differs from its canonical envelope"),
        ("parent_plan_hash", "stored reservation snapshot hash does not match payload"),
    ],
    ids=[
        "downgraded-receipt-backed-trade",
        "damaged-receipt-hash",
        "damaged-parent-plan-hash",
    ],
)
def test_trade_list_redacts_fill_history_validation_reason(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    caplog: pytest.LogCaptureFixture,
    damage: str,
    internal_reason: str,
) -> None:
    """The real owner endpoint returns a stable error without leaking reason text."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    if damage == "downgrade":
        trade_query = SimulatedTradeModel._default_manager.filter(pk=trade.pk)
        assert models.QuerySet.update(trade_query, settlement_plan_binding_version=3) == 1
    elif damage == "receipt_hash":
        receipt_query = SimulatedOrderFillReceiptModel._default_manager.filter(pk=receipt.pk)
        damaged_hash = "0" * 64
        assert receipt.receipt_hash != damaged_hash
        assert models.QuerySet.update(receipt_query, receipt_hash=damaged_hash) == 1
    else:
        assert damage == "parent_plan_hash"
        reservation = receipt.reservation
        reservation_query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
        damaged_hash = "f" * 64
        assert reservation.plan_snapshot_hash != damaged_hash
        assert (
            models.QuerySet.update(
                reservation_query,
                plan_snapshot_hash=damaged_hash,
            )
            == 1
        )

    logger_name = "apps.simulated_trading.infrastructure.order_reservation_fill_trade_read_guard"
    caplog.set_level(logging.ERROR, logger=logger_name)
    client = APIClient()
    owner = get_user_model()._default_manager.get(pk=reservation_harness.user_id)
    client.force_login(owner)
    response = client.get(
        f"/api/simulated-trading/accounts/{reservation_harness.account.pk}/trades/"
    )

    expected_error = "成交记录校验未通过，请先核对该账户的成交记录"
    assert response.status_code == 422
    assert response["Content-Type"] == "application/json"
    payload = response.json()
    assert payload == {
        "error": expected_error,
        "code": "ORDER_RESERVATION_FILL_HISTORY_INVALID",
    }
    assert internal_reason in caplog.text
    assert internal_reason not in payload["error"]


@pytest.mark.django_db(transaction=True)
def test_owner_close_api_blocks_completed_orphan_reservation_without_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner close route preserves a filled parent even when child markers are absent."""

    del persisted_receipt_schema
    account = reservation_harness.account
    assert type(account.pk) is int
    _backdate_account_for_fixture_cutoff(account)
    manual_state = _CallerState(source_available=True)
    monkeypatch.setattr(
        sdk_contract_view_module,
        "build_current_reference_manual_trade_use_case",
        manual_state.build_service,
        raising=False,
    )
    position = _create_ledger_position(account, asset_code="600000.SH")
    reservation = _create_fill_reservation(
        reservation_harness,
        key="owner-close-completed-orphan",
    )
    reservation_query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
    assert (
        models.QuerySet.update(
            reservation_query,
            status=SimulatedOrderReservationModel.STATUS_COMPLETED,
            filled_quantity=reservation.quantity,
            cash_consumed=reservation.cash_reserved,
        )
        == 1
    )
    reservation.refresh_from_db()
    assert reservation.status == SimulatedOrderReservationModel.STATUS_COMPLETED
    assert not SimulatedTradeModel._base_manager.filter(
        account_id=account.pk,
        asset_code=position.asset_code,
    ).exists()
    assert not SimulatedOrderFillReceiptModel._base_manager.filter(
        reservation_id=reservation.pk
    ).exists()

    def snapshot() -> tuple[object, ...]:
        account_values = SimulatedAccountModel._base_manager.filter(pk=account.pk).values().get()
        position_values = PositionModel._base_manager.filter(pk=position.pk).values().get()
        reservation_values = (
            SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk).values().get()
        )
        trades = (
            SimulatedTradeModel._base_manager.filter(
                account_id=account.pk,
                asset_code=position.asset_code,
            )
            .order_by("pk")
            .values()
        )
        receipts = (
            SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=reservation.pk)
            .order_by("pk")
            .values()
        )
        return (
            tuple(account_values.items()),
            tuple(position_values.items()),
            tuple(reservation_values.items()),
            tuple(tuple(row.items()) for row in trades),
            tuple(tuple(row.items()) for row in receipts),
        )

    before = snapshot()
    client = APIClient()
    owner = get_user_model()._default_manager.get(pk=reservation_harness.user_id)
    client.force_login(owner)
    response = client.post(
        f"/api/simulated-trading/accounts/{account.pk}/positions/close/",
        {
            "asset_code": position.asset_code,
            "close_shares": 100,
            "close_price": "10.00",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="owner-close-completed-orphan-001",
    )

    assert response.status_code == 422
    assert response["Content-Type"] == "application/json"
    payload = response.json()
    assert payload.get("code") == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert snapshot() == before
