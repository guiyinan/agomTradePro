import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture
def api_client(active_decision_runtime):
    del active_decision_runtime
    user = User.objects.create_user(username="testuser", password="password")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_regime_navigator_history_api(api_client):
    url = reverse("regime_api:regime-navigator-history")

    # 无参数调用，默认 12 个月
    response = api_client.get(url)
    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"

    data = response.json()
    assert data["success"] is True
    assert "data" in data
    assert "period" in data["data"]
    assert "regime_transitions" in data["data"]
    assert "pulse_history" in data["data"]
    assert "action_history" in data["data"]


@pytest.mark.django_db
def test_regime_navigator_history_api_with_months(api_client):
    url = reverse("regime_api:regime-navigator-history")

    # 带参数调用，3个月
    response = api_client.get(url, {"months": 3})
    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"
    data = response.json()
    assert data["success"] is True


@pytest.mark.django_db
def test_regime_navigator_empty_state_is_a_successful_read(api_client, monkeypatch):
    """A fresh install exposes an explicit empty state instead of a broken route."""

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, as_of_date: None,
    )

    response = api_client.get(reverse("regime_api:regime-navigator"))

    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"
    assert response.json() == {
        "success": True,
        "available": False,
        "data": None,
        "message": "Navigator data not available",
    }


@pytest.mark.django_db
def test_regime_action_empty_state_is_a_successful_read(api_client, monkeypatch):
    """Missing Regime/Pulse evidence remains a readable no-recommendation state."""

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.GetActionRecommendationUseCase.execute",
        lambda self, as_of_date, **kwargs: None,
    )

    response = api_client.get(reverse("regime_api:regime-action"))

    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"
    assert response.json() == {
        "success": True,
        "available": False,
        "data": None,
        "message": "Action recommendation not available",
    }
