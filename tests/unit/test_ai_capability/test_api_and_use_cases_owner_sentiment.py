# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_sentiment."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_sentiment_clear_cache_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="sentiment.clear.cache",
        summary="Preview the cache count, then clear the sentiment cache.",
        description="Governed write capability for global sentiment cache deletion.",
        owner_app="sentiment",
        tags=("sentiment", "cache", "clear", "delete", "write"),
        audit_tags=("sentiment:clear_cache", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("clear_sentiment_cache",),
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
                SimpleNamespace(
                    name="clear_sentiment_cache",
                    description="clear sentiment cache",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.sentiment.clear.cache"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["clear_sentiment_cache"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "sentiment:clear_cache",
        "mcp:write",
    ]
    assert governed.semantic_key == "sentiment.clear.cache"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.clear_sentiment_cache"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "sentiment.clear.cache"
    assert legacy.semantic_key == "sentiment.clear.cache"
    assert legacy.enabled_for_terminal is False
