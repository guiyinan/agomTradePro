import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="strategy_user",
        password="testpass123",
        email="strategy@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_login(auth_user)
    return api_client


@pytest.mark.django_db
def test_strategy_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/strategy/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["strategies"] == "/api/strategy/strategies/"
    assert payload["endpoints"]["execution_evaluate"] == "/api/strategy/execution/evaluate/"


@pytest.mark.django_db
def test_strategy_assignments_by_portfolio_requires_portfolio_id(authenticated_client):
    response = authenticated_client.get("/api/strategy/assignments/by_portfolio/")

    assert response.status_code == 400
    assert response.json()["detail"] == "必须提供 portfolio_id 参数"


@pytest.mark.django_db
def test_strategy_execution_evaluate_rejects_invalid_json(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/execution/evaluate/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "无效 JSON"


@pytest.mark.django_db
def test_strategy_bind_requires_required_parameters(authenticated_client):
    response = authenticated_client.post("/api/strategy/bind-strategy/", data={}, content_type="application/json")

    assert response.status_code == 400
    assert response.json()["error"] == "缺少必要参数"


@pytest.mark.django_db
def test_strategy_unbind_rejects_invalid_json(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/unbind-strategy/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "无效 JSON"
