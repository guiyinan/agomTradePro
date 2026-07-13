from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_config_center_snapshot_legacy_tool():
    manifest = SimpleNamespace(
        capability_key="config_center.read.snapshot",
        summary="Read the redacted configuration snapshot.",
        description="Governed staff-only config center snapshot.",
        owner_app="config_center",
        tags=("config_center", "snapshot", "staff", "read"),
        audit_tags=("config_center:snapshot", "mcp:read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="medium",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=("get_config_center_snapshot",),
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
                    name="get_config_center_snapshot",
                    description="legacy snapshot",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.config_center.read.snapshot"]
    legacy = by_key["mcp_tool.get_config_center_snapshot"]
    assert governed.semantic_key == "config_center.read.snapshot"
    assert governed.execution_target["audit_tags"] == [
        "config_center:snapshot",
        "mcp:read",
    ]
    assert legacy.execution_target["replacement_capability_key"] == ("config_center.read.snapshot")
    assert legacy.semantic_key == "config_center.read.snapshot"
    assert legacy.enabled_for_terminal is False
