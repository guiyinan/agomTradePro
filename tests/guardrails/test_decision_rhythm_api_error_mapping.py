import pytest
from django.contrib.auth.models import User
from django.test import Client


@pytest.fixture
def api_client(db):
    User.objects.create_user(
        username="decision_rhythm_guard",
        email="decision_rhythm_guard@example.com",
        password="StrongPass123!",
    )
    client = Client()
    client.login(username="decision_rhythm_guard", password="StrongPass123!")
    return client


@pytest.mark.django_db
def test_decision_rhythm_requests_invalid_days_returns_400(api_client):
    response = api_client.get("/api/decision-rhythm/requests/?days=invalid")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_statistics_invalid_days_returns_400(api_client):
    response = api_client.get("/api/decision-rhythm/requests/statistics/?days=invalid")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_requests_excessive_days_returns_400(api_client):
    response = api_client.get("/api/decision-rhythm/requests/?days=3651")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_statistics_excessive_days_returns_400(api_client):
    response = api_client.get("/api/decision-rhythm/requests/statistics/?days=3651")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_remaining_hours_rejects_long_asset_code(api_client):
    response = api_client.get(
        "/api/decision-rhythm/cooldowns/remaining-hours/",
        {"asset_code": "A" * 33},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_by_asset_rejects_long_asset_code(api_client):
    response = api_client.get(f"/api/decision-rhythm/cooldowns/by-asset/{'A' * 33}/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_trend_invalid_days_returns_400(api_client):
    response = api_client.get("/api/decision-rhythm/trend-data/?days=invalid")
    assert response.status_code == 400


@pytest.mark.django_db
def test_decision_rhythm_update_quota_invalid_numeric_returns_400(api_client):
    response = api_client.post(
        "/api/decision-rhythm/quota/update/",
        data={
            "period": "WEEKLY",
            "max_decisions": "invalid-number",
            "max_executions": 5,
        },
        content_type="application/json",
    )
    assert response.status_code == 400
