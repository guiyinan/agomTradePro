"""filter read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest
from agomtradepro_mcp.registry.modules.owners.filter_lifecycle import FILTER_LIFECYCLE

MANIFESTS = [
    CapabilityManifest(
        capability_key="filter.read.indicator_catalog",
        title="Filter Indicator Catalog",
        summary="Read the available filter indicator catalog.",
        description=(
            "Return the available indicator list exposed by the filter service, "
            "including indicator codes, names, and categories."
        ),
        owner_app="filter",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_filters",
        tags=("filter", "indicator", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "filters": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_filters",),
        **FILTER_LIFECYCLE,
    ),
    CapabilityManifest(
        capability_key="filter.read.config_detail",
        title="Filter Config Detail",
        summary="Read a single filter config detail.",
        description=(
            "Return one filter config entry resolved by indicator code or legacy filter id, "
            "including filter parameters and indicator metadata."
        ),
        owner_app="filter",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_filter",
        tags=("filter", "config", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "filter_id": {"type": "integer"},
                "indicator_code": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "hp_enabled": {"type": "boolean"},
                "hp_lambda": {"type": "number"},
                "kalman_enabled": {"type": "boolean"},
                "kalman_level_variance": {"type": "number"},
                "kalman_slope_variance": {"type": "number"},
                "kalman_observation_variance": {"type": "number"},
                "success": {"type": "boolean"},
                "error": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_filter",),
        **FILTER_LIFECYCLE,
    ),
    CapabilityManifest(
        capability_key="filter.read.health",
        title="Filter Service Health",
        summary="Read the Filter service health contract.",
        description=(
            "Return Filter service availability and the filter implementations exposed "
            "by the canonical health endpoint."
        ),
        owner_app="filter",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_filter_health",
        tags=("filter", "health", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "service": {"type": "string"},
                "filters_available": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("get_filter_health",),
        **FILTER_LIFECYCLE,
    ),
]
