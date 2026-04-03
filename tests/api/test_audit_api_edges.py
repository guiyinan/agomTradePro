import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="audit_api_user",
        password="testpass123",
        email="audit@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_audit_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/audit/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["summary"] == "/api/audit/summary/"
    assert payload["endpoints"]["run_validation"] == "/api/audit/run-validation/"


@pytest.mark.django_db
def test_audit_run_validation_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/run-validation/",
        {"start_date": "2026/04/02", "end_date": "2026-04-03"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert "日期格式错误" in payload["error"]


@pytest.mark.django_db
def test_audit_validate_all_requires_date_range(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/validate-all-indicators/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "必须提供 start_date 和 end_date"


@pytest.mark.django_db
def test_audit_summary_rejects_invalid_backtest_id(authenticated_client):
    response = authenticated_client.get("/api/audit/summary/?backtest_id=bad-id")

    assert response.status_code == 400
    assert response.json()["error"] == "backtest_id 必须是整数"
