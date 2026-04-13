import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="dashboard_api_user",
        password="testpass123",
        email="dashboard@example.com",
    )


@pytest.mark.django_db
def test_dashboard_api_root_contract(client):
    response = client.get("/api/dashboard/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["allocation"] == "/api/dashboard/allocation/"
    assert payload["endpoints"]["alpha_stocks"] == "/api/dashboard/alpha/stocks/"
    assert (
        payload["endpoints"]["v1_alpha_decision_chain"]
        == "/api/dashboard/v1/alpha-decision-chain/"
    )


@pytest.mark.django_db
def test_dashboard_allocation_rejects_invalid_account_id(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/allocation/?account_id=bad-id")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "account_id" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_stocks_rejects_invalid_top_n(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/alpha/stocks/?format=json&top_n=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_decision_chain_rejects_invalid_top_n(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/v1/alpha-decision-chain/?top_n=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_ic_trends_rejects_non_positive_days(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/alpha/ic-trends/?days=0")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "days" in payload["error"]
