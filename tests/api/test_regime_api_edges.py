import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username="regime-edge", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_regime_navigator_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/regime/navigator/?as_of_date=2026/04/02")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "Invalid as_of_date" in payload["error"]


@pytest.mark.django_db
def test_regime_action_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/regime/action/?as_of_date=2026/04/02")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "Invalid as_of_date" in payload["error"]
