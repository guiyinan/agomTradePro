from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


def test_sync_mcp_tools_replaces_legacy_alpha_score_upload():
    manifest = SimpleNamespace(
        capability_key="alpha.import.score_cache",
        summary="Preview and import one bounded Alpha score batch.",
        description="Governed staff-only Alpha score-cache import.",
        owner_app="alpha",
        tags=("alpha", "score", "cache", "import", "batch", "write"),
        audit_tags=("alpha:score_cache_import", "mcp:write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("upload_alpha_scores",),
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
                    name="upload_alpha_scores", description="legacy upload", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.alpha.import.score_cache"]
    legacy = by_key["mcp_tool.upload_alpha_scores"]
    assert governed.semantic_key == "alpha.import.score_cache"
    assert governed.requires_confirmation is True
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["replacement_for"] == ["upload_alpha_scores"]
    assert legacy.execution_target["replacement_capability_key"] == "alpha.import.score_cache"
    assert legacy.enabled_for_terminal is False
