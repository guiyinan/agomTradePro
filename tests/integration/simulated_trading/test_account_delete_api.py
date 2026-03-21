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
    return get_user_model().objects.create_user(username="sim_delete_owner", password="x")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="sim_delete_other", password="x")


def _create_account(user, name: str) -> SimulatedAccountModel:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
    )


@pytest.mark.django_db
def test_delete_single_simulated_account(api_client: APIClient, owner):
    account = _create_account(owner, "to_delete")
    api_client.force_login(owner)

    response = api_client.delete(f"/api/simulated-trading/accounts/{account.id}/")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["account_id"] == account.id
    assert not SimulatedAccountModel.objects.filter(id=account.id).exists()


@pytest.mark.django_db
def test_delete_single_simulated_account_rejects_non_owner(api_client: APIClient, owner, other_user):
    account = _create_account(owner, "owner_only")
    api_client.force_login(other_user)

    response = api_client.delete(f"/api/simulated-trading/accounts/{account.id}/")

    assert response.status_code == 403
    assert SimulatedAccountModel.objects.filter(id=account.id).exists()


@pytest.mark.django_db
def test_batch_delete_simulated_accounts_returns_partial_failures(api_client: APIClient, owner, other_user):
    owned_1 = _create_account(owner, "owned_1")
    owned_2 = _create_account(owner, "owned_2")
    foreign = _create_account(other_user, "foreign")
    api_client.force_login(owner)

    response = api_client.post(
        "/api/simulated-trading/accounts/batch-delete/",
        {"account_ids": [owned_1.id, owned_2.id, foreign.id, 999999]},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted_count"] == 2
    assert set(data["deleted_account_ids"]) == {owned_1.id, owned_2.id}
    assert len(data["failed"]) == 2
    assert SimulatedAccountModel.objects.filter(id=foreign.id).exists()
