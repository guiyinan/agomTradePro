from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


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
def test_terminal_chat_returns_502_when_router_raises(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)

    with patch(
        "apps.terminal.interface.api_views.route_terminal_message",
        side_effect=RuntimeError("router exploded"),
    ):
        response = api_client.post(
            "/api/terminal/chat/",
            {
                "message": "系统怎么了",
                "provider_name": "test-provider",
                "model": "test-model",
            },
            format="json",
        )

    assert response.status_code == 502
    assert response.json()["error"] == "AI 调用异常: router exploded"


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
def test_terminal_session_requires_authentication(api_client):
    response = api_client.post("/api/terminal/session/")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_terminal_capabilities_exposes_lock_reason_when_mcp_disabled(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    with patch(
        "apps.terminal.interface.api_views.get_user_role",
        return_value="read_only",
    ), patch(
        "apps.terminal.interface.api_views._get_mcp_enabled",
        return_value=False,
    ), patch(
        "apps.terminal.interface.api_views.AnswerChainSettingsService.get_config",
        return_value={"enabled": False, "visibility": "masked", "is_admin": False},
    ):
        response = api_client.get("/api/terminal/commands/capabilities/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp_enabled"] is False
    assert payload["role"] == "read_only"
    assert payload["reason_if_locked"] == "MCP access disabled for your account"
    assert payload["available_modes"] == ["readonly"]
