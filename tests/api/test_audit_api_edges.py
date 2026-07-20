import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="audit_api_user",
        password="testpass123",
        email="audit@example.com",
        is_staff=True,
    )


@pytest.mark.django_db
def test_audit_run_validation_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/run-validation/",
        {"start_date": "2026/04/02", "end_date": "2026-04-03"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert "start_date" in payload["details"]


@pytest.mark.django_db
def test_audit_validate_all_requires_date_range(authenticated_client):
    response = authenticated_client.post(
        "/api/audit/validate-all-indicators/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()["details"]) == {"start_date", "end_date"}


@pytest.mark.django_db
def test_audit_summary_rejects_invalid_backtest_id(authenticated_client):
    response = authenticated_client.get("/api/audit/summary/?backtest_id=bad-id")

    assert response.status_code == 400
    assert response.json()["error"] == "backtest_id 必须是整数"
