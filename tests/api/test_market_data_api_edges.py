import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="market_data_api_user",
        password="testpass123",
        email="market-data@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_market_data_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/market-data/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["quotes"] == "/api/market-data/quotes/"
    assert payload["endpoints"]["cross_validate"] == "/api/market-data/cross-validate/"


@pytest.mark.django_db
def test_market_data_quotes_require_codes(authenticated_client):
    response = authenticated_client.get("/api/market-data/quotes/")

    assert response.status_code == 400
    assert response.json()["error"] == "缺少 codes 参数"


@pytest.mark.django_db
def test_market_data_news_rejects_non_positive_limit(authenticated_client):
    response = authenticated_client.get("/api/market-data/news/?code=000001.SZ&limit=0")

    assert response.status_code == 400
    assert "limit" in response.json()["error"]


@pytest.mark.django_db
def test_market_data_cross_validate_rejects_blank_codes(authenticated_client):
    response = authenticated_client.get("/api/market-data/cross-validate/?codes=, ,")

    assert response.status_code == 400
    assert response.json()["error"] == "codes 参数为空"
