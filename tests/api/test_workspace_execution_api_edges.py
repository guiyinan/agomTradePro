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
        username="workspace_execution_api_user",
        password="testpass123",
        email="workspace-execution@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_workspace_execution_preview_requires_plan_or_recommendation_id(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/execute/preview/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "plan_id or recommendation_id is required"


@pytest.mark.django_db
def test_workspace_execution_plan_detail_returns_404_for_missing_plan(authenticated_client):
    response = authenticated_client.get("/api/decision/workspace/plans/missing-plan/")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Transition plan not found"


@pytest.mark.django_db
def test_workspace_execution_approve_requires_approval_request_id(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/execute/approve/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "approval_request_id is required"


@pytest.mark.django_db
def test_workspace_execution_reject_requires_approval_request_id(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/execute/reject/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "approval_request_id is required"


@pytest.mark.django_db
def test_workspace_execution_approve_returns_404_for_missing_request(authenticated_client):
    response = authenticated_client.post(
        "/api/decision/execute/approve/",
        {"approval_request_id": "missing-request"},
        format="json",
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Approval request not found"


@pytest.mark.django_db
def test_workspace_execution_detail_returns_request_payload(authenticated_client):
    fake_request = SimpleNamespace(
        to_dict=lambda: {"request_id": "req-1", "approval_status": "pending"}
    )

    with patch(
        "apps.decision_rhythm.interface.workspace_execution_api_views.get_approval_request",
        return_value=fake_request,
    ):
        response = authenticated_client.get("/api/decision/execute/req-1/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["request_id"] == "req-1"
