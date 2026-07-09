"""Terminal API contract tests for the agent-based terminal surface."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.terminal.infrastructure.models import TerminalAuditLogORM


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff_test",
        password="test123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="regular_test",
        password="test123",
        is_staff=False,
    )


@pytest.mark.django_db
class TestDeprecatedCommandEndpoints:
    """Legacy terminal command endpoints must return 410."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/terminal/commands/"),
            ("get", "/api/terminal/commands/available/"),
            ("get", "/api/terminal/commands/by_category/"),
            ("get", "/api/terminal/commands/capabilities/"),
            ("post", "/api/terminal/commands/execute_by_name/"),
            ("post", "/api/terminal/commands/confirm_execute/"),
        ],
    )
    def test_legacy_command_routes_return_410(self, api_client, staff_user, method, path):
        api_client.force_authenticate(user=staff_user)
        response = getattr(api_client, method)(path, {}, format="json")
        assert response.status_code == 410
        assert "retired" in response.json()["error"].lower()


@pytest.mark.django_db
class TestTerminalSessionEndpoint:
    """Tests for /api/terminal/session/."""

    def test_session_requires_authentication(self, api_client):
        response = api_client.post("/api/terminal/session/")
        assert response.status_code in {401, 403}

    def test_session_returns_uuid_like_id(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post("/api/terminal/session/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert len(payload["session_id"]) >= 32


@pytest.mark.django_db
class TestTerminalChatEndpoint:
    """Tests for /api/terminal/chat/."""

    def test_terminal_chat_returns_reply_session_and_metadata(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response_dto = Mock(
            reply="ok",
            session_id="sess-1",
            metadata={"provider": "test-provider", "model": "test-model"},
        )

        with patch(
            "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
            return_value=response_dto,
        ):
            response = api_client.post(
                "/api/terminal/chat/",
                {
                    "message": "hello",
                    "provider_name": "test-provider",
                    "model": "test-model",
                },
                format="json",
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "ok"
        assert payload["session_id"] == "sess-1"
        assert payload["metadata"]["provider"] == "test-provider"

    def test_terminal_chat_returns_approval_payload(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        response_dto = Mock(
            reply="approval needed",
            session_id="sess-approval",
            metadata={
                "status": "approval_required",
                "capability_key": "mcp_tool.sync_positions",
                "risk_level": "high",
            },
        )

        with patch(
            "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
            return_value=response_dto,
        ):
            response = api_client.post(
                "/api/terminal/chat/",
                {"message": "sync positions"},
                format="json",
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["approval_required"] is True
        assert payload["selected_capability_key"] == "mcp_tool.sync_positions"

    def test_terminal_chat_returns_502_when_agent_raises(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)

        with patch(
            "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
            side_effect=RuntimeError("agent exploded"),
        ):
            response = api_client.post(
                "/api/terminal/chat/",
                {"message": "系统怎么了"},
                format="json",
            )

        assert response.status_code == 502
        assert response.json()["error"] == "AI 调用异常: agent exploded"


@pytest.mark.django_db
class TestTerminalChatStreamEndpoint:
    """Tests for /api/terminal/chat/stream/."""

    def test_stream_endpoint_returns_sse_contract(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        events = iter(
            [
                Mock(event_type="message_delta", data={"delta": "hel"}),
                Mock(
                    event_type="final",
                    data={
                        "reply": "hello",
                        "session_id": "sess-stream",
                        "metadata": {"provider": "test-provider"},
                    },
                ),
            ]
        )

        with patch(
            "apps.terminal.interface.api_views.StreamTerminalAgentChatUseCase.execute",
            return_value=events,
        ):
            response = api_client.post(
                "/api/terminal/chat/stream/",
                {"message": "hello"},
                format="json",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/event-stream")
        assert "event: message_delta" in body
        assert "event: final" in body


@pytest.mark.django_db
class TestTerminalAuditEndpoint:
    """Tests for audit logging and /api/terminal/audit/."""

    def test_audit_endpoint_staff_only(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)
        response = api_client.get("/api/terminal/audit/")
        assert response.status_code == 403

    def test_audit_endpoint_accessible_by_staff(self, api_client, staff_user):
        TerminalAuditLogORM.objects.create(
            username=staff_user.username,
            session_id="audit-1",
            command_name="agent_chat",
            risk_level="read",
            mode="agent",
            result_status="success",
        )
        api_client.force_authenticate(user=staff_user)
        response = api_client.get("/api/terminal/audit/")
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["count"] >= 1
