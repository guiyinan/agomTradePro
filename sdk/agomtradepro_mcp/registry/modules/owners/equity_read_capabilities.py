"""equity read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="equity.read.pool_catalog",
        title="Equity Stock Pool Catalog",
        summary="Read the current persisted equity stock-pool snapshot.",
        description=(
            "Return the authenticated canonical equity pool with optional SDK-side "
            "sector and minimum-score filtering. The read path does not refresh the "
            "pool, hydrate market data, persist Regime calculations, or write caches. "
            "The Sector stock-list compatibility tool is the same semantic task; its "
            "legacy order_by hint is not published because the canonical API does not "
            "implement market-cap or change sorting."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_pool_catalog",
        tags=("equity", "stock", "pool", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "sector": {"type": "string"},
                "min_score": {"type": "number"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "regime": {"type": "string"},
                "update_time": {"type": ["string", "null"]},
                "avg_roe": {"type": ["number", "null"]},
                "avg_pe": {"type": ["number", "null"]},
                "stocks": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": [
                "success",
                "regime",
                "update_time",
                "avg_roe",
                "avg_pe",
                "stocks",
                "total_count",
                "query",
            ],
        },
        legacy_tool_names=("list_stocks", "get_sector_stocks"),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_analysis",
        title="Equity Valuation Analysis",
        summary="Read persisted valuation analysis for one equity.",
        description=(
            "Return canonical stock identity, valuation percentiles, the latest persisted "
            "valuation snapshot, and latest persisted financial context. Cache misses do "
            "not hydrate providers, backfill asset names, or write local mirror tables."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_analysis",
        tags=("equity", "valuation", "financial", "analysis", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "minLength": 1, "maxLength": 20},
                "lookback_days": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 1260,
                },
            },
            "required": ["stock_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "stock_code": {"type": "string"},
                "stock_name": {"type": "string"},
                "sector": {"type": "string"},
                "market": {"type": "string"},
                "list_date": {"type": ["string", "null"]},
                "current_pe": {"type": "number"},
                "pe_percentile": {"type": "number"},
                "current_pb": {"type": "number"},
                "pb_percentile": {"type": "number"},
                "is_undervalued": {"type": "boolean"},
                "latest_valuation": {"type": ["object", "null"]},
                "financial_data": {"type": ["object", "null"]},
                "error": {"type": ["string", "null"]},
            },
            "required": [
                "success",
                "stock_code",
                "stock_name",
                "sector",
                "market",
                "list_date",
                "current_pe",
                "pe_percentile",
                "current_pb",
                "pb_percentile",
                "is_undervalued",
                "latest_valuation",
                "financial_data",
            ],
        },
        legacy_tool_names=("get_stock_valuation",),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_repair_list",
        title="Equity Valuation Repair Snapshot List",
        summary="Read persisted equity valuation-repair snapshots.",
        description=(
            "Return active persisted valuation-repair snapshots for one source "
            "universe without triggering real-time recalculation or snapshot writes."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_repair_list",
        tags=("equity", "valuation", "repair", "snapshot", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "universe": {"type": "string"},
                "phase": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "universe": {"type": "string"},
                "repairs": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["universe", "repairs", "total_count", "query"],
        },
        legacy_tool_names=("list_valuation_repairs",),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_freshness",
        title="Equity Valuation Data Freshness",
        summary="Read the freshness state of persisted equity valuation data.",
        description=(
            "Return the latest local valuation date, lag and quality-gate context "
            "without syncing providers or creating a quality snapshot."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_freshness",
        tags=("equity", "valuation", "freshness", "quality", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "latest_trade_date": {"type": "string"},
                "lag_days": {"type": "integer"},
                "freshness_status": {"type": "string"},
                "coverage_ratio": {"type": ["number", "null"]},
                "is_gate_passed": {"type": ["boolean", "null"]},
            },
            "required": [
                "latest_trade_date",
                "lag_days",
                "freshness_status",
                "coverage_ratio",
                "is_gate_passed",
            ],
        },
        legacy_tool_names=("get_valuation_data_freshness",),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_quality_latest",
        title="Latest Equity Valuation Quality Snapshot",
        summary="Read the latest persisted equity valuation quality snapshot.",
        description=(
            "Return the latest persisted valuation quality and gate evidence without "
            "running validation or updating the snapshot."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_quality_latest",
        tags=("equity", "valuation", "quality", "snapshot", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": "string"},
                "coverage_ratio": {"type": "number"},
                "valid_ratio": {"type": "number"},
                "primary_source": {"type": "string"},
                "is_gate_passed": {"type": "boolean"},
            },
            "required": [
                "as_of_date",
                "coverage_ratio",
                "valid_ratio",
                "primary_source",
                "is_gate_passed",
            ],
        },
        legacy_tool_names=("get_valuation_data_quality_latest",),
    ),
    CapabilityManifest(
        capability_key="equity.compute.valuation_repair_status",
        title="Equity Valuation Repair Status",
        summary="Calculate the current valuation-repair status for one stock.",
        description=(
            "Calculate the current valuation-repair phase, progress, speed, target ETA and "
            "quality provenance from persisted stock and valuation facts. Runtime configuration "
            "is loaded without cache writes; the calculation does not save repair snapshots, "
            "quality snapshots, stock data, cache state, or background tasks."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_compute_valuation_repair_status",
        tags=("equity", "valuation", "repair", "status", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "minLength": 1},
                "lookback_days": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 2520,
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
                "as_of_date": {"type": "string"},
                "phase": {"type": "string"},
                "signal": {"type": "string"},
                "composite_percentile": {"type": "number"},
                "repair_progress": {"type": ["number", "null"]},
                "repair_speed_per_30d": {"type": ["number", "null"]},
                "estimated_days_to_target": {"type": ["integer", "null"]},
                "is_stalled": {"type": "boolean"},
                "confidence": {"type": "number"},
                "data_quality_flag": {"type": ["string", "null"]},
                "data_source_provider": {"type": "string"},
                "data_as_of_date": {"type": "string"},
            },
            "required": [
                "stock_code",
                "stock_name",
                "as_of_date",
                "phase",
                "signal",
                "composite_percentile",
                "repair_progress",
                "repair_speed_per_30d",
                "estimated_days_to_target",
                "is_stalled",
                "confidence",
                "data_source_provider",
                "data_as_of_date",
            ],
        },
        legacy_tool_names=("get_valuation_repair_status",),
    ),
    CapabilityManifest(
        capability_key="equity.compute.valuation_repair_history",
        title="Equity Valuation Repair History",
        summary="Calculate the valuation-percentile history for one stock.",
        description=(
            "Calculate a bounded historical valuation-percentile series from persisted local "
            "valuation facts and return canonical quality provenance. Runtime configuration is "
            "loaded without cache writes; the calculation does not save repair snapshots, "
            "quality snapshots, stock data, cache state, or background tasks."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_compute_valuation_repair_history",
        tags=("equity", "valuation", "repair", "history", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "minLength": 1},
                "lookback_days": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 2520,
                },
            },
            "required": ["stock_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string"},
                "points": {"type": "array", "items": {"type": "object"}},
                "data_quality_flag": {"type": ["string", "null"]},
                "data_source_provider": {"type": "string"},
                "data_as_of_date": {"type": ["string", "null"]},
            },
            "required": [
                "stock_code",
                "points",
                "data_quality_flag",
                "data_source_provider",
                "data_as_of_date",
            ],
        },
        legacy_tool_names=("get_valuation_repair_history",),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_repair_config",
        title="Active Equity Valuation Repair Configuration",
        summary="Read the effective staff-only valuation-repair configuration.",
        description=(
            "Return the active persisted valuation-repair configuration, or an unpersisted "
            "settings/default projection when no active row exists. The read bypasses runtime "
            "cache writes and does not create a default configuration."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_repair_config",
        tags=("equity", "valuation", "repair", "configuration", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"config": {"type": "object"}},
            "required": ["config"],
        },
        required_roles=("staff",),
        legacy_tool_names=("get_valuation_repair_config",),
    ),
    CapabilityManifest(
        capability_key="equity.read.valuation_repair_config_catalog",
        title="Equity Valuation Repair Configuration Catalog",
        summary="Read persisted valuation-repair configuration versions.",
        description=(
            "Return a bounded staff-only catalog of persisted valuation-repair configuration "
            "versions without creating, updating, activating, rolling back, or deleting rows."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_valuation_repair_config_catalog",
        tags=("equity", "valuation", "repair", "configuration", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
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
        required_roles=("staff",),
        legacy_tool_names=("list_valuation_repair_configs",),
    ),
]

MANIFESTS.append(
    CapabilityManifest(
        capability_key="equity.read.financial_history",
        title="Equity Financial History",
        summary="Read persisted financial statements for one stock.",
        description=(
            "Return a bounded annual, quarterly, or complete financial history from "
            "persisted Equity and Data Center facts without on-demand hydration."
        ),
        owner_app="equity",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="equity_read_financial_history",
        tags=("equity", "financials", "history", "persisted", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string", "minLength": 1, "maxLength": 32},
                "report_type": {
                    "type": "string",
                    "enum": ["annual", "quarterly", "all"],
                    "default": "annual",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 40},
            },
            "required": ["stock_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "stock_code": {"type": "string"},
                "report_type": {"type": "string"},
                "financials": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["stock_code", "report_type", "financials", "total_count"],
        },
        legacy_tool_names=("get_stock_financials",),
    )
)

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="equity.read.score",
            title="Equity Score",
            summary="Read the current canonical score projection for one stock.",
            description=(
                "Read persisted stock detail and expose its score with an optional "
                "as-of label; no provider synchronization or snapshot write occurs."
            ),
            owner_app="equity",
            risk_level="low",
            executor_kind="legacy_tool",
            executor_ref="equity_read_score",
            tags=("equity", "stock", "score", "research", "read"),
            input_schema={
                "type": "object",
                "properties": {
                    "stock_code": {"type": "string", "minLength": 1, "maxLength": 32},
                    "as_of_date": {"type": ["string", "null"], "format": "date"},
                },
                "required": ["stock_code"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            legacy_tool_names=("get_stock_score",),
        ),
        CapabilityManifest(
            capability_key="equity.compute.recommendations",
            title="Equity Recommendations",
            summary="Calculate a bounded stock recommendation projection.",
            description=(
                "Apply the canonical persisted stock screen for an optional Regime and "
                "return normalized recommendation rows without persisting a new ranking."
            ),
            owner_app="equity",
            risk_level="medium",
            executor_kind="legacy_tool",
            executor_ref="equity_compute_recommendations",
            tags=("equity", "stock", "recommendation", "screen", "compute"),
            input_schema={
                "type": "object",
                "properties": {
                    "regime": {"type": ["string", "null"], "maxLength": 32},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "recommendations": {"type": "array"},
                    "total_count": {"type": "integer"},
                },
                "required": ["recommendations", "total_count"],
            },
            audit_tags=("equity:recommendations", "mcp:research_read"),
            legacy_tool_names=("get_stock_recommendations",),
        ),
        CapabilityManifest(
            capability_key="equity.compute.analysis",
            title="Equity Analysis",
            summary="Compose persisted stock detail and valuation evidence.",
            description=(
                "Compose the canonical stock detail and valuation reads for one code "
                "without provider synchronization, cache mutation, or snapshot creation."
            ),
            owner_app="equity",
            risk_level="medium",
            executor_kind="legacy_tool",
            executor_ref="equity_compute_analysis",
            tags=("equity", "stock", "valuation", "analysis", "compute"),
            input_schema={
                "type": "object",
                "properties": {
                    "stock_code": {"type": "string", "minLength": 1, "maxLength": 32},
                    "as_of_date": {"type": ["string", "null"], "format": "date"},
                },
                "required": ["stock_code"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            audit_tags=("equity:analysis", "mcp:research_read"),
            legacy_tool_names=("analyze_stock",),
        ),
    ]
)
