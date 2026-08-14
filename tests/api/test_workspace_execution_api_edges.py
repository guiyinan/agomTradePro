from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.decision_rhythm.domain.entities import ApprovalStatus
from apps.decision_rhythm.domain.exceptions import LegacyTransitionPlanWriteDisabledError


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
def test_workspace_plan_generation_rejects_non_list_recommendation_ids(
    authenticated_client,
):
    response = authenticated_client.post(
        "/api/decision/workspace/plans/generate/",
        {"recommendation_ids": "rec-1"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "recommendation_ids must be a list of strings"


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
def test_workspace_execution_approve_skips_event_when_status_update_returns_none(
    authenticated_client,
):
    approval_request = SimpleNamespace(
        approval_status=ApprovalStatus.PENDING,
        market_price_at_review=None,
    )

    with (
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.get_approval_request",
            return_value=approval_request,
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.ExecutionApprovalService.can_approve",
            return_value=(True, "ok"),
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.update_approval_request_status",
            return_value=None,
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.ExecutionApproveView._publish_decision_approved_event"
        ) as publish_event,
    ):
        response = authenticated_client.post(
            "/api/decision/execute/approve/",
            {"approval_request_id": "req-missing-after-update"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"request_id": "req-missing-after-update"}
    publish_event.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_workspace_plan_approval_legacy_blocker_returns_conflict(
    authenticated_client,
    action: str,
) -> None:
    approval_request = SimpleNamespace(
        approval_status=ApprovalStatus.PENDING,
        market_price_at_review=None,
    )

    with (
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.get_approval_request",
            return_value=approval_request,
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.ExecutionApprovalService.can_approve",
            return_value=(True, "ok"),
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.ApprovalStatusStateMachine.validate_transition",
            return_value=(True, "ok"),
        ),
        patch(
            "apps.decision_rhythm.interface.workspace_execution_api_views.update_approval_request_status",
            side_effect=LegacyTransitionPlanWriteDisabledError(
                "legacy transition-plan writes are disabled"
            ),
        ),
    ):
        response = authenticated_client.post(
            f"/api/decision/execute/{action}/",
            {"approval_request_id": "plan-request"},
            format="json",
        )

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "error": "legacy transition-plan writes are disabled",
    }


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
