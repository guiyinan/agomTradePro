"""Governed read capabilities for persisted Sector ranking data."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="sector.read.rotation_ranking",
        title="Sector Rotation Ranking",
        summary="Read a persisted sector rotation ranking.",
        description=(
            "Rank persisted sector index facts for one regime and sector level. "
            "The canonical GET does not synchronize providers, mutate sector data, "
            "write market-data caches, or enqueue background work."
        ),
        owner_app="sector",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="sector_read_rotation_ranking",
        tags=("sector", "rotation", "ranking", "persisted", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "regime": {"type": ["string", "null"], "maxLength": 20},
                "lookback_days": {"type": "integer", "minimum": 5, "maximum": 120},
                "level": {"type": "string", "enum": ["SW1", "SW2", "SW3"]},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "regime": {"type": ["string", "null"]},
                "analysis_date": {"type": "string"},
                "top_sectors": {"type": "array", "items": {"type": "object"}},
                "status": {"type": "string"},
                "data_source": {"type": "string"},
                "warning_message": {"type": ["string", "null"]},
                "warning_detail": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
            },
            "required": [
                "success",
                "regime",
                "analysis_date",
                "top_sectors",
                "status",
                "data_source",
            ],
        },
        legacy_tool_names=(
            "list_sectors",
            "get_sector_recommendations",
            "get_hot_sectors",
        ),
    ),
]

MANIFESTS.append(
    CapabilityManifest(
        capability_key="sector.read.score",
        title="Sector Score",
        summary="Read the current persisted rotation score for one sector.",
        description=(
            "Resolve one sector from the canonical persisted rotation calculation without "
            "provider synchronization, cache writes, or background work."
        ),
        owner_app="sector",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="sector_read_score",
        tags=("sector", "score", "rotation", "persisted", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "sector_name": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "required": ["sector_name"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"score": {"type": "object"}},
            "required": ["score"],
        },
        legacy_tool_names=("get_sector_score",),
    )
)
