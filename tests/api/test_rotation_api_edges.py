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
        username="rotation_user",
        password="testpass123",
        email="rotation@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_rotation_api_root_contract(api_client):
    response = api_client.get("/api/rotation/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["assets"] == "/api/rotation/assets/"
    assert payload["endpoints"]["actions"] == "/api/rotation/"


@pytest.mark.django_db
def test_rotation_compare_requires_asset_codes(authenticated_client):
    response = authenticated_client.post("/api/rotation/compare/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "asset_codes is required"


@pytest.mark.django_db
def test_rotation_generate_signal_returns_404_when_service_returns_none(authenticated_client):
    with patch(
        "apps.rotation.interface.views.RotationIntegrationService.generate_rotation_signal",
        return_value=None,
    ):
        response = authenticated_client.post(
            "/api/rotation/generate-signal/",
            {"config_name": "missing-config"},
            format="json",
        )

    assert response.status_code == 404
    assert "missing-config" in response.json()["error"]


@pytest.mark.django_db
def test_rotation_clear_cache_calls_service(authenticated_client):
    with patch("apps.rotation.interface.views.RotationIntegrationService.clear_price_cache") as mock_clear:
        response = authenticated_client.post("/api/rotation/clear-cache/", {}, format="json")

    assert response.status_code == 200
    assert response.json() == {"status": "cache cleared"}
    mock_clear.assert_called_once_with()
