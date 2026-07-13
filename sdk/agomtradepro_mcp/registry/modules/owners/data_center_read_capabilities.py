"""data_center read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="data_center.read.provider_status",
        title="Data Center Provider Status",
        summary="Read provider health and status across the data center.",
        description="Return the current provider health snapshot for the AgomTradePro data center.",
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_data_center_provider_status",
        tags=("data_center", "operations", "read"),
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
        legacy_tool_names=("get_data_center_provider_status",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.provider_catalog",
        title="Data Center Provider Catalog",
        summary="Read the data-center provider catalog list.",
        description=(
            "Return the configured data-center provider catalog used by operator workflows, "
            "including source type, activation state, priority, and endpoint metadata."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_data_center_providers",
        tags=("data_center", "provider", "catalog", "read"),
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
        legacy_tool_names=("list_data_center_providers",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.macro_series",
        title="Data Center Macro Series",
        summary="Read one normalized macro time series from the data center.",
        description=(
            "Return one standardized macro indicator series, including provenance metadata "
            "used for research and decision-readiness checks."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_macro_series",
        tags=("data_center", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "observations": {"type": "array"},
                "provenance_class": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_macro_series",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.indicator_catalog",
        title="Data Center Indicator Catalog",
        summary="Read the normalized data-center indicator catalog.",
        description="Return indicator catalog metadata and unit-rule summaries from the data center.",
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_list_indicators",
        tags=("data_center", "catalog", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "indicators": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_list_indicators",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.price_history",
        title="Data Center Price History",
        summary="Read normalized historical price bars for one asset.",
        description=(
            "Return canonical data-center price history for one asset, including normalized "
            "bar data and the resolved asset code."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_price_history",
        tags=("data_center", "market_data", "price", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "start": {"type": ["string", "null"]},
                "end": {"type": ["string", "null"]},
                "freq": {"type": ["string", "null"]},
                "adjustment": {"type": ["string", "null"]},
                "limit": {"type": ["integer", "null"], "minimum": 1},
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "total": {"type": "integer"},
                "data": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=(
            "data_center_get_price_history",
            "get_price_history",
        ),
    ),
    CapabilityManifest(
        capability_key="data_center.read.latest_quote",
        title="Data Center Latest Quote",
        summary="Read the latest canonical quote snapshot for one asset.",
        description=(
            "Return the latest quote snapshot with freshness, decision-safety, provenance, "
            "and blocking metadata from the data center."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_quotes",
        tags=("data_center", "market_data", "quote", "freshness", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "strict_freshness": {"type": ["boolean", "null"]},
                "max_age_hours": {
                    "type": ["number", "null"],
                    "exclusiveMinimum": 0,
                },
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "snapshot_at": {"type": "string"},
                "current_price": {"type": "number"},
                "open": {"type": ["number", "null"]},
                "high": {"type": ["number", "null"]},
                "low": {"type": ["number", "null"]},
                "prev_close": {"type": ["number", "null"]},
                "volume": {"type": ["number", "null"]},
                "source": {"type": "string"},
                "freshness_status": {"type": "string"},
                "must_not_use_for_decision": {"type": "boolean"},
                "blocked_reason": {"type": "string"},
                "contract": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_quotes",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.news",
        title="Data Center Asset News",
        summary="Read recent normalized news facts for one asset.",
        description=(
            "Return recent normalized news facts for one asset from the canonical data-center "
            "news endpoint."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_news",
        tags=("data_center", "news", "asset", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "total": {"type": "integer"},
                "data": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_news",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.capital_flows",
        title="Data Center Capital Flows",
        summary="Read persisted capital-flow facts for one asset.",
        description=(
            "Return a bounded date range of persisted capital-flow facts from the "
            "canonical data-center read endpoint. This capability does not fetch from "
            "providers, synchronize data, update facts, or start background tasks."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_capital_flows",
        tags=("data_center", "capital_flow", "asset", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string", "minLength": 1, "maxLength": 20},
                "start": {"type": ["string", "null"], "format": "date"},
                "end": {"type": ["string", "null"], "format": "date"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["asset_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "query": {
                    "type": "object",
                    "properties": {
                        "start": {"type": ["string", "null"], "format": "date"},
                        "end": {"type": ["string", "null"], "format": "date"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "required": ["start", "end", "limit"],
                },
                "total": {"type": "integer", "minimum": 0},
                "data": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["asset_code", "query", "total", "data"],
        },
        legacy_tool_names=("data_center_get_capital_flows",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.publisher_detail",
        title="Data Center Publisher Detail",
        summary="Read one provenance publisher definition.",
        description=(
            "Return one canonical publisher definition used by data-center provenance "
            "and source-governance contracts."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_publisher",
        tags=("data_center", "publisher", "provenance", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "publisher_code": {"type": "string"},
            },
            "required": ["publisher_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name": {"type": "string"},
                "publisher_type": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_publisher",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.publisher_catalog",
        title="Data Center Publisher Catalog",
        summary="Read the canonical provenance publisher catalog.",
        description=(
            "Return the configured publisher catalog used by data-center provenance and "
            "source-governance contracts."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_list_publishers",
        tags=("data_center", "publisher", "provenance", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "publishers": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_list_publishers",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.indicator_detail",
        title="Data Center Indicator Detail",
        summary="Read one canonical indicator catalog definition.",
        description=(
            "Return one indicator definition, including naming, category, period, activation, "
            "and governance metadata."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_indicator",
        tags=("data_center", "indicator", "catalog", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name_cn": {"type": "string"},
                "name_en": {"type": "string"},
                "category": {"type": "string"},
                "default_period_type": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_indicator",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.indicator_unit_rules",
        title="Data Center Indicator Unit Rules",
        summary="Read the unit-normalization rules for one indicator.",
        description=(
            "Return the canonical unit and dimension normalization rules configured for one "
            "indicator."
        ),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_list_indicator_unit_rules",
        tags=("data_center", "indicator", "unit", "rules", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rules": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_list_indicator_unit_rules",),
    ),
    CapabilityManifest(
        capability_key="data_center.read.indicator_unit_rule_detail",
        title="Data Center Indicator Unit Rule Detail",
        summary="Read one unit-normalization rule for an indicator.",
        description=("Return one canonical indicator unit rule by indicator code and rule ID."),
        owner_app="data_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="data_center_get_indicator_unit_rule",
        tags=("data_center", "indicator", "unit", "rule", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
            },
            "required": ["indicator_code", "rule_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "indicator_code": {"type": "string"},
                "dimension_key": {"type": "string"},
                "storage_unit": {"type": "string"},
                "display_unit": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("data_center_get_indicator_unit_rule",),
    ),
]
