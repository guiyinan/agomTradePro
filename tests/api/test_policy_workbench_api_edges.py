import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    user = get_user_model().objects.create_user(
        username="policy_workbench_user",
        password="testpass123",
        email="policy-workbench@example.com",
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_policy_workbench_rollback_requires_reason(authenticated_client):
    response = authenticated_client.post(
        "/api/policy/workbench/items/123/rollback/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "reason" in payload["errors"]


@pytest.mark.django_db
def test_policy_workbench_override_rejects_invalid_level(authenticated_client):
    response = authenticated_client.post(
        "/api/policy/workbench/items/123/override/",
        {"reason": "manual override", "new_level": "PX"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "new_level" in payload["errors"]


@pytest.mark.django_db
def test_policy_sentiment_gate_config_rejects_empty_payload(authenticated_client):
    response = authenticated_client.put(
        "/api/policy/sentiment-gate-config/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "asset_class" in payload["errors"]
