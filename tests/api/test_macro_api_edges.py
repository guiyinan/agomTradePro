import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="macro_user",
        password="testpass123",
        email="macro@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_macro_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/macro/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["fetch"] == "/api/macro/fetch/"
    assert payload["endpoints"]["table"] == "/api/macro/table/"


@pytest.mark.django_db
def test_macro_fetch_rejects_invalid_json_body(authenticated_client):
    response = authenticated_client.post(
        "/api/macro/fetch/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "无效的请求数据" in payload["message"]


@pytest.mark.django_db
def test_macro_indicator_data_requires_code(authenticated_client):
    response = authenticated_client.get("/api/macro/indicator-data/")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "请指定指标代码"


@pytest.mark.django_db
def test_macro_indicator_data_accepts_indicator_alias(authenticated_client):
    response = authenticated_client.get("/api/macro/indicator-data/?indicator=CN_PMI")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True


@pytest.mark.django_db
def test_macro_legacy_datasource_routes_are_removed(authenticated_client):
    response = authenticated_client.get("/api/macro/datasources/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_macro_delete_rejects_invalid_json_body(authenticated_client):
    response = authenticated_client.post(
        "/api/macro/delete/",
        data=json.dumps({"indicator_code": "CN_PMI", "start_date": "bad-date"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "无效的请求数据" in payload["message"]
