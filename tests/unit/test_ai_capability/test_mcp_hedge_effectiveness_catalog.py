from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_duplicate_hedge_effectiveness_tools():
    manifest = SimpleNamespace(
        capability_key="hedge.compute.effectiveness",
        summary="Compute one hedge pair's current effectiveness.",
        description="Pure governed Hedge effectiveness calculation.",
        owner_app="hedge",
        tags=("hedge", "effectiveness", "calculation"),
        audit_tags=("hedge:effectiveness", "mcp:compute"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="medium",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=(
            "check_hedge_effectiveness",
            "is_my_hedge_still_working",
        ),
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
                    name="check_hedge_effectiveness", description="check", inputSchema={}
                ),
                SimpleNamespace(
                    name="is_my_hedge_still_working", description="quick check", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    governed = by_key["mcp_tool.hedge.compute.effectiveness"]
    assert governed.semantic_key == "hedge.compute.effectiveness"
    assert governed.execution_target["replacement_for"] == [
        "check_hedge_effectiveness",
        "is_my_hedge_still_working",
    ]
    for legacy_name in manifest.legacy_tool_names:
        legacy = by_key[f"mcp_tool.{legacy_name}"]
        assert legacy.execution_target["replacement_capability_key"] == (
            "hedge.compute.effectiveness"
        )
        assert legacy.enabled_for_terminal is False
