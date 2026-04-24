from unittest.mock import patch

from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="factor_user",
        password="testpass123",
        email="factor@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_factor_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/factor/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["definitions"] == "/api/factor/definitions/"
    assert payload["endpoints"]["configs"] == "/api/factor/configs/"


@pytest.mark.django_db
def test_factor_create_portfolio_requires_config_name(authenticated_client):
    response = authenticated_client.post("/api/factor/create-portfolio/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "config_name is required"


@pytest.mark.django_db
def test_factor_create_portfolio_maps_value_error_to_400(authenticated_client):
    with patch(
        "apps.factor.interface.views.factor_interface_services.create_factor_portfolio",
        side_effect=ValueError("invalid trade date"),
    ):
        response = authenticated_client.post(
            "/api/factor/create-portfolio/",
            {"config_name": "balanced-factor", "trade_date": "bad-date"},
            format="json",
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid trade date"


@pytest.mark.django_db
def test_factor_explain_stock_returns_500_when_service_returns_none(authenticated_client):
    with patch(
        "apps.factor.interface.views.factor_interface_services.explain_stock_score",
        return_value=None,
    ):
        response = authenticated_client.post(
            "/api/factor/explain-stock/",
            {"stock_code": "600519.SH", "factor_weights": {"roe": 0.6, "pe_ttm": -0.4}},
            format="json",
        )

    assert response.status_code == 500
    assert response.json()["error"] == "Failed to explain stock score"
