from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="alpha_user",
        password="testpass123",
        email="alpha@example.com",
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="alpha_staff",
        password="testpass123",
        email="alpha-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_alpha_api_root_contract():
    client = APIClient()
    response = client.get("/api/alpha/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["module"] == "alpha"
    assert "/api/alpha/scores/" in payload["endpoints"]


@pytest.mark.django_db
def test_alpha_scores_reject_invalid_top_n(authenticated_client):
    response = authenticated_client.get("/api/alpha/scores/?top_n=0")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "invalid_request"
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_alpha_scores_non_staff_cannot_query_other_user(authenticated_client):
    response = authenticated_client.get("/api/alpha/scores/?user_id=42")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "forbidden"


@pytest.mark.django_db
def test_alpha_upload_scores_requires_admin_for_system_scope(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha/scores/upload/",
        {
            "universe_id": "csi300",
            "asof_date": "2026-04-02",
            "intended_trade_date": "2026-04-03",
            "scope": "system",
            "scores": [
                {"code": "600519.SH", "score": 0.9, "rank": 1},
            ],
        },
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"] == "只有管理员可以上传系统级评分（scope=system）"


@pytest.mark.django_db
def test_alpha_health_returns_503_when_all_providers_unavailable(authenticated_client):
    with patch(
        "apps.alpha.interface.views.AlphaService.get_provider_status",
        return_value={
            "qlib": {"status": "unavailable"},
            "cache": {"status": "unavailable"},
        },
    ):
        response = authenticated_client.get("/api/alpha/health/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["providers"] == {"available": 0, "total": 2}
