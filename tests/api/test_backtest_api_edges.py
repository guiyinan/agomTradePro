import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="backtest_user",
        password="testpass123",
        email="backtest@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_backtest_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/backtest/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["backtests"] == "/api/backtest/backtests/"
    assert payload["endpoints"]["run"] == "/api/backtest/run/"


@pytest.mark.django_db
def test_backtest_list_rejects_non_integer_limit(authenticated_client):
    response = authenticated_client.get("/api/backtest/backtests/?limit=bad")

    assert response.status_code == 400
    assert response.json()["error"] == "limit must be an integer"


@pytest.mark.django_db
def test_backtest_run_rejects_invalid_date_order(authenticated_client):
    response = authenticated_client.post(
        "/api/backtest/run/",
        {
            "name": "invalid-range",
            "start_date": "2026-04-03",
            "end_date": "2026-04-03",
            "initial_capital": 100000,
            "rebalance_frequency": "monthly",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "start_date must be before end_date" in str(response.json()["errors"])


@pytest.mark.django_db
def test_backtest_rerun_returns_404_for_missing_backtest(authenticated_client):
    response = authenticated_client.post("/api/backtest/backtests/99999/rerun/", {}, format="json")

    assert response.status_code == 404
    assert response.json()["error"] == "Backtest not found"
