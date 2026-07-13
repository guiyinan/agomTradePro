from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_dashboard_equity_curve_tool():
    manifest = SimpleNamespace(
        capability_key="dashboard.read.equity_curve",
        summary="Read the authenticated user's portfolio equity curve.",
        description="Governed read-only Dashboard equity curve.",
        owner_app="dashboard",
        tags=("dashboard", "portfolio", "equity_curve", "read"),
        audit_tags=(),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=("get_dashboard_equity_curve_v1",),
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
                    name="get_dashboard_equity_curve_v1",
                    description="legacy equity curve",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    governed = by_key["mcp_tool.dashboard.read.equity_curve"]
    assert governed.semantic_key == "dashboard.read.equity_curve"
    assert governed.execution_target["replacement_for"] == [
        "get_dashboard_equity_curve_v1"
    ]
    legacy = by_key["mcp_tool.get_dashboard_equity_curve_v1"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "dashboard.read.equity_curve"
    )
    assert legacy.enabled_for_terminal is False
