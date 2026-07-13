from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_dashboard_allocation_tool():
    manifest = SimpleNamespace(
        capability_key="dashboard.read.asset_allocation",
        summary="Read the authenticated user's aggregate asset allocation.",
        description="Governed user-scoped Dashboard allocation read.",
        owner_app="dashboard",
        tags=("dashboard", "account", "asset_allocation", "read"),
        audit_tags=(),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=("get_dashboard_allocation",),
    )
    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="get_dashboard_allocation",
                    description="legacy dashboard allocation",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    governed = by_key["mcp_tool.dashboard.read.asset_allocation"]
    assert governed.semantic_key == "dashboard.read.asset_allocation"
    assert governed.execution_target["replacement_for"] == [
        "get_dashboard_allocation"
    ]
    legacy = by_key["mcp_tool.get_dashboard_allocation"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "dashboard.read.asset_allocation"
    )
    assert legacy.enabled_for_terminal is False
