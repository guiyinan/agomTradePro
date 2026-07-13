"""factor read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="factor.compute.top_stocks",
        title="Factor Top Stocks",
        summary="Compute a factor-ranked stock list from persisted market facts.",
        description=(
            "Compute a bounded stock ranking from active factor definitions, persisted stock "
            "master data, and stored valuation, financial, and price facts. The calculation "
            "does not create holdings or write price-cache results."
        ),
        owner_app="factor",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="factor_compute_top_stocks",
        tags=("factor", "stock", "ranking", "score", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "value_preference": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "quality_preference": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "growth_preference": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "momentum_preference": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "top_n": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "total_stocks": {"type": "integer", "minimum": 0},
                "stocks": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["total_stocks", "stocks"],
        },
        legacy_tool_names=("get_factor_top_stocks",),
    ),
    CapabilityManifest(
        capability_key="factor.compute.stock_explanation",
        title="Factor Stock Explanation",
        summary="Compute a factor-score explanation for one stock.",
        description=(
            "Explain one stock using a stable named factor focus and persisted factor, "
            "stock, valuation, financial, and price facts. The calculation does not "
            "persist exposures or holdings and does not write successful price reads "
            "back to the process cache."
        ),
        owner_app="factor",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="factor_compute_stock_explanation",
        tags=("factor", "stock", "explanation", "score", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "minLength": 1},
                "focus": {
                    "type": "string",
                    "enum": ["value", "growth", "quality", "balanced"],
                },
            },
            "required": ["stock_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string"},
                "stock_name": {"type": "string"},
                "composite_score": {"type": "number"},
                "percentile_rank": {"type": "number"},
                "factor_breakdown": {"type": "object"},
                "category_breakdown": {"type": "object"},
            },
            "required": [
                "stock_code",
                "stock_name",
                "composite_score",
                "percentile_rank",
                "factor_breakdown",
                "category_breakdown",
            ],
        },
        legacy_tool_names=("explain_factor_stock",),
    ),
    CapabilityManifest(
        capability_key="factor.read.definition_catalog",
        title="Factor Definition Catalog",
        summary="Read the active factor-definition catalog.",
        description=(
            "Return active factor definitions from the canonical Factor GET endpoint, "
            "including a stable flat list and category projection without calculating scores."
        ),
        owner_app="factor",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="factor_read_definition_catalog",
        tags=("factor", "definition", "catalog", "active", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "factors": {"type": "array", "items": {"type": "object"}},
                "by_category": {"type": "object"},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["factors", "by_category", "total_count"],
        },
        legacy_tool_names=("list_factor_definitions",),
    ),
    CapabilityManifest(
        capability_key="factor.read.config_catalog",
        title="Factor Portfolio Configuration Catalog",
        summary="Read the factor portfolio-configuration catalog.",
        description=(
            "Return persisted factor portfolio configurations from the canonical Factor GET "
            "endpoint without generating holdings, calculating scores, or changing activation."
        ),
        owner_app="factor",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="factor_read_config_catalog",
        tags=("factor", "portfolio", "config", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "configs": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["configs", "total_count"],
        },
        legacy_tool_names=("list_factor_configs",),
    ),
]

MANIFESTS.append(
    CapabilityManifest(
        capability_key="factor.read.portfolio",
        title="Factor Portfolio Holdings",
        summary="Read the latest persisted holdings for one factor configuration.",
        description=(
            "Return latest persisted factor portfolio holdings without generating a new "
            "portfolio, recalculating scores, or importing Django infrastructure into SDK."
        ),
        owner_app="factor",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="factor_read_portfolio",
        tags=("factor", "portfolio", "holdings", "persisted", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "config_name": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "required": ["config_name"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "config_name": {"type": "string"},
                "exists": {"type": "boolean"},
                "portfolio": {"type": ["object", "null"]},
            },
            "required": ["config_name", "exists", "portfolio"],
        },
        legacy_tool_names=("get_factor_portfolio",),
    )
)
