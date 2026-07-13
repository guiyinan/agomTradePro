"""hedge read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="hedge.compute.correlation_matrix",
        title="Hedge Correlation Matrix",
        summary="Compute a correlation matrix from persisted or cached price history.",
        description=(
            "Run the canonical Hedge correlation-matrix calculation without persisting "
            "correlation history, generating alerts, refreshing market data, or writing "
            "successful price reads back to cache."
        ),
        owner_app="hedge",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="hedge_compute_correlation_matrix",
        tags=("hedge", "correlation", "matrix", "calculation"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 20,
                },
                "window_days": {"type": "integer", "minimum": 2, "maximum": 500},
            },
            "required": ["asset_codes"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_codes": {"type": "array"},
                "window_days": {"type": "integer"},
                "matrix": {"type": "object"},
            },
            "required": ["asset_codes", "window_days", "matrix"],
        },
        legacy_tool_names=(
            "get_hedge_correlation_matrix",
            "get_correlation_matrix",
        ),
    ),
    CapabilityManifest(
        capability_key="hedge.read.pair_catalog",
        title="Hedge Pair Catalog",
        summary="Read the configured hedge-pair catalog.",
        description=(
            "Return the persisted hedge-pair definitions available to authenticated "
            "users through the canonical Hedge API."
        ),
        owner_app="hedge",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="hedge_read_pair_catalog",
        tags=("hedge", "pair", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "pairs": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": ["pairs", "total_count"],
        },
        legacy_tool_names=("list_hedge_pairs",),
    ),
    CapabilityManifest(
        capability_key="hedge.read.pair_detail",
        title="Hedge Pair Detail",
        summary="Read one configured hedge pair by name.",
        description=(
            "Return one hedge-pair definition selected from the canonical persisted pair catalog."
        ),
        owner_app="hedge",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="hedge_read_pair_detail",
        tags=("hedge", "pair", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string"},
            },
            "required": ["pair_name"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string"},
                "pair": {"type": "object"},
            },
            "required": ["pair_name", "pair"],
        },
        legacy_tool_names=("get_hedge_pair_info",),
    ),
    CapabilityManifest(
        capability_key="hedge.read.alert_list",
        title="Active Hedge Alerts",
        summary="Read active hedge alerts from the canonical Hedge API.",
        description=(
            "Return unresolved hedge alerts using the SDK's established default "
            "lookback window and a stable list envelope."
        ),
        owner_app="hedge",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="hedge_read_alert_list",
        tags=("hedge", "alert", "active", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "alerts": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["alerts", "total_count", "query"],
        },
        legacy_tool_names=("get_hedge_alerts",),
    ),
    CapabilityManifest(
        capability_key="hedge.read.portfolio_state",
        title="Hedge Portfolio State",
        summary="Read the latest persisted portfolio state for one hedge pair.",
        description=(
            "Return the latest persisted hedge snapshot matching the requested pair "
            "name without triggering portfolio refresh."
        ),
        owner_app="hedge",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="hedge_read_portfolio_state",
        tags=("hedge", "portfolio", "snapshot", "state", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string"},
            },
            "required": ["pair_name"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string"},
                "state": {"type": "object"},
            },
            "required": ["pair_name", "state"],
        },
        legacy_tool_names=("get_hedge_portfolio_state",),
    ),
    CapabilityManifest(
        capability_key="hedge.compute.effectiveness",
        title="Compute Hedge Effectiveness",
        summary="Evaluate one configured hedge pair without persisting calculation results.",
        description=(
            "Resolve one persisted hedge pair through the canonical SDK, calculate its current "
            "correlation, beta, ratio, rating, and recommendation from existing price history, "
            "and prohibit price-cache writes, snapshots, alerts, and performance persistence."
        ),
        owner_app="hedge",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="hedge_compute_effectiveness",
        tags=("hedge", "effectiveness", "calculation", "recommendation"),
        input_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "required": ["pair_name"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "pair_name": {"type": "string"},
                "correlation": {"type": "number"},
                "beta": {"type": "number"},
                "hedge_ratio": {"type": "number"},
                "hedge_method": {"type": "string"},
                "effectiveness": {"type": "number"},
                "is_effective": {"type": "boolean"},
                "rating": {"type": "string"},
                "recommendation": {"type": "string"},
            },
            "required": [
                "pair_name",
                "effectiveness",
                "is_effective",
                "rating",
                "recommendation",
            ],
        },
        audit_tags=("hedge:effectiveness", "mcp:compute"),
        legacy_tool_names=(
            "check_hedge_effectiveness",
            "is_my_hedge_still_working",
        ),
    ),
]
