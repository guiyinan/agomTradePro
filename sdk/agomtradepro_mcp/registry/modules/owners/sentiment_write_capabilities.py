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

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="sentiment.execute.analysis",
            title="Execute Sentiment Analysis",
            summary="Preview and confirm one provider-backed sentiment analysis.",
            description=(
                "Show a redacted text fingerprint and cache policy before invoking the AI "
                "provider and writing cache or analysis-log records."
            ),
            owner_app="sentiment",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="sentiment_execute_analysis",
            tags=("sentiment", "ai", "analysis", "execute", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("sentiment:execute_analysis", "mcp:write"),
            legacy_tool_names=("analyze_sentiment",),
        ),
        CapabilityManifest(
            capability_key="sentiment.execute.batch_analysis",
            title="Execute Batch Sentiment Analysis",
            summary="Preview and confirm one bounded provider-backed sentiment batch.",
            description=(
                "Show text count and redacted fingerprints before invoking the AI provider "
                "for a batch of at most 50 items."
            ),
            owner_app="sentiment",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="sentiment_execute_batch_analysis",
            tags=("sentiment", "ai", "batch", "analysis", "execute", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("sentiment:execute_batch_analysis", "mcp:write"),
            legacy_tool_names=("batch_analyze_sentiment",),
        ),
    ]
)
