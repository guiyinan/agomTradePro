from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="unified_api_user", password="pass123")


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def accounts(user):
    real_account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="真实账户A",
        account_type="real",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("80000.00"),
        current_market_value=Decimal("25000.00"),
        total_value=Decimal("105000.00"),
    )
    simulated_account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="模拟账户B",
        account_type="simulated",
        initial_capital=Decimal("50000.00"),
        current_cash=Decimal("45000.00"),
        current_market_value=Decimal("6000.00"),
        total_value=Decimal("51000.00"),
    )
    return real_account, simulated_account


def test_create_account_accepts_account_type_real(client):
    resp = client.post(
        "/api/simulated-trading/accounts/",
        data={
            "account_name": "真实账户C",
            "account_type": "real",
            "initial_capital": "200000.00",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()
    assert body["success"] is True
    assert body["account"]["account_type"] == "real"


def test_list_accounts_can_filter_by_account_type(client, accounts):
    resp = client.get("/api/simulated-trading/accounts/", {"account_type": "real"})
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["count"] >= 1
    assert all(account["account_type"] == "real" for account in body["accounts"])


def test_list_accounts_rejects_invalid_account_type(client, accounts):
    resp = client.get("/api/simulated-trading/accounts/", {"account_type": "paper"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "account_type" in resp.json()["error"]


def test_account_module_canonical_alias_list_uses_account_api(client, accounts):
    resp = client.get("/api/account/accounts/", {"account_type": "real"})
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["count"] >= 1
    assert all(account["account_type"] == "real" for account in body["accounts"])


def test_account_module_canonical_alias_detail_uses_account_id(client, accounts):
    real_account, _ = accounts
    resp = client.get(f"/api/account/accounts/{real_account.id}/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["success"] is True
    assert body["account"]["account_id"] == real_account.id
    assert body["account"]["account_type"] == "real"


def test_account_module_canonical_alias_positions_and_trades(client, accounts):
    real_account, _ = accounts

    positions_resp = client.get(f"/api/account/accounts/{real_account.id}/positions/")
    assert positions_resp.status_code == status.HTTP_200_OK
    assert positions_resp.json()["account_id"] == real_account.id

    trades_resp = client.get(f"/api/account/accounts/{real_account.id}/trades/")
    assert trades_resp.status_code == status.HTTP_200_OK
    assert trades_resp.json()["account_id"] == real_account.id
