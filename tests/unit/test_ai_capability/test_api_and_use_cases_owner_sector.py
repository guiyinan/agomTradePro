# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_sector."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_maps_sector_rotation_ranking_legacy_aliases():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="sector.read.rotation_ranking",
        summary="Read persisted sector rotation ranking.",
        description="Pure persisted Sector ranking read.",
        owner_app="sector",
        tags=("sector", "rotation", "ranking", "read"),
        audit_tags=(),
        input_schema={
            "type": "object",
            "properties": {
                "regime": {"type": ["string", "null"]},
                "lookback_days": {"type": "integer"},
                "level": {"type": "string"},
                "top_n": {"type": "integer"},
            },
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=(
            "list_sectors",
            "get_sector_recommendations",
            "get_hot_sectors",
        ),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                *[
                    SimpleNamespace(name=name, description="sector read", inputSchema={})
                    for name in governed_manifest.legacy_tool_names
                ],
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.sector.read.rotation_ranking"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == list(governed_manifest.legacy_tool_names)
    assert governed.semantic_key == "sector.read.rotation_ranking"
    assert governed.enabled_for_terminal is True

    for tool_name in governed_manifest.legacy_tool_names:
        legacy = by_key[f"mcp_tool.{tool_name}"]
        assert (
            legacy.execution_target["replacement_capability_key"] == "sector.read.rotation_ranking"
        )
        assert legacy.semantic_key == "sector.read.rotation_ranking"
        assert legacy.enabled_for_terminal is False
