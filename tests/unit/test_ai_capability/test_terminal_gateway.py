"""Tests for the AI Capability gateway injected into Terminal Agent."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.ai_capability.application.facade import CapabilityRoutingFacade


def test_terminal_gateway_returns_normalized_visible_mcp_capabilities():
    capability_repo = Mock()
    capability = SimpleNamespace(
        capability_key="mcp_tool.account.update.macro_sizing_config",
        source_ref="account.update.macro_sizing_config",
        summary="Update macro sizing config",
        risk_level=SimpleNamespace(value="high"),
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "account.update.macro_sizing_config",
        },
        enabled_for_terminal=True,
    )
    capability_repo.get_by_source_type.return_value = [capability]
    facade = CapabilityRoutingFacade(
        capability_repo=capability_repo,
        routing_log_repo=Mock(),
    )

    with patch(
        "apps.ai_capability.application.facade.CapabilityFilter.filter_by_context",
        return_value=[capability],
    ):
        result = facade.list_terminal_mcp_capabilities(
            session_id="session-1",
            user_id=7,
            user_is_admin=True,
            mcp_enabled=True,
            provider_name="provider",
            model="model",
            context={"source": "test"},
        )

    capability_repo.get_by_source_type.assert_called_once_with("mcp_tool")
    assert result == [
        {
            "capability_key": "mcp_tool.account.update.macro_sizing_config",
            "source_ref": "account.update.macro_sizing_config",
            "summary": "Update macro sizing config",
            "risk_level": "high",
            "execution_target": {
                "type": "mcp_capability",
                "tool_name": "agom_capability_call",
                "capability_key": "account.update.macro_sizing_config",
            },
        }
    ]


def test_terminal_gateway_returns_high_confidence_capability_match():
    capability_repo = Mock()
    capability = SimpleNamespace(
        capability_key="mcp_tool.account.update.macro_sizing_config",
        risk_level=SimpleNamespace(value="high"),
    )
    capability_repo.get_by_key.return_value = capability
    facade = CapabilityRoutingFacade(
        capability_repo=capability_repo,
        routing_log_repo=Mock(),
    )
    facade.retrieval_scorer = Mock()
    facade.retrieval_scorer.retrieve_top_k.return_value = [SimpleNamespace(capability=capability)]

    result = facade.match_terminal_mcp_capability(
        message="update macro sizing config",
        capability_keys=["mcp_tool.account.update.macro_sizing_config"],
    )

    assert result == {
        "capability_key": "mcp_tool.account.update.macro_sizing_config",
        "risk_level": "high",
    }


def test_terminal_gateway_hides_staff_capability_from_non_admin_user():
    capability_repo = Mock()
    capability = SimpleNamespace(
        capability_key="mcp_tool.config_center.update.runtime_setting",
        source_ref="config_center.update.runtime_setting",
        summary="Update runtime setting",
        risk_level=SimpleNamespace(value="high"),
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "config_center.update.runtime_setting",
            "required_roles": ["staff"],
        },
        enabled_for_terminal=True,
    )
    capability_repo.get_by_source_type.return_value = [capability]
    facade = CapabilityRoutingFacade(
        capability_repo=capability_repo,
        routing_log_repo=Mock(),
    )

    with patch(
        "apps.ai_capability.application.facade.CapabilityFilter.filter_by_context",
        return_value=[capability],
    ):
        result = facade.list_terminal_mcp_capabilities(
            session_id="session-1",
            user_id=7,
            user_is_admin=False,
            mcp_enabled=True,
            provider_name="provider",
            model="model",
            context={"user_role": "read_only"},
        )

    assert result == []
