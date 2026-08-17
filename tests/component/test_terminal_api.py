"""Terminal API contract tests for the agent-based terminal surface."""

from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentBusyError,
    TerminalAgentTimeoutError,
)
from apps.agent_runtime.infrastructure.models import (
    AgentExecutionRecordModel,
    AgentProposalModel,
)
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor
from core.exceptions import MissingConfigError


@pytest.fixture
def api_client(active_decision_runtime):
    del active_decision_runtime
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
def test_terminal_page_bootstraps_provider_selector(client, regular_user):
    AIProviderConfig.objects.create(
        name="terminal-provider",
        provider_type="openai",
        is_active=True,
        priority=1,
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        default_model="gpt-4.1",
        extra_config={"supported_models": ["gpt-4.1", "gpt-4.1-mini"]},
    )
    client.force_login(regular_user)

    response = client.get("/terminal/")

    assert response.status_code == 200
    assert response.context["provider_selector_bootstrap"] == {
        "providers": [
            {
                "name": "terminal-provider",
                "provider_type": "openai",
                "default_model": "gpt-4.1",
                "models": ["gpt-4.1", "gpt-4.1-mini"],
                "is_active": True,
                "priority": 1,
                "display_label": "terminal-provider (gpt-4.1)",
            }
        ],
        "default_provider": "terminal-provider",
    }


@pytest.mark.django_db
def test_retired_terminal_config_page_redirects_staff_to_agent_chat(
    client,
    staff_user,
    regular_user,
):
    client.force_login(regular_user)
    forbidden = client.get("/terminal/config/")

    client.force_login(staff_user)
    redirected = client.get("/terminal/config/")

    assert forbidden.status_code == 403
    assert redirected.status_code == 302
    assert redirected["Location"] == ("/tui/?screen=ai-ops.terminal&action=terminal.agent_chat")


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
                "proposal_id": 41,
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
        assert payload["proposal_id"] == 41

    def test_terminal_chat_returns_redacted_502_when_agent_raises(self, api_client, staff_user):
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
        assert response.json() == {
            "error": "AI 服务调用失败，请检查服务商连通性、模型和额度后重试。",
            "code": "AI_PROVIDER_REQUEST_FAILED",
            "setup_required": False,
        }
        assert "agent exploded" not in response.content.decode("utf-8")

    @pytest.mark.parametrize(
        ("exception", "expected_status", "expected_code"),
        [
            (TerminalAgentBusyError(), 429, "AI_AGENT_BUSY"),
            (TerminalAgentTimeoutError(), 504, "AI_AGENT_TIMEOUT"),
        ],
    )
    def test_terminal_chat_returns_bounded_retryable_resilience_errors(
        self,
        api_client,
        staff_user,
        exception,
        expected_status,
        expected_code,
    ):
        api_client.force_authenticate(user=staff_user)

        with patch(
            "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
            side_effect=exception,
        ):
            response = api_client.post(
                "/api/terminal/chat/",
                {"message": "系统怎么了"},
                format="json",
            )

        assert response.status_code == expected_status
        assert response.json()["code"] == expected_code
        assert response.json()["retryable"] is True
        assert response["Retry-After"] == "5"
        assert response["Content-Type"].startswith("application/json")

    def test_terminal_chat_returns_503_when_provider_is_not_configured(
        self,
        api_client,
        staff_user,
    ):
        api_client.force_authenticate(user=staff_user)

        with patch(
            "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
            side_effect=MissingConfigError("No available AI providers"),
        ):
            response = api_client.post(
                "/api/terminal/chat/",
                {"message": "请说明当前配置状态"},
                format="json",
            )

        assert response.status_code == 503
        assert response.json() == {
            "error": "AI 服务尚未配置，请先配置可用服务商。",
            "code": "AI_PROVIDER_UNAVAILABLE",
            "setup_required": True,
        }


@pytest.mark.django_db
def test_tui_internal_agent_action_recovers_after_bounded_busy_response(staff_user):
    executor = TuiInternalActionExecutor()
    recovered_response = Mock(
        reply="recovered",
        session_id="session-recovered",
        metadata={"provider": "test-provider", "model": "test-model"},
    )

    with patch(
        "apps.terminal.interface.api_views.RunTerminalAgentChatUseCase.execute",
        side_effect=[TerminalAgentBusyError(), recovered_response],
    ):
        busy = executor.execute(
            method="POST",
            endpoint="/api/terminal/chat/",
            params={},
            body={"message": "first"},
            user=staff_user,
        )
        recovered = executor.execute(
            method="POST",
            endpoint="/api/terminal/chat/",
            params={},
            body={"message": "second"},
            user=staff_user,
        )

    assert busy["status_code"] == 429
    assert busy["payload"]["code"] == "AI_AGENT_BUSY"
    assert recovered["status_code"] == 200
    assert recovered["payload"]["reply"] == "recovered"


@pytest.mark.django_db
class TestTerminalApprovalDecisionEndpoint:
    """Tests for the Terminal MCP approval decision endpoint."""

    def test_approval_decision_requires_operator_permission(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)

        response = api_client.post(
            "/api/terminal/approvals/41/decision/",
            {"decision": "approve"},
            format="json",
        )

        assert response.status_code == 403

    def test_staff_can_approve_and_execute_persisted_mcp_proposal(self, api_client, staff_user):
        api_client.force_authenticate(user=staff_user)
        approved = Mock(request_id="apr-1", proposal=Mock(id=41))
        executed = Mock(
            request_id="apr-1",
            proposal=Mock(id=41),
            execution_record_id=88,
            guardrail_decision={"decision": "allowed"},
        )
        persisted = Mock(proposal=Mock(proposal_type="terminal_mcp_capability"))

        with (
            patch(
                "apps.terminal.interface.api_views.GetProposalUseCase.execute",
                return_value=persisted,
            ),
            patch(
                "apps.terminal.interface.api_views.ApproveProposalUseCase.execute",
                return_value=approved,
            ) as approve,
            patch(
                "apps.terminal.interface.api_views.ExecuteProposalUseCase.execute",
                return_value=executed,
            ) as execute,
        ):
            response = api_client.post(
                "/api/terminal/approvals/41/decision/",
                {"decision": "approve", "reason": "confirmed in Terminal"},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["status"] == "executed"
        assert response.json()["execution_record_id"] == 88
        approve.assert_called_once()
        execute.assert_called_once()

    def test_approval_executes_real_mcp_flow_for_standalone_proposal(self, api_client, staff_user):
        proposal = AgentProposalModel._default_manager.create(
            request_id="apr_terminal_real_1",
            proposal_type="terminal_mcp_capability",
            status="submitted",
            risk_level="high",
            approval_required=True,
            approval_status="pending",
            proposal_payload={
                "capability_key": "portfolio.write.rebalance",
                "arguments": {"account_id": 7},
                "session_id": "sess-real",
            },
            created_by=staff_user,
        )
        api_client.force_authenticate(user=staff_user)

        with patch(
            "apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool",
            side_effect=[
                {
                    "ok": False,
                    "status": "confirmation_required",
                    "capability_key": "portfolio.write.rebalance",
                    "confirmation_token": "confirm-real",
                },
                {
                    "ok": True,
                    "status": "completed",
                    "capability_key": "portfolio.write.rebalance",
                    "result": {"rebalanced": True},
                },
            ],
        ):
            response = api_client.post(
                f"/api/terminal/approvals/{proposal.id}/decision/",
                {"decision": "approve", "reason": "verified"},
                format="json",
            )

        assert response.status_code == 200
        proposal.refresh_from_db()
        assert proposal.status == "executed"
        record = AgentExecutionRecordModel._default_manager.get(proposal=proposal)
        assert record.task_id is None
        assert record.execution_output["mcp_result"]["result"] == {"rebalanced": True}


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
