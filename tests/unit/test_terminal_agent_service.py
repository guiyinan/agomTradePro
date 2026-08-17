"""Unit tests for the refactored terminal agent service."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentBusyError,
    TerminalAgentChatRequestDTO,
    TerminalAgentEventDTO,
    TerminalAgentTimeoutError,
)
from apps.agent_runtime.infrastructure.terminal_agent_service import OpenAIAgentsTerminalService


def _request(**overrides):
    payload = {
        "message": "show system status",
        "session_id": "sess-1",
        "user_id": 7,
        "username": "ops_user",
        "user_role": "admin",
        "user_is_admin": True,
        "mcp_enabled": True,
        "provider_ref": None,
        "model": None,
        "context": {},
    }
    payload.update(overrides)
    return TerminalAgentChatRequestDTO(**payload)


def test_build_mcp_server_uses_stdio_python_module_entrypoint():
    captured = {}

    class FakeServer:
        def __init__(
            self,
            *,
            params,
            cache_tools_list,
            client_session_timeout_seconds,
            tool_filter,
            name,
        ):
            captured["params"] = params
            captured["cache_tools_list"] = cache_tools_list
            captured["client_session_timeout_seconds"] = client_session_timeout_seconds
            captured["tool_filter"] = tool_filter
            captured["name"] = name

    service = OpenAIAgentsTerminalService()
    tool_access = SimpleNamespace(
        auto_allowed={"read_regime": {"tool_name": "read_regime"}},
        gated={},
        allowed_tool_names=frozenset({"read_regime"}),
    )
    server = service._build_mcp_server({"MCPServerStdio": FakeServer}, _request(), tool_access)

    assert isinstance(server, FakeServer)
    assert Path(captured["params"]["command"]).name.lower() in {"python", "python.exe"}
    assert captured["params"]["args"] == ["-m", "agomtradepro_mcp.server"]
    assert "PYTHONPATH" in captured["params"]["env"]
    assert captured["params"]["env"]["AGOMTRADEPRO_INTERNAL_USER_ID"] == "7"
    assert captured["params"]["env"]["AGOMTRADEPRO_INTERNAL_USERNAME"] == "ops_user"
    assert captured["params"]["env"]["AGOMTRADEPRO_INTERNAL_SOURCE"] == "terminal_mcp"
    assert captured["params"]["env"]["AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS"] == "true"
    assert captured["params"]["env"]["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] == "false"
    assert captured["params"]["env"]["AGOMTRADEPRO_MCP_ROLE"] == "admin"
    assert captured["cache_tools_list"] is True
    assert captured["client_session_timeout_seconds"] == 20.0
    assert captured["params"]["env"]["AGOMTRADEPRO_TIMEOUT"] == "8.0"
    assert captured["params"]["env"]["AGOMTRADEPRO_MAX_RETRIES"] == "0"
    assert captured["params"]["env"]["AGOMTRADEPRO_AUDIT_TIMEOUT_SECONDS"] == "2.0"
    assert captured["params"]["env"]["AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS"] == "1"
    assert captured["params"]["env"]["AGOMTRADEPRO_AUDIT_RETRY_BACKOFF_SECONDS"] == "0"
    assert captured["name"] == "agomtradepro"
    assert (
        captured["tool_filter"](
            SimpleNamespace(server_name="stdio"), SimpleNamespace(name="read_regime")
        )
        is True
    )


def test_resolve_provider_prefers_personal_provider_without_fallback_quota():
    provider_repo = Mock()
    usage_repo = Mock()
    quota_repo = Mock()
    personal = SimpleNamespace(
        id=1,
        name="personal-ai",
        scope="user",
        base_url="https://example.test/v1",
        default_model="gpt-personal",
        daily_budget_limit=None,
        monthly_budget_limit=None,
    )
    user = SimpleNamespace(id=7)

    provider_repo.get_provider_for_reference.return_value = None
    provider_repo.get_active_configured_user_providers.return_value = [personal]
    provider_repo.get_active_configured_system_providers.return_value = []
    provider_repo.get_api_key.return_value = "secret"
    usage_repo.check_budget_limits.return_value = {
        "daily": {"exceeded": False},
        "monthly": {"exceeded": False},
    }

    service = OpenAIAgentsTerminalService(
        provider_repo=provider_repo,
        usage_repo=usage_repo,
        quota_repo=quota_repo,
    )

    with patch.object(service, "_resolve_user", return_value=user):
        resolved = service._resolve_provider(_request())

    assert resolved.provider is personal
    assert resolved.provider_scope == "personal"
    assert resolved.quota_charged is False
    assert resolved.model == "gpt-personal"
    assert resolved.user is user


def test_resolve_provider_uses_system_fallback_when_personal_missing():
    provider_repo = Mock()
    usage_repo = Mock()
    quota_repo = Mock()
    system = SimpleNamespace(
        id=2,
        name="system-ai",
        scope="system",
        base_url="https://example.test/v1",
        default_model="gpt-system",
        daily_budget_limit=None,
        monthly_budget_limit=None,
    )
    user = SimpleNamespace(id=7)

    provider_repo.get_provider_for_reference.return_value = None
    provider_repo.get_active_configured_user_providers.return_value = []
    provider_repo.get_active_configured_system_providers.return_value = [system]
    provider_repo.get_api_key.return_value = "system-secret"
    usage_repo.check_budget_limits.return_value = {
        "daily": {"exceeded": False},
        "monthly": {"exceeded": False},
    }
    quota_repo.get_with_usage.return_value = (
        SimpleNamespace(is_active=True, daily_limit=None, monthly_limit=None),
        0.0,
        0.0,
    )

    service = OpenAIAgentsTerminalService(
        provider_repo=provider_repo,
        usage_repo=usage_repo,
        quota_repo=quota_repo,
    )

    with patch.object(service, "_resolve_user", return_value=user):
        resolved = service._resolve_provider(_request())

    assert resolved.provider is system
    assert resolved.provider_scope == "system_fallback"
    assert resolved.quota_charged is True
    assert resolved.user is user


def test_build_tool_access_snapshot_separates_auto_and_gated_tools():
    capability_gateway = Mock()
    capability_gateway.list_terminal_mcp_capabilities.return_value = [
        {
            "source_ref": "read_regime",
            "execution_target": {"type": "mcp_tool", "tool_name": "read_regime"},
            "risk_level": "safe",
            "capability_key": "mcp_tool.read_regime",
            "summary": "Read regime",
        },
        {
            "source_ref": "rebalance_portfolio",
            "execution_target": {"type": "mcp_tool", "tool_name": "rebalance_portfolio"},
            "risk_level": "high",
            "capability_key": "mcp_tool.rebalance_portfolio",
            "summary": "Rebalance",
        },
    ]

    service = OpenAIAgentsTerminalService(capability_gateway=capability_gateway)
    snapshot = service._build_tool_access_snapshot(_request())

    assert "read_regime" in snapshot.auto_allowed
    assert "rebalance_portfolio" in snapshot.gated
    assert snapshot.allowed_tool_names == frozenset({"read_regime", "rebalance_portfolio"})


def test_build_tool_access_snapshot_keeps_low_risk_tools_auto_allowed_even_if_confirmation_flagged():
    capability_gateway = Mock()
    capability_gateway.list_terminal_mcp_capabilities.return_value = [
        {
            "source_ref": "check_alpha_health",
            "execution_target": {
                "type": "mcp_tool",
                "tool_name": "check_alpha_health",
            },
            "risk_level": "low",
            "capability_key": "mcp_tool.check_alpha_health",
            "summary": "Health check",
        }
    ]

    service = OpenAIAgentsTerminalService(capability_gateway=capability_gateway)
    snapshot = service._build_tool_access_snapshot(_request())

    assert "check_alpha_health" in snapshot.auto_allowed
    assert "check_alpha_health" not in snapshot.gated


def test_build_tool_access_snapshot_prefers_core_tools_for_governed_mcp_capabilities():
    capability_gateway = Mock()
    capability_gateway.list_terminal_mcp_capabilities.return_value = [
        {
            "source_ref": "system.read.regime.current",
            "execution_target": {
                "type": "mcp_capability",
                "tool_name": "agom_capability_call",
                "capability_key": "system.read.regime.current",
            },
            "risk_level": "safe",
            "capability_key": "mcp_tool.system.read.regime.current",
            "summary": "Read regime through governed MCP capability",
        }
    ]

    service = OpenAIAgentsTerminalService(capability_gateway=capability_gateway)
    snapshot = service._build_tool_access_snapshot(_request())

    assert "mcp_tool.system.read.regime.current" in snapshot.auto_allowed
    assert (
        snapshot.auto_allowed["mcp_tool.system.read.regime.current"]["discovery_key"]
        == "system.read.regime.current"
    )
    assert "agom_capability_call" in snapshot.allowed_tool_names
    assert "agom_capability_search" in snapshot.allowed_tool_names
    assert "agom_bootstrap" in snapshot.allowed_tool_names


def test_build_agent_instructions_use_compact_governed_discovery_summary():
    service = OpenAIAgentsTerminalService()
    auto_allowed = {
        f"account.read.capability_{index}": {
            "capability_key": f"account.read.capability_{index}",
            "execution_target_type": "mcp_capability",
        }
        for index in range(200)
    }
    gated = {
        f"strategy.update.capability_{index}": {
            "capability_key": f"strategy.update.capability_{index}",
            "execution_target_type": "mcp_capability",
        }
        for index in range(100)
    }
    tool_access = SimpleNamespace(
        auto_allowed=auto_allowed,
        gated=gated,
        allowed_tool_names=frozenset(
            {
                "agom_capability_search",
                "agom_capability_schema",
                "agom_capability_call",
            }
        ),
    )

    instructions = service._build_agent_instructions(_request(), tool_access)

    assert "200 auto-approved" in instructions
    assert "100 approval-gated" in instructions
    assert "account, strategy" in instructions
    assert "agom_capability_search" in instructions
    assert "agom_capability_schema" in instructions
    assert "agom_capability_call" in instructions
    assert "terminal.search.user_actions" in instructions
    assert "execute it only through agom_capability_call" in instructions
    assert "Never call internal executor names" in instructions
    assert "source observation date" in instructions
    assert "must_not_use_for_decision=true" in instructions
    assert "account.read.capability_199" not in instructions
    assert "strategy.update.capability_99" not in instructions
    assert len(instructions) < 1_200


def test_collect_events_returns_unknown_tools_to_model_for_self_correction():
    captured = {}

    class FakeRunConfig:
        def __init__(self, *, tool_not_found_behavior):
            self.tool_not_found_behavior = tool_not_found_behavior

    class FakeStreamed:
        final_output = "System is healthy"

        async def stream_events(self):
            if False:
                yield None

    class FakeRunner:
        @staticmethod
        def run_streamed(**kwargs):
            captured.update(kwargs)
            return FakeStreamed()

    class FakeMCPServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    service = OpenAIAgentsTerminalService()
    sdk = {"Runner": FakeRunner, "RunConfig": FakeRunConfig}
    resolved_provider = SimpleNamespace(provider=SimpleNamespace(), model="test-model")
    tool_access = SimpleNamespace(auto_allowed={}, gated={}, allowed_tool_names=frozenset())

    with (
        patch.object(service, "_import_agents_sdk", return_value=sdk),
        patch.object(service, "_build_agent_session", return_value=None),
        patch.object(service, "_build_mcp_server", return_value=FakeMCPServer()),
        patch.object(service, "_build_agent", return_value="agent"),
        patch.object(service, "_extract_usage", return_value={}),
        patch.object(service, "_build_final_metadata", return_value={}),
    ):
        events = asyncio.run(service._collect_events(_request(), resolved_provider, tool_access))

    assert captured["run_config"].tool_not_found_behavior == "return_error_to_model"
    assert captured["max_turns"] == 4
    assert events[-1].event_type == "final"
    assert events[-1].data["reply"] == "System is healthy"


def test_stream_chat_returns_bounded_timeout_event_and_releases_execution_guard():
    guard = Mock()
    guard.acquire.return_value.__enter__ = Mock(return_value=None)
    guard.acquire.return_value.__exit__ = Mock(return_value=False)
    service = OpenAIAgentsTerminalService(
        execution_guard=guard,
        execution_timeout_seconds=0.01,
    )

    async def slow_collect(*_args):
        await asyncio.sleep(1)
        return []

    with (
        patch.object(service, "_build_tool_access_snapshot", return_value=SimpleNamespace()),
        patch.object(service, "_resolve_provider", return_value=SimpleNamespace()),
        patch.object(service, "_collect_events", side_effect=slow_collect),
        patch.object(service, "_log_terminal_run"),
    ):
        events = list(service.stream_chat(_request()))

    assert events == [
        TerminalAgentEventDTO(
            event_type="error",
            data={
                "session_id": "sess-1",
                "message": "terminal_agent_timeout",
            },
        )
    ]
    guard.acquire.return_value.__exit__.assert_called_once()


def test_run_chat_maps_bounded_error_events_to_typed_exceptions():
    service = OpenAIAgentsTerminalService()

    with patch.object(
        service,
        "stream_chat",
        return_value=iter(
            [
                TerminalAgentEventDTO(
                    event_type="error",
                    data={"message": "terminal_agent_busy"},
                )
            ]
        ),
    ):
        with pytest.raises(TerminalAgentBusyError):
            service.run_chat(_request())

    with patch.object(
        service,
        "stream_chat",
        return_value=iter(
            [
                TerminalAgentEventDTO(
                    event_type="error",
                    data={"message": "terminal_agent_timeout"},
                )
            ]
        ),
    ):
        with pytest.raises(TerminalAgentTimeoutError):
            service.run_chat(_request())


def test_match_gated_tool_returns_high_confidence_match():
    capability_gateway = Mock()
    capability_gateway.match_terminal_mcp_capability.return_value = {
        "capability_key": "mcp_tool.rebalance_portfolio",
        "risk_level": "high",
    }
    service = OpenAIAgentsTerminalService(capability_gateway=capability_gateway)
    tool_access = SimpleNamespace(
        auto_allowed={},
        gated={
            "rebalance_portfolio": {
                "capability_key": "mcp_tool.rebalance_portfolio",
                "tool_name": "rebalance_portfolio",
                "risk_level": "high",
                "summary": "Rebalance",
            }
        },
    )

    matched = service._match_gated_tool(
        _request(message="rebalance the account"),
        tool_access,
    )

    assert matched["tool_name"] == "rebalance_portfolio"
    assert matched["risk_level"] == "high"


def test_map_stream_event_maps_mcp_approval_requests():
    service = OpenAIAgentsTerminalService()
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="mcp_approval_requested",
        item=SimpleNamespace(
            type="mcp_approval_request_item",
            raw_item=SimpleNamespace(
                id="approval-1",
                name="rebalance_portfolio",
                arguments='{"account_id": 1}',
                server_label="agomtradepro",
            ),
        ),
    )

    mapped = service._map_stream_event(event)

    assert mapped == [
        TerminalAgentEventDTO(
            event_type="approval_required",
            data={
                "tool_name": "rebalance_portfolio",
                "arguments": '{"account_id": 1}',
                "approval_request_id": "approval-1",
                "server_label": "agomtradepro",
                "message": "该操作涉及受控 MCP 工具，当前不会自动执行。请进入审批流程后再继续。",
            },
        )
    ]


def test_stage_mcp_confirmation_persists_model_generated_arguments():
    approval_gateway = Mock()
    approval_gateway.stage_terminal_mcp_capability.return_value = {
        "proposal_id": 41,
        "request_id": "apr_20260713_ABC123",
        "status": "submitted",
    }
    service = OpenAIAgentsTerminalService(approval_gateway=approval_gateway)
    tool_access = SimpleNamespace(
        auto_allowed={},
        gated={
            "mcp_tool.portfolio.write.rebalance": {
                "capability_key": "mcp_tool.portfolio.write.rebalance",
                "discovery_key": "portfolio.write.rebalance",
                "risk_level": "high",
                "summary": "Rebalance portfolio",
            }
        },
    )
    events = [
        TerminalAgentEventDTO(
            event_type="tool_called",
            data={
                "tool_name": "agom_capability_call",
                "arguments": (
                    '{"capability_key":"portfolio.write.rebalance",'
                    '"arguments":{"account_id":7,"target":{"equity":0.6}}}'
                ),
            },
        ),
        TerminalAgentEventDTO(
            event_type="tool_output",
            data={
                "tool_name": "agom_capability_call",
                "output": (
                    '{"ok":false,"status":"confirmation_required",'
                    '"capability_key":"portfolio.write.rebalance",'
                    '"confirmation_token":"ephemeral-token"}'
                ),
            },
        ),
    ]

    approval_event = service._stage_mcp_confirmation(
        request=_request(message="rebalance account 7"),
        tool_access=tool_access,
        events=events,
    )

    approval_gateway.stage_terminal_mcp_capability.assert_called_once_with(
        capability_key="portfolio.write.rebalance",
        arguments={"account_id": 7, "target": {"equity": 0.6}},
        risk_level="high",
        summary="Rebalance portfolio",
        session_id="sess-1",
        user_id=7,
        actor={
            "user_id": 7,
            "username": "ops_user",
            "is_staff": True,
            "roles": ["admin"],
        },
    )
    assert approval_event.event_type == "approval_required"
    assert approval_event.data["proposal_id"] == 41
    assert approval_event.data["capability_key"] == "portfolio.write.rebalance"
    assert "ephemeral-token" not in str(approval_event.data)


def test_collect_events_redacts_sdk_exception_details(caplog):
    service = OpenAIAgentsTerminalService()
    resolved_provider = SimpleNamespace(provider=SimpleNamespace(), model="test-model")
    tool_access = SimpleNamespace(
        auto_allowed={},
        gated={},
        allowed_tool_names=frozenset(),
    )

    with patch.object(
        service,
        "_import_agents_sdk",
        side_effect=RuntimeError("postgresql://admin:raw-secret@example.test/terminal"),
    ):
        events = asyncio.run(service._collect_events(_request(), resolved_provider, tool_access))

    assert events == [
        TerminalAgentEventDTO(
            event_type="error",
            data={
                "session_id": "sess-1",
                "message": "terminal_agent_execution_failed",
            },
        )
    ]
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


def test_error_usage_audit_uses_stable_message_and_redacts_repository_failure(caplog):
    usage_repo = Mock()
    usage_repo.log_usage.side_effect = RuntimeError(
        "postgresql://admin:audit-secret@example.test/terminal"
    )
    service = OpenAIAgentsTerminalService(usage_repo=usage_repo)
    resolved_provider = SimpleNamespace(
        provider=SimpleNamespace(),
        user=SimpleNamespace(id=7),
        provider_scope="personal",
        quota_charged=False,
        model="test-model",
        fallback_used=False,
    )

    service._log_terminal_run(
        request=_request(),
        resolved_provider=resolved_provider,
        events=[
            TerminalAgentEventDTO(
                event_type="error",
                data={"message": "postgresql://admin:event-secret@example.test/terminal"},
            )
        ],
    )

    assert usage_repo.log_usage.call_args.kwargs["error_message"] == (
        "terminal_agent_execution_failed"
    )
    assert "audit-secret" not in caplog.text
    assert "event-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
