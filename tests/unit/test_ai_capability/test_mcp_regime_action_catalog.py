from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_regime_action_recommendation_tool():
    manifest = SimpleNamespace(
        capability_key="regime.read.action_recommendation",
        summary="Read the current decision-safe Regime and Pulse action recommendation.",
        description="Governed read-only action recommendation.",
        owner_app="regime",
        tags=("regime", "pulse", "action", "read"),
        audit_tags=("regime:action_recommendation", "mcp:decision_read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="medium",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=("get_action_recommendation",),
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
                    name="get_action_recommendation",
                    description="legacy action recommendation",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    governed = by_key["mcp_tool.regime.read.action_recommendation"]
    assert governed.semantic_key == "regime.read.action_recommendation"
    assert governed.execution_target["replacement_for"] == [
        "get_action_recommendation"
    ]
    legacy = by_key["mcp_tool.get_action_recommendation"]
    assert legacy.execution_target["replacement_capability_key"] == (
        "regime.read.action_recommendation"
    )
    assert legacy.enabled_for_terminal is False
