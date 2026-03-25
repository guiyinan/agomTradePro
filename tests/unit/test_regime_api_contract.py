import pytest
from datetime import date
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth.models import User

@pytest.fixture
def api_client():
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
