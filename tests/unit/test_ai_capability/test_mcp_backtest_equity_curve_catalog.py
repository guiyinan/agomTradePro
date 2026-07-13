from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_backtest_equity_curve_tool():
    manifest = SimpleNamespace(
        capability_key="backtest.read.equity_curve",
        summary="Read one persisted backtest equity curve.",
        description="Governed staff-only persisted backtest curve read.",
        owner_app="backtest",
        tags=("backtest", "equity_curve", "staff", "read"),
        audit_tags=("backtest:equity_curve", "mcp:research_read"),
        input_schema={
            "type": "object",
            "properties": {"backtest_id": {"type": "integer"}},
            "required": ["backtest_id"],
        },
        risk_level="medium",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=("get_backtest_equity_curve",),
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
                    name="get_backtest_equity_curve",
                    description="legacy backtest equity curve",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    governed = by_key["mcp_tool.backtest.read.equity_curve"]
    assert governed.semantic_key == "backtest.read.equity_curve"
    assert governed.execution_target["replacement_for"] == [
        "get_backtest_equity_curve"
    ]
    legacy = by_key["mcp_tool.get_backtest_equity_curve"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "backtest.read.equity_curve"
    )
    assert legacy.enabled_for_terminal is False
