from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


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
