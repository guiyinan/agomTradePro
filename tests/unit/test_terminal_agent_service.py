"""Unit tests for the refactored terminal agent service."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentChatRequestDTO,
    TerminalAgentEventDTO,
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
        def __init__(self, *, params, cache_tools_list, tool_filter, name):
            captured["params"] = params
            captured["cache_tools_list"] = cache_tools_list
            captured["tool_filter"] = tool_filter
            captured["name"] = name

    service = OpenAIAgentsTerminalService()
    tool_access = SimpleNamespace(
        auto_allowed={"read_regime": {"tool_name": "read_regime"}},
        gated={},
    )
    server = service._build_mcp_server({"MCPServerStdio": FakeServer}, tool_access)

    assert isinstance(server, FakeServer)
    assert captured["params"]["command"].lower().endswith("python.exe")
    assert captured["params"]["args"] == ["-m", "agomtradepro_mcp.server"]
    assert "PYTHONPATH" in captured["params"]["env"]
    assert captured["cache_tools_list"] is True
    assert captured["name"] == "agomtradepro"
    assert captured["tool_filter"](SimpleNamespace(server_name="stdio"), SimpleNamespace(name="read_regime")) is True


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
    capability_repo = Mock()
    safe_cap = SimpleNamespace(
        source_ref="read_regime",
        enabled_for_terminal=True,
        risk_level=SimpleNamespace(value="safe"),
        requires_confirmation=False,
        capability_key="mcp_tool.read_regime",
        summary="Read regime",
    )
    gated_cap = SimpleNamespace(
        source_ref="rebalance_portfolio",
        enabled_for_terminal=True,
        risk_level=SimpleNamespace(value="high"),
        requires_confirmation=True,
        capability_key="mcp_tool.rebalance_portfolio",
        summary="Rebalance",
    )
    capability_repo.get_by_source_type.return_value = [safe_cap, gated_cap]

    service = OpenAIAgentsTerminalService(capability_repo=capability_repo)
    with patch.object(
        service._capability_filter,
        "filter_by_context",
        return_value=[safe_cap, gated_cap],
    ):
        snapshot = service._build_tool_access_snapshot(_request())

    assert "read_regime" in snapshot.auto_allowed
    assert "rebalance_portfolio" in snapshot.gated


def test_build_tool_access_snapshot_keeps_low_risk_tools_auto_allowed_even_if_confirmation_flagged():
    capability_repo = Mock()
    low_cap = SimpleNamespace(
        source_ref="check_alpha_health",
        enabled_for_terminal=True,
        risk_level=SimpleNamespace(value="low"),
        requires_confirmation=True,
        capability_key="mcp_tool.check_alpha_health",
        summary="Health check",
    )
    capability_repo.get_by_source_type.return_value = [low_cap]

    service = OpenAIAgentsTerminalService(capability_repo=capability_repo)
    with patch.object(
        service._capability_filter,
        "filter_by_context",
        return_value=[low_cap],
    ):
        snapshot = service._build_tool_access_snapshot(_request())

    assert "check_alpha_health" in snapshot.auto_allowed
    assert "check_alpha_health" not in snapshot.gated


def test_match_gated_tool_returns_high_confidence_match():
    capability_repo = Mock()
    matched_capability = SimpleNamespace(source_ref="rebalance_portfolio")
    capability_repo.get_by_key.return_value = matched_capability

    service = OpenAIAgentsTerminalService(capability_repo=capability_repo)
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

    with patch.object(
        service._retrieval_scorer,
        "retrieve_top_k",
        return_value=[SimpleNamespace(capability=matched_capability)],
    ):
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
