from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="policy_user",
        password="testpass123",
        email="policy@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_policy_status_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/policy/status/?as_of_date=2026/04/02")

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert "Invalid date format" in response.json()["error"]


@pytest.mark.django_db
def test_policy_workbench_items_rejects_invalid_tab(authenticated_client):
    response = authenticated_client.get("/api/policy/workbench/items/?tab=invalid")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "tab" in payload["errors"]


@pytest.mark.django_db
def test_policy_reject_event_requires_reason(authenticated_client):
    response = authenticated_client.post(
        "/api/policy/workbench/items/123/reject/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "reason" in payload["errors"]


@pytest.mark.django_db
def test_policy_workbench_fetch_rejects_invalid_source_id(authenticated_client):
    response = authenticated_client.post(
        "/api/policy/workbench/fetch/",
        {"source_id": "not-an-int"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "source_id" in payload["errors"]
