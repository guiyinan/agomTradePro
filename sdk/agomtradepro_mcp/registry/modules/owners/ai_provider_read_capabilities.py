"""ai_provider read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="ai_provider.read.provider_catalog",
        title="AI Provider Catalog",
        summary="Read the AI provider catalog list.",
        description=(
            "Return the configured AI provider catalog used by operator workflows, including "
            "provider type, activation state, base URL, and default model metadata."
        ),
        owner_app="ai_provider",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_ai_providers",
        tags=("ai_provider", "provider", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "providers": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_ai_providers",),
    ),
    CapabilityManifest(
        capability_key="ai_provider.read.provider_detail",
        title="AI Provider Detail",
        summary="Read a single AI provider configuration detail.",
        description=(
            "Return one configured AI provider entry used by operator workflows, "
            "including scope, activation state, endpoint metadata, and default model."
        ),
        owner_app="ai_provider",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_ai_provider",
        tags=("ai_provider", "provider", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
            },
            "required": ["provider_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "provider_id": {"type": "integer"},
                "name": {"type": "string"},
                "scope": {"type": "string"},
                "provider_type": {"type": "string"},
                "base_url": {"type": "string"},
                "default_model": {"type": "string"},
                "is_active": {"type": "boolean"},
                "success": {"type": "boolean"},
                "error": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_ai_provider",),
    ),
    CapabilityManifest(
        capability_key="ai_provider.read.usage_logs",
        title="AI Provider Usage Logs",
        summary="Read AI provider usage logs.",
        description=(
            "Return recent AI provider usage log entries for operator audit workflows, "
            "including provider identity, token usage, cost, latency, and status."
        ),
        owner_app="ai_provider",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_ai_usage_logs",
        tags=("ai_provider", "usage", "logs", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "logs": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_ai_usage_logs",),
    ),
]
