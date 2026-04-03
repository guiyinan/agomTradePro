import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="ai_provider_user",
        password="testpass123",
        email="ai-provider@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_ai_provider_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/ai/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/ai/providers/"
    assert payload["endpoints"]["logs"] == "/api/ai/logs/"


@pytest.mark.django_db
def test_ai_provider_logs_reject_invalid_provider_filter(authenticated_client):
    response = authenticated_client.get("/api/ai/logs/?provider=bad")

    assert response.status_code == 400
    assert response.json()["error"] == "provider 必须是整数"


@pytest.mark.django_db
def test_ai_provider_list_requires_authentication(api_client):
    response = api_client.get("/api/ai/providers/")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_ai_provider_test_connection_missing_provider_returns_404(authenticated_client):
    response = authenticated_client.post("/api/ai/providers/999999/test-connection/")

    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()
