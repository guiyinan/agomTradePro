from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        username="sim_create_owner",
        password="x",
    )


@pytest.mark.django_db
def test_create_simulated_account_api_creates_owned_account(api_client: APIClient, owner):
    api_client.force_login(owner)

    response = api_client.post(
        "/api/simulated-trading/accounts/",
        {
            "account_name": "Growth Lab",
            "account_type": "simulated",
            "initial_capital": "250000.00",
            "max_position_pct": 25.0,
            "stop_loss_pct": 8.0,
            "commission_rate": 0.0002,
            "slippage_rate": 0.0008,
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["account"]["account_name"] == "Growth Lab"
    assert payload["account"]["account_type"] == "simulated"

    created = SimulatedAccountModel.objects.get(account_name="Growth Lab")
    assert created.user_id == owner.id
    assert created.account_type == "simulated"
    assert created.initial_capital == Decimal("250000.00")
    assert created.max_position_pct == 25.0
    assert created.commission_rate == 0.0002


@pytest.mark.django_db
def test_canonical_account_create_allows_same_name_for_different_owners(
    api_client: APIClient,
    owner,
):
    other = get_user_model().objects.create_user(
        username="sim_create_other",
        password="x",
    )
    SimulatedAccountModel.objects.create(
        user=other,
        account_name="Shared Name",
        account_type="real",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )
    api_client.force_login(owner)

    response = api_client.post(
        "/api/account/accounts/",
        {
            "account_name": "Shared Name",
            "account_type": "real",
            "initial_capital": "150000.00",
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["account"]["account_type"] == "real"
    assert payload["account"]["auto_trading_enabled"] is False
    assert SimulatedAccountModel.objects.filter(
        user=owner,
        account_name="Shared Name",
        account_type="real",
    ).exists()


@pytest.mark.django_db
def test_canonical_account_create_rejects_duplicate_name_for_same_owner(
    api_client: APIClient,
    owner,
):
    SimulatedAccountModel.objects.create(
        user=owner,
        account_name="Owner Duplicate",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )
    api_client.force_login(owner)

    response = api_client.post(
        "/api/account/accounts/",
        {
            "account_name": "Owner Duplicate",
            "account_type": "simulated",
            "initial_capital": "150000.00",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "账户名称已存在" in response.json()["error"]
    assert SimulatedAccountModel.objects.filter(
        user=owner,
        account_name="Owner Duplicate",
    ).count() == 1
