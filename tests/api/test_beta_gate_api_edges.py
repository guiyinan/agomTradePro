import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="beta_gate_user",
        password="testpass123",
        email="beta-gate@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_beta_gate_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["configs"] == "/api/beta-gate/configs/"
    assert payload["endpoints"]["test"] == "/api/beta-gate/test/"


@pytest.mark.django_db
def test_beta_gate_decisions_reject_invalid_days(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/decisions/?days=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "days must be an integer"


@pytest.mark.django_db
def test_beta_gate_universe_rejects_invalid_limit(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/universe/?limit=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "limit must be an integer"


@pytest.mark.django_db
def test_beta_gate_rollback_rejects_invalid_version(authenticated_client):
    response = authenticated_client.post(
        "/api/beta-gate/config/rollback/not-real/",
        {"version": "bad"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Invalid version number"


@pytest.mark.django_db
def test_beta_gate_create_rejects_invalid_numeric_payload(authenticated_client):
    response = authenticated_client.post(
        "/api/beta-gate/configs/",
        {
            "risk_profile": "balanced",
            "min_confidence": "bad-float",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
