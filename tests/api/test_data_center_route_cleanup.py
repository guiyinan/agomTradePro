import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="market_data_api_user",
        password="testpass123",
        email="market-data@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_data_center_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/data-center/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/data-center/providers/"
    assert payload["endpoints"]["price_quotes"] == "/api/data-center/prices/quotes/"


@pytest.mark.django_db
def test_data_center_quotes_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/prices/quotes/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_data_center_capital_flows_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/capital-flows/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_legacy_market_data_api_routes_are_removed(authenticated_client):
    response = authenticated_client.get("/api/market-data/")

    assert response.status_code == 404
