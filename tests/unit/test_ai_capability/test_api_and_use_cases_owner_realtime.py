# ruff: noqa: F403, F405
"""AI capability projection evidence for governed realtime management."""

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

from .api_and_use_cases_support import *


def test_sync_mcp_tools_projects_all_realtime_management_capabilities() -> None:
    """Native and legacy-backed realtime management remain routable after sync."""

    keys = {
        "realtime.read.alerts",
        "realtime.read.alert",
        "realtime.create.price_alert",
        "realtime.update.price_alert",
        "realtime.delete.price_alert",
        "realtime.read.price_subscriptions",
        "realtime.create.price_subscription",
        "realtime.delete.price_subscription",
    }
    expected_replacements = {
        "list_price_alerts": "realtime.read.alerts",
        "create_price_alert": "realtime.create.price_alert",
        "delete_price_alert": "realtime.delete.price_alert",
    }
    registry = CapabilityRegistryLoader().build_registry()
    manifests = [registry[key] for key in sorted(keys)]
    raw_names = set(expected_replacements)
    tools = [
        SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
        *[
            SimpleNamespace(name=name, description=name, inputSchema={})
            for name in sorted(raw_names)
        ],
    ]

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=manifests,
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=tools,
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    for key in keys:
        governed = by_key[f"mcp_tool.{key}"]
        assert governed.execution_target["type"] == "mcp_capability"
        assert governed.execution_target["capability_key"] == key
        assert governed.enabled_for_terminal is True
    for raw_name in raw_names:
        legacy = by_key[f"mcp_tool.{raw_name}"]
        assert (
            legacy.execution_target["replacement_capability_key"] == expected_replacements[raw_name]
        )
