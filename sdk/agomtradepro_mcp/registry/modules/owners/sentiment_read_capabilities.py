"""sentiment read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="sentiment.read.index",
        title="Sentiment Index",
        summary="Read one canonical sentiment index snapshot.",
        description=(
            "Return the latest sentiment index, or the index for one requested date, "
            "with confidence, data sufficiency, sector distribution, and source evidence."
        ),
        owner_app="sentiment",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_sentiment_index",
        tags=("sentiment", "index", "market_mood", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "format": "date",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "index": {"type": "object"},
                "level": {"type": "string"},
                "confidence": {"type": "number"},
                "data_sufficient": {"type": "boolean"},
                "sector_sentiment": {"type": "object"},
                "sources": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("get_sentiment_index",),
    ),
    CapabilityManifest(
        capability_key="sentiment.read.recent",
        title="Recent Sentiment Indices",
        summary="Read the canonical recent sentiment-index series.",
        description=(
            "Return recent sentiment index snapshots using the canonical days filter, "
            "with a stable indices-plus-total response envelope."
        ),
        owner_app="sentiment",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_sentiment_recent",
        tags=("sentiment", "index", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 30,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "indices": {"type": "array"},
                "total": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_sentiment_recent",),
    ),
    CapabilityManifest(
        capability_key="sentiment.read.health",
        title="Sentiment Service Health",
        summary="Read the canonical Sentiment service health contract.",
        description=(
            "Return service status, AI-provider availability, cache volume, and the "
            "latest sentiment-index date."
        ),
        owner_app="sentiment",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_sentiment_health",
        tags=("sentiment", "health", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "ai_provider_available": {"type": "boolean"},
                "cache_count": {"type": "integer"},
                "latest_index_date": {"type": ["string", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_sentiment_health",),
    ),
]
