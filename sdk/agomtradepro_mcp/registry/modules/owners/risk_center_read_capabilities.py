"""risk_center read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="risk_center.read.floor",
        title="Risk Center Floor",
        summary="Read the active global risk floor configuration.",
        description=(
            "Return the active global risk floor used by the centralized risk center, "
            "including position caps, cash floor, stop-loss settings, and audit metadata."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_risk_floor",
        tags=("risk_center", "floor", "config", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "max_total_position_pct": {"type": "number"},
                "max_single_position_pct": {"type": "number"},
                "min_cash_pct": {"type": "number"},
                "force_stop_loss": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("get_risk_floor",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.template_catalog",
        title="Risk Center Template Catalog",
        summary="Read the active risk template catalog.",
        description=(
            "Return the active risk template list used by the centralized risk center, "
            "including template keys, risk profiles, parameter caps, and activation state."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_risk_templates",
        tags=("risk_center", "template", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "templates": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_risk_templates",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.effective_policy",
        title="Risk Center Effective Policy",
        summary="Read the resolved effective risk policy for a specific account.",
        description=(
            "Return the effective account-level risk policy resolved by the centralized risk "
            "center, including final parameters, source attribution, floor overrides, and "
            "applied exceptions."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_effective_risk_policy",
        tags=("risk_center", "policy", "effective", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "template_key": {"type": "string"},
                "risk_profile": {"type": "string"},
                "parameters": {"type": "object"},
                "sources": {"type": "object"},
                "floor_applied": {"type": "array"},
                "exceptions_applied": {"type": "array"},
                "warnings": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("get_effective_risk_policy",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.account_policy",
        title="Risk Center Account Policy",
        summary="Read the stored account-level risk policy for a specific account.",
        description=(
            "Return the persisted account-level risk policy by account ID, including account "
            "overrides, selected template linkage, risk profile, activation state, and audit "
            "timestamps."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_account_risk_policy",
        tags=("risk_center", "policy", "account", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "template": {"type": ["integer", "null"]},
                "template_key": {"type": "string"},
                "template_name": {"type": "string"},
                "risk_profile": {"type": ["string", "null"]},
                "max_total_position_pct": {"type": ["number", "null"]},
                "max_single_position_pct": {"type": ["number", "null"]},
                "min_cash_pct": {"type": ["number", "null"]},
                "force_stop_loss": {"type": ["boolean", "null"]},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("get_account_risk_policy",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.exception_list",
        title="Risk Center Exception List",
        summary="Read the active risk exception list, optionally filtered by account.",
        description=(
            "Return the current risk exception list from the centralized risk center, "
            "including allowed override values, reasons, expiry times, and creator metadata."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_risk_exceptions",
        tags=("risk_center", "exception", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "exceptions": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_risk_exceptions",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.pre_trade_check",
        title="Risk Center Pre-Trade Check",
        summary="Preview whether a proposed trade would pass centralized risk checks.",
        description=(
            "Return the pre-trade risk evaluation for a proposed order, including violations, "
            "warnings, projected metrics, and the effective account policy used during evaluation."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="check_pre_trade_risk",
        tags=("risk_center", "pre_trade", "risk", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "quantity": {"type": "number"},
                "price": {"type": "number"},
                "account_equity": {"type": "number"},
                "total_position_value": {"type": "number"},
                "cash_balance": {"type": "number"},
                "current_symbol_position_value": {"type": "number"},
            },
            "required": [
                "account_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "account_equity",
                "total_position_value",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "violations": {"type": "array"},
                "warnings": {"type": "array"},
                "metrics": {"type": "object"},
                "effective_policy": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("check_pre_trade_risk",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.post_investment_check",
        title="Risk Center Post-Investment Check",
        summary="Read the post-investment risk evaluation for the current portfolio state.",
        description=(
            "Return the post-investment risk evaluation for an account, including breach status, "
            "portfolio metrics, position alerts, warnings, and the effective policy used during "
            "evaluation."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="check_post_investment_risk",
        tags=("risk_center", "post_investment", "risk", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "account_equity": {"type": "number"},
                "positions": {"type": "array"},
                "cash_balance": {"type": "number"},
                "total_position_value": {"type": "number"},
                "daily_pnl_pct": {"type": "number"},
                "drawdown_pct": {"type": "number"},
            },
            "required": ["account_id", "account_equity"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "passed": {"type": "boolean"},
                "violations": {"type": "array"},
                "warnings": {"type": "array"},
                "metrics": {"type": "object"},
                "position_alerts": {"type": "array"},
                "effective_policy": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("check_post_investment_risk",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.daily_report",
        title="Risk Center Daily Report",
        summary="Read a specific risk-center daily report for an account and report date.",
        description=(
            "Return the stored daily risk-center report for a specific account and report date, "
            "including risk summary, position summary, post-investment evaluation, and report "
            "metadata."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_risk_center_daily_report",
        tags=("risk_center", "daily_report", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
            },
            "required": ["account_id", "report_date"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
                "risk_daily_report": {"type": "object"},
                "position_daily_report": {"type": "object"},
                "post_investment_check": {"type": "object"},
                "notes": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_risk_center_daily_report",),
    ),
    CapabilityManifest(
        capability_key="risk_center.read.daily_report_history",
        title="Risk Center Daily Report History",
        summary="Read archived risk-center daily reports by account, single day, or date range.",
        description=(
            "Return archived risk-center daily reports for an account, optionally filtered by "
            "single report date or a date range, including risk summary, position summary, "
            "and stored post-investment evaluation payloads."
        ),
        owner_app="risk_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_risk_center_daily_reports",
        tags=("risk_center", "daily_report", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "null"]},
                "report_date": {"type": ["string", "null"]},
                "start_date": {"type": ["string", "null"]},
                "end_date": {"type": ["string", "null"]},
                "limit": {"type": ["integer", "null"]},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "reports": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_risk_center_daily_reports",),
    ),
]

_SCENARIO_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "scenario_key": {"type": "string"},
        "revision_id": {"type": "string"},
        "version": {"type": "integer"},
        "content_hash": {"type": "string"},
        "warnings": {"type": "array"},
        "blocked_reason": {"type": ["string", "null"]},
        "must_not_use_for_decision": {"type": "boolean"},
    },
    "required": [],
}

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="risk_center.stress_scenario.list",
            title="List governed stress scenarios",
            summary="List repository-backed scenario definitions and active revisions.",
            description=(
                "Return versioned stress scenarios from the Risk Center canonical repository; "
                "no Python scenario catalog fallback is used."
            ),
            owner_app="risk_center",
            risk_level="low",
            executor_kind="internal_handler",
            executor_ref="risk_center_stress_scenario_list",
            tags=("risk_center", "stress_scenario", "versioned", "read"),
            input_schema={
                "type": "object",
                "properties": {"include_inactive": {"type": "boolean"}},
                "required": [],
            },
            output_schema={
                "type": "object",
                "properties": {"scenarios": {"type": "array"}},
                "required": ["scenarios"],
            },
        ),
        CapabilityManifest(
            capability_key="risk_center.stress_scenario.read",
            title="Read governed stress scenario",
            summary="Read one scenario and its immutable revision history.",
            description="Return a scenario definition, revisions, evidence, and activation state.",
            owner_app="risk_center",
            risk_level="low",
            executor_kind="internal_handler",
            executor_ref="risk_center_stress_scenario_read",
            tags=("risk_center", "stress_scenario", "revision", "read"),
            input_schema={
                "type": "object",
                "properties": {"scenario_key": {"type": "string", "minLength": 1}},
                "required": ["scenario_key"],
            },
            output_schema=_SCENARIO_RESULT_SCHEMA,
        ),
        CapabilityManifest(
            capability_key="risk_center.stress_scenario.compare",
            title="Compare stress scenario revisions",
            summary="Compare two immutable revisions without writing state.",
            description="Return a stable field-level diff for two revisions of one scenario.",
            owner_app="risk_center",
            risk_level="low",
            executor_kind="internal_handler",
            executor_ref="risk_center_stress_scenario_compare",
            tags=("risk_center", "stress_scenario", "diff", "read"),
            input_schema={
                "type": "object",
                "properties": {
                    "scenario_key": {"type": "string", "minLength": 1},
                    "left_version": {"type": "integer", "minimum": 1},
                    "right_version": {"type": "integer", "minimum": 1},
                },
                "required": ["scenario_key", "left_version", "right_version"],
            },
            output_schema={
                "type": "object",
                "properties": {"diff": {"type": "object"}},
                "required": ["diff"],
            },
        ),
        CapabilityManifest(
            capability_key="risk_center.stress_scenario.validate_revision",
            title="Validate stress scenario revision",
            summary="Validate typed scenario assumptions without creating a revision.",
            description=(
                "Run canonical Risk Center schema and business validation with zero writes and "
                "reject unknown fields."
            ),
            owner_app="risk_center",
            risk_level="low",
            executor_kind="internal_handler",
            executor_ref="risk_center_stress_scenario_validate_revision",
            tags=("risk_center", "stress_scenario", "validate", "read"),
            input_schema={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
            },
            output_schema=_SCENARIO_RESULT_SCHEMA,
        ),
        CapabilityManifest(
            capability_key="risk_center.stress_scenario.preview_revision",
            title="Preview stress scenario revision",
            summary="Preview revision diff and portfolio impact with zero writes.",
            description=(
                "Return preview ID, request fingerprint, base and after hashes, expiry, warnings, "
                "and decision-use blocking state."
            ),
            owner_app="risk_center",
            risk_level="medium",
            executor_kind="internal_handler",
            executor_ref="risk_center_stress_scenario_preview_revision",
            tags=("risk_center", "stress_scenario", "preview", "read"),
            input_schema={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
            },
            output_schema=_SCENARIO_RESULT_SCHEMA,
        ),
    ]
)
