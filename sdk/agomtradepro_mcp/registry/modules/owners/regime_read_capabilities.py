"""regime read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="system.read.regime.current",
        title="Current Regime Snapshot",
        summary="Read the current macro regime snapshot.",
        description="Return the current macro regime, confidence, and observation metadata.",
        owner_app="regime",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_current_regime",
        tags=("regime", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "dominant_regime": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_current_regime",),
    ),
    CapabilityManifest(
        capability_key="regime.read.history",
        title="Regime History",
        summary="Read historical regime snapshots for a time window.",
        description="Return historical macro regime observations for research and comparison.",
        owner_app="regime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_regime_history",
        tags=("regime", "macro", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "history": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_regime_history",),
    ),
    CapabilityManifest(
        capability_key="regime.read.navigator",
        title="Regime Navigator",
        summary="Read the canonical Regime Navigator output.",
        description=(
            "Return the current Regime quadrant, movement assessment, asset guidance, "
            "and watch indicators. The governed contract remains zero-parameter because "
            "the legacy raw tool and SDK do not expose the canonical API's optional "
            "as_of_date query."
        ),
        owner_app="regime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_regime_navigator",
        tags=("regime", "navigator", "allocation", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "regime_name": {"type": "string"},
                "confidence": {"type": "number"},
                "distribution": {"type": "object"},
                "generated_at": {"type": "string"},
                "data_freshness": {"type": "string"},
                "is_transitioning": {"type": "boolean"},
                "movement": {"type": "object"},
                "asset_guidance": {"type": "object"},
                "watch_indicators": {"type": "array", "items": {"type": "object"}},
            },
            "required": [
                "regime_name",
                "confidence",
                "movement",
                "asset_guidance",
                "watch_indicators",
            ],
        },
        legacy_tool_names=("get_regime_navigator",),
    ),
    CapabilityManifest(
        capability_key="regime.read.distribution",
        title="Regime Distribution",
        summary="Read canonical Regime occurrence counts for a date range.",
        description=(
            "Return the canonical Recovery, Overheat, Stagflation, and Deflation "
            "occurrence counts for the optional date range. Historical Repression "
            "labels are normalized to Deflation by the SDK compatibility layer."
        ),
        owner_app="regime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_regime_distribution",
        tags=("regime", "distribution", "history", "statistics", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": ["string", "null"], "format": "date"},
                "end_date": {"type": ["string", "null"], "format": "date"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "distribution": {
                    "type": "object",
                    "properties": {
                        "Recovery": {"type": "integer", "minimum": 0},
                        "Overheat": {"type": "integer", "minimum": 0},
                        "Stagflation": {"type": "integer", "minimum": 0},
                        "Deflation": {"type": "integer", "minimum": 0},
                    },
                    "required": [
                        "Recovery",
                        "Overheat",
                        "Stagflation",
                        "Deflation",
                    ],
                },
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["distribution", "total_count"],
        },
        legacy_tool_names=("get_regime_distribution",),
    ),
    CapabilityManifest(
        capability_key="regime.compute.calculate",
        title="Calculate Regime Snapshot",
        summary="Calculate a Regime snapshot from persisted macro facts.",
        description=(
            "Run the canonical pure Regime calculation for an optional date, "
            "Point-in-Time policy, indicators, and persisted data source. The "
            "contract intentionally excludes the legacy use_kalman argument because "
            "the canonical API never implemented it. This operation does not persist "
            "RegimeLog rows, sync providers, trigger tasks, or write shared caches."
        ),
        owner_app="regime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="calculate_regime",
        tags=("regime", "macro", "calculation", "pure_compute", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": ["string", "null"], "format": "date"},
                "use_pit": {"type": "boolean"},
                "growth_indicator": {"type": "string"},
                "inflation_indicator": {"type": "string"},
                "data_source": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "snapshot": {"type": ["object", "null"]},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "error": {"type": ["string", "null"]},
                "raw_data": {"type": ["object", "null"]},
                "intermediate_data": {"type": ["object", "null"]},
            },
            "required": ["success", "snapshot", "warnings", "error"],
        },
        legacy_tool_names=("calculate_regime",),
    ),
    CapabilityManifest(
        capability_key="regime.read.action_recommendation",
        title="Regime And Pulse Action Recommendation",
        summary="Read the current decision-safe Regime and Pulse action recommendation.",
        description=(
            "Return the current asset-weight, risk-budget, sector, style, hedge, confidence, "
            "and decision-safety contract from the canonical Regime GET endpoint. The read "
            "uses persisted inputs without refreshing Pulse data or writing recommendation logs."
        ),
        owner_app="regime",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="regime_read_action_recommendation",
        tags=("regime", "pulse", "action", "recommendation", "decision_safety", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_weights": {"type": "object"},
                "risk_budget_pct": {"type": "number"},
                "position_limit_pct": {"type": "number"},
                "recommended_sectors": {"type": "array"},
                "benefiting_styles": {"type": "array"},
                "hedge_recommendation": {"type": ["object", "string", "null"]},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
                "must_not_use_for_decision": {"type": "boolean"},
                "blocked_reason": {"type": "string"},
                "blocked_code": {"type": "string"},
                "pulse_is_reliable": {"type": "boolean"},
                "stale_indicator_codes": {"type": "array"},
                "contract": {"type": "object"},
            },
            "required": [
                "asset_weights",
                "risk_budget_pct",
                "position_limit_pct",
                "recommended_sectors",
                "benefiting_styles",
                "must_not_use_for_decision",
                "blocked_reason",
                "blocked_code",
                "pulse_is_reliable",
                "stale_indicator_codes",
                "contract",
            ],
        },
        audit_tags=("regime:action_recommendation", "mcp:decision_read"),
        legacy_tool_names=("get_action_recommendation",),
    ),
]
