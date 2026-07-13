"""sentiment write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="sentiment.clear.cache",
        title="Clear Sentiment Cache",
        summary="Preview the global cache size, then confirm staff-only cache deletion.",
        description=(
            "Read the current sentiment health payload through the canonical Sentiment SDK, "
            "report the persisted cache row count without mutation, then require explicit "
            "confirmation before clearing all sentiment cache records."
        ),
        owner_app="sentiment",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="sentiment_clear_cache",
        tags=("sentiment", "cache", "clear", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("sentiment:clear_cache", "mcp:write"),
        legacy_tool_names=("clear_sentiment_cache",),
    ),
]
