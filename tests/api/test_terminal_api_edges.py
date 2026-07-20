"""Edge-case tests for the refactored terminal agent endpoints."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="terminal_staff",
        password="test123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return get_user_model().objects.create_user(
        username="terminal_regular",
        password="test123",
        is_staff=False,
    )


@pytest.mark.django_db
def test_terminal_audit_limit_is_capped_at_200(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)
    repository = Mock()
    repository.get_recent.return_value = []

    with patch(
        "apps.terminal.interface.api_views.get_terminal_audit_repository",
        return_value=repository,
    ):
        response = api_client.get("/api/terminal/audit/?limit=9999")

    assert response.status_code == 200
    repository.get_recent.assert_called_once_with(
        limit=200,
        username=None,
        command_name=None,
        result_status=None,
    )


@pytest.mark.django_db
def test_terminal_stream_emits_error_event_when_use_case_fails(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)

    with patch(
        "apps.terminal.interface.api_views.StreamTerminalAgentChatUseCase.execute",
        side_effect=RuntimeError("stream exploded"),
    ):
        response = api_client.post(
            "/api/terminal/chat/stream/",
            {"message": "系统怎么了"},
            format="json",
        )
        body = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert "event: error" in body
    assert "stream exploded" in body


@pytest.mark.django_db
def test_terminal_chat_can_return_approval_required_payload(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)
    response_dto = Mock(
        reply="need approval",
        session_id="sess-approval",
        metadata={
            "status": "approval_required",
            "capability_key": "mcp_tool.rebalance_portfolio",
            "risk_level": "critical",
        },
    )

    with patch(
        "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
        return_value=response_dto,
    ):
        response = api_client.post(
            "/api/terminal/chat/",
            {"message": "rebalance my portfolio"},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["approval_required"] is True
    assert payload["metadata"]["risk_level"] == "critical"
