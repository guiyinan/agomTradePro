"""Transport rejection contracts; real creation is tested on dedicated PostgreSQL.

Owned fields, both account types, alias replay, and existing-row name isolation
are covered in component/account/test_authenticated_creation_http_postgres.py.
These SQLite fixtures make no claim of successful canonical authentication.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["/api/account/accounts/", "/api/simulated-trading/accounts/"])
def test_creation_requires_key_before_reading_runtime_configuration(
    api_client: APIClient, owner, endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transport validation must not reach configuration or the legacy writer."""
    from core.integration import authenticated_canonical_account_creation as bridge

    def unexpected_configuration(environment: str):
        raise AssertionError("invalid creation key reached runtime configuration")

    monkeypatch.setattr(
        bridge, "get_active_account_creation_evidence_settings", unexpected_configuration
    )
    api_client.force_login(owner)
    before = SimulatedAccountModel.objects.count()
    response = api_client.post(
        endpoint,
        {"account_name": "Missing key", "account_type": "real", "initial_capital": "10000.00"},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert response["Content-Type"].startswith("application/json")
    assert SimulatedAccountModel.objects.count() == before


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["/api/account/accounts/", "/api/simulated-trading/accounts/"])
def test_missing_creation_configuration_never_falls_back_to_unsealed_row(
    api_client: APIClient, owner, endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid transport request remains unavailable without configured evidence."""
    from core.integration import authenticated_canonical_account_creation as bridge

    monkeypatch.setattr(bridge, "get_active_account_creation_evidence_settings", lambda _: None)
    api_client.force_login(owner)
    before = SimulatedAccountModel.objects.count()
    response = api_client.post(
        endpoint,
        {"account_name": "Missing config", "account_type": "real", "initial_capital": "10000.00"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="missing-configuration",
    )
    assert response.status_code == 503, response.content
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["success"] is False
    assert SimulatedAccountModel.objects.count() == before


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        username="sim_create_owner",
        password="x",
    )
