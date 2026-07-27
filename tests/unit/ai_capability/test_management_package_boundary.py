"""AI Capability management package boundary regressions."""

from __future__ import annotations

from django.core.management import get_commands

from apps.ai_capability import management
from apps.ai_capability.interface import views


def test_management_package_does_not_publish_http_views() -> None:
    """Command discovery must not initialize the MCP tools HTTP implementation."""

    assert management.__all__ == ()
    assert not hasattr(management, "mcp_tools_page")
    assert not hasattr(management, "sync_mcp_tools_view")
    assert not hasattr(management, "toggle_mcp_tool_flag_view")


def test_interface_remains_the_only_mcp_tools_page_owner() -> None:
    """The routed MCP tools handlers remain owned by the Interface layer."""

    assert views.mcp_tools_page.__module__ == "apps.ai_capability.interface.views"
    assert views.sync_mcp_tools_view.__module__ == "apps.ai_capability.interface.views"
    assert views.toggle_mcp_tool_flag_view.__module__ == ("apps.ai_capability.interface.views")


def test_ai_capability_management_commands_remain_discoverable() -> None:
    """Removing dead page views must not alter the real command registry."""

    commands = get_commands()
    assert commands["govern_ai_capability_catalog"] == "apps.ai_capability"
    assert commands["init_ai_capability_catalog"] == "apps.ai_capability"
    assert commands["review_ai_capability_catalog"] == "apps.ai_capability"
    assert commands["sync_ai_capability_catalog"] == "apps.ai_capability"
