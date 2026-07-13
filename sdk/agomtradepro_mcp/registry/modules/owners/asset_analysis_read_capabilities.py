"""asset_analysis read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="asset_analysis.read.weight_config_catalog",
        title="Asset Analysis Weight Config Catalog",
        summary="Read the configured asset-analysis scoring weights.",
        description=(
            "Return the persisted multi-dimensional scoring weight configurations and "
            "the active configuration name without triggering screening or refresh."
        ),
        owner_app="asset_analysis",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="asset_analysis_read_weight_config_catalog",
        tags=("asset_analysis", "weight", "config", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "configs": {"type": "object"},
                "active": {"type": ["string", "null"]},
                "total_count": {"type": "integer"},
            },
            "required": ["configs", "active", "total_count"],
        },
        legacy_tool_names=("get_asset_weight_configs",),
    ),
    CapabilityManifest(
        capability_key="asset_analysis.read.current_weight",
        title="Asset Analysis Current Weight",
        summary="Read the currently effective asset-analysis scoring weights.",
        description=(
            "Return the currently effective default scoring weights through the "
            "canonical Asset Analysis API without persisting a fallback configuration."
        ),
        owner_app="asset_analysis",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="asset_analysis_read_current_weight",
        tags=("asset_analysis", "weight", "current", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "weights": {"type": "object"},
                "asset_type": {"type": ["string", "null"]},
                "market_condition": {"type": ["string", "null"]},
            },
            "required": ["success", "weights", "asset_type", "market_condition"],
        },
        legacy_tool_names=("get_asset_current_weight",),
    ),
    CapabilityManifest(
        capability_key="asset_analysis.read.pool_summary",
        title="Asset Analysis Pool Summary",
        summary="Read persisted asset-pool counts.",
        description=(
            "Return active persisted asset-pool counts, optionally scoped to one asset "
            "type, without running asset screening or changing pool membership."
        ),
        owner_app="asset_analysis",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="asset_analysis_read_pool_summary",
        tags=("asset_analysis", "pool", "summary", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_type": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "asset_type": {"type": "string"},
                "summary": {"type": "object"},
            },
            "required": ["success", "asset_type", "summary"],
        },
        legacy_tool_names=("asset_pool_summary",),
    ),
    CapabilityManifest(
        capability_key="asset_analysis.compute.multidim_screen",
        title="Asset Multi-Dimensional Screen",
        summary="Calculate a multi-dimensional asset screen from bounded inputs.",
        description=(
            "Execute the canonical scoring use case over persisted inputs. The operation "
            "does not synchronize providers, enqueue work, or persist screen results."
        ),
        owner_app="asset_analysis",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="asset_analysis_compute_multidim_screen",
        tags=("asset_analysis", "screen", "score", "research", "compute"),
        input_schema={
            "type": "object",
            "properties": {"payload": {"type": "object"}},
            "required": ["payload"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "results": {"type": "array"},
            },
            "required": [],
        },
        audit_tags=("asset_analysis:multidim_screen", "mcp:research_read"),
        legacy_tool_names=("asset_multidim_screen",),
    ),
    CapabilityManifest(
        capability_key="asset_analysis.compute.pool_screen",
        title="Asset Pool Screen",
        summary="Classify scored equity or fund assets into an in-memory pool result.",
        description=(
            "Read the canonical scoring context and calculate pool classifications in "
            "memory without changing persisted pool membership or refreshing providers."
        ),
        owner_app="asset_analysis",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="asset_analysis_compute_pool_screen",
        tags=("asset_analysis", "pool", "screen", "research", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_type": {"type": "string", "enum": ["equity", "fund"]},
                "payload": {"type": ["object", "null"]},
            },
            "required": ["asset_type"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "asset_type": {"type": "string"},
                "pools_summary": {"type": "object"},
                "assets": {"type": "array"},
            },
            "required": [],
        },
        audit_tags=("asset_analysis:pool_screen", "mcp:research_read"),
        legacy_tool_names=("asset_pool_screen",),
    ),
]
