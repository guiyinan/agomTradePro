from datetime import date
from decimal import Decimal

import pytest
from django.db import DatabaseError
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
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
def test_close_position_endpoint_commits_through_unified_ledger(
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

    assert response.status_code == 200
    assert response.json()["closed"] is True
    assert not PositionModel.objects.filter(account=owned_account).exists()
    assert owned_account.trades.filter(asset_code="000001.SZ", action="sell").exists()


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
def test_close_position_endpoint_rejects_oversell_without_ledger_mutation(
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
        {"asset_code": "000001.SZ", "close_shares": "101"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": "close_shares_exceeds_position",
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
    mocker.patch(
        "apps.simulated_trading.interface.sdk_contract_views.interface_services."
        "close_account_position",
        side_effect=ValueError("postgresql://admin:raw-secret@example.test/simulated"),
    )

    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.id}/positions/close/",
        {"asset_code": "000001.SZ"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "success": False,
        "error": "simulated_position_close_failed",
    }
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=ValueError" in caplog.text


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
