from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="sim_api_user",
        password="testpass123",
        email="sim@example.com",
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
def test_simulated_trading_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/simulated-trading/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["module"] == "simulated-trading"
    assert "/api/simulated-trading/accounts/" in payload["endpoints"]


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
