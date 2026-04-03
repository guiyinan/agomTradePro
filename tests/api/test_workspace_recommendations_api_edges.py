from types import SimpleNamespace
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
        username="workspace_recommendations_api_user",
        password="testpass123",
        email="workspace-recommendations@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_workspace_recommendations_reject_invalid_status_filter(authenticated_client, settings):
    settings.DECISION_WORKSPACE_V2_ENABLED = True

    response = authenticated_client.get(
        "/api/decision/workspace/recommendations/?account_id=default&status=bad-status"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "status must be one of" in payload["error"]


@pytest.mark.django_db
def test_workspace_recommendations_reject_invalid_user_action_filter(authenticated_client, settings):
    settings.DECISION_WORKSPACE_V2_ENABLED = True

    response = authenticated_client.get(
        "/api/decision/workspace/recommendations/?account_id=default&user_action=bad-action"
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "user_action must be one of" in payload["error"]


@pytest.mark.django_db
def test_workspace_recommendations_normalize_enum_filters_before_service_call(authenticated_client, settings):
    settings.DECISION_WORKSPACE_V2_ENABLED = True

    with patch(
        "apps.decision_rhythm.interface.recommendation_api_views.list_workspace_recommendations",
        return_value=([], 0),
    ) as list_mock:
        response = authenticated_client.get(
            "/api/decision/workspace/recommendations/"
            "?account_id=default&status=reviewing&user_action=watching"
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    kwargs = list_mock.call_args.kwargs
    assert kwargs["status"] == "REVIEWING"
    assert kwargs["user_action"] == "WATCHING"


@pytest.mark.django_db
def test_workspace_recommendation_action_returns_404_when_account_scope_misses(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/workspace/recommendations/action/",
        {
            "recommendation_id": "missing-rec",
            "account_id": "missing-account",
            "action": "watch",
        },
        format="json",
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Recommendation not found"


@pytest.mark.django_db
def test_workspace_refresh_rejects_non_list_security_codes(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/workspace/recommendations/refresh/",
        {"account_id": "default", "security_codes": "000001.SZ"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "security_codes must be a list of strings"


@pytest.mark.django_db
def test_workspace_refresh_rejects_non_string_security_code_items(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/workspace/recommendations/refresh/",
        {"account_id": "default", "security_codes": ["000001.SZ", 123]},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "security_codes must be a list of non-empty strings"


@pytest.mark.django_db
def test_workspace_refresh_returns_failed_status_payload(authenticated_client):
    failed_response = SimpleNamespace(
        status="FAILED",
        to_dict=lambda: {
            "task_id": "refresh_task_1",
            "status": "FAILED",
            "message": "刷新失败: upstream",
            "recommendations_count": 0,
            "conflicts_count": 0,
        },
    )

    with patch(
        "apps.decision_rhythm.interface.recommendation_api_views.refresh_workspace_recommendations",
        return_value=failed_response,
    ):
        response = authenticated_client.post(
            "/api/decision/workspace/recommendations/refresh/",
            {"account_id": "default", "security_codes": ["000001.SZ"]},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["data"]["status"] == "FAILED"
