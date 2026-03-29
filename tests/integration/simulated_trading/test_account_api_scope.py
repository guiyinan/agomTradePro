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
    return get_user_model().objects.create_user(username="sim_scope_owner", password="x")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="sim_scope_other", password="x")


def _create_account(user, name: str, *, is_active: bool = True) -> SimulatedAccountModel:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
        is_active=is_active,
    )


@pytest.mark.django_db
def test_account_list_api_returns_only_current_users_accounts(api_client: APIClient, owner, other_user):
    _create_account(owner, "owned_active", is_active=True)
    _create_account(owner, "owned_inactive", is_active=False)
    _create_account(other_user, "foreign_active", is_active=True)
    api_client.force_login(owner)

    response = api_client.get("/api/simulated-trading/accounts/?active_only=false")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    account_ids = {account["account_id"] for account in data["accounts"]}
    expected_ids = set(
        SimulatedAccountModel.objects.filter(user=owner).values_list("id", flat=True)
    )
    foreign_ids = set(
        SimulatedAccountModel.objects.filter(user=other_user).values_list("id", flat=True)
    )
    assert account_ids == expected_ids
    assert account_ids.isdisjoint(foreign_ids)


@pytest.mark.django_db
def test_account_list_api_active_only_filters_within_current_users_accounts(api_client: APIClient, owner, other_user):
    _create_account(owner, "owned_active", is_active=True)
    _create_account(owner, "owned_inactive", is_active=False)
    _create_account(other_user, "foreign_active", is_active=True)
    api_client.force_login(owner)

    response = api_client.get("/api/simulated-trading/accounts/")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    account_ids = {account["account_id"] for account in data["accounts"]}
    expected_ids = set(
        SimulatedAccountModel.objects.filter(user=owner, is_active=True).values_list("id", flat=True)
    )
    foreign_ids = set(
        SimulatedAccountModel.objects.filter(user=other_user).values_list("id", flat=True)
    )
    assert account_ids == expected_ids
    assert account_ids.isdisjoint(foreign_ids)


@pytest.mark.django_db
def test_account_detail_api_rejects_non_owner(api_client: APIClient, owner, other_user):
    foreign_account = _create_account(other_user, "foreign_active", is_active=True)
    api_client.force_login(owner)

    response = api_client.get(f"/api/simulated-trading/accounts/{foreign_account.id}/")

    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert "无权查看该账户" in data["error"]
