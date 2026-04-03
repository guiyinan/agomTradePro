import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="alpha_trigger_user",
        password="testpass123",
        email="alpha-trigger@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_alpha_trigger_create_rejects_invalid_confidence(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/create/",
        {
            "trigger_type": "MOMENTUM_SIGNAL",
            "asset_code": "600519.SH",
            "asset_class": "a_share_growth",
            "direction": "LONG",
            "trigger_condition": {"signal": "cross_up"},
            "confidence": 1.5,
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "confidence" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_check_invalidation_requires_indicator_values(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/check-invalidation/",
        {"trigger_id": "trigger-001"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "current_indicator_values" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_evaluate_requires_current_data(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/evaluate/",
        {"trigger_id": "trigger-001"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "current_data" in payload["error"]


@pytest.mark.django_db
def test_alpha_trigger_update_status_rejects_invalid_status(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha-triggers/candidates/candidate-001/update-status/",
        {"status": "NOT_A_STATUS"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "status" in payload["error"]
