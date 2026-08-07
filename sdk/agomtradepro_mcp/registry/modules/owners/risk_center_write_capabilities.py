"""risk_center write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="risk_center.create.exception",
        title="Create Risk Exception",
        summary="Preview existing scoped exceptions, then confirm staff-only exception creation.",
        description=(
            "Validate the canonical risk-exception payload and read existing exceptions for the "
            "same account scope through the formal Risk Center SDK, then require explicit "
            "confirmation before creating the persisted exception."
        ),
        owner_app="risk_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="risk_center_create_exception",
        tags=("risk_center", "exception", "override", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "null"], "minimum": 1},
                "field_name": {
                    "type": "string",
                    "enum": [
                        "max_total_position_pct",
                        "max_single_position_pct",
                        "max_daily_loss_pct",
                        "max_drawdown_pct",
                        "max_stop_loss_pct",
                        "take_profit_pct",
                        "min_cash_pct",
                        "force_stop_loss",
                        "hard_exclusions",
                    ],
                },
                "allowed_value": {},
                "reason": {"type": "string"},
                "expires_at": {"type": "string", "format": "date-time"},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["field_name", "allowed_value", "reason", "expires_at"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "account_id": {"type": ["integer", "null"]},
                "field_name": {"type": "string"},
                "allowed_value": {},
                "reason": {"type": "string"},
                "expires_at": {"type": "string"},
                "is_active": {"type": "boolean"},
                "created_by": {"type": "integer"},
                "created_by_username": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("risk_center:create_exception", "mcp:write"),
        legacy_tool_names=("create_risk_exception",),
    ),
    CapabilityManifest(
        capability_key="risk_center.update.floor",
        title="Update Global Risk Floor",
        summary="Preview global risk-floor changes, then confirm the staff-only update.",
        description=(
            "Read the active global risk floor through the formal Risk Center SDK, validate and "
            "summarize the requested parameter changes without mutation, then require explicit "
            "confirmation before updating the persisted floor."
        ),
        owner_app="risk_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="risk_center_update_floor",
        tags=("risk_center", "floor", "configuration", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 100},
                "max_total_position_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_single_position_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_daily_loss_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_drawdown_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_stop_loss_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "take_profit_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "min_cash_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "force_stop_loss": {"type": "boolean"},
                "hard_exclusions": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 64},
                },
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "max_total_position_pct": {"type": ["number", "null"]},
                "max_single_position_pct": {"type": ["number", "null"]},
                "max_daily_loss_pct": {"type": ["number", "null"]},
                "max_drawdown_pct": {"type": ["number", "null"]},
                "max_stop_loss_pct": {"type": ["number", "null"]},
                "take_profit_pct": {"type": ["number", "null"]},
                "min_cash_pct": {"type": ["number", "null"]},
                "force_stop_loss": {"type": ["boolean", "null"]},
                "hard_exclusions": {"type": "array"},
                "is_active": {"type": "boolean"},
                "updated_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("risk_center:update_floor", "mcp:write"),
        legacy_tool_names=("update_risk_floor",),
    ),
    CapabilityManifest(
        capability_key="risk_center.update.account_policy",
        title="Update Account Risk Policy",
        summary="Preview an account policy create or update, then confirm the owner-scoped write.",
        description=(
            "Read the caller-visible account policy catalog and optional risk template through "
            "the formal Risk Center SDK, summarize whether the operation creates or updates the "
            "account policy, then require explicit confirmation before the canonical upsert."
        ),
        owner_app="risk_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="risk_center_update_account_policy",
        tags=("risk_center", "account", "policy", "configuration", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
                "template_id": {"type": "integer", "minimum": 1},
                "risk_profile": {
                    "type": "string",
                    "enum": ["conservative", "moderate", "aggressive", "custom"],
                },
                "max_total_position_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_single_position_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_daily_loss_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_drawdown_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "max_stop_loss_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "take_profit_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "min_cash_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "force_stop_loss": {"type": "boolean"},
                "hard_exclusions": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 64},
                },
                "is_active": {"type": "boolean"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "account_id": {"type": "integer"},
                "template": {"type": ["integer", "null"]},
                "template_key": {"type": "string"},
                "template_name": {"type": "string"},
                "risk_profile": {"type": ["string", "null"]},
                "max_total_position_pct": {"type": ["number", "null"]},
                "max_single_position_pct": {"type": ["number", "null"]},
                "max_daily_loss_pct": {"type": ["number", "null"]},
                "max_drawdown_pct": {"type": ["number", "null"]},
                "max_stop_loss_pct": {"type": ["number", "null"]},
                "take_profit_pct": {"type": ["number", "null"]},
                "min_cash_pct": {"type": ["number", "null"]},
                "force_stop_loss": {"type": ["boolean", "null"]},
                "hard_exclusions": {"type": "array"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("risk_center:update_account_policy", "mcp:write"),
        legacy_tool_names=("upsert_account_risk_policy",),
    ),
    CapabilityManifest(
        capability_key="risk_center.generate.daily_report",
        title="Generate Risk Center Daily Report",
        summary="Preview the risk evaluation and overwrite target, then confirm report generation.",
        description=(
            "Run the canonical post-investment check and inspect the selected account/date report "
            "slot through the formal Risk Center SDK without mutation, then require explicit "
            "confirmation before generating or overwriting the persisted daily report."
        ),
        owner_app="risk_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="risk_center_generate_daily_report",
        tags=("risk_center", "daily_report", "generate", "upsert", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
                "report_date": {"type": "string", "format": "date"},
                "account_equity": {"type": "number", "minimum": 0},
                "cash_balance": {"type": "number", "minimum": 0},
                "total_position_value": {"type": "number", "minimum": 0},
                "daily_pnl_pct": {"type": "number"},
                "drawdown_pct": {"type": "number", "minimum": 0, "maximum": 1},
                "positions": {"type": "array"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "report_date", "account_equity"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "report_id": {"type": ["integer", "null"]},
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
                "risk_daily_report": {"type": "object"},
                "position_daily_report": {"type": "object"},
                "post_investment_check": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("risk_center:generate_daily_report", "mcp:write"),
        legacy_tool_names=("generate_risk_center_daily_report",),
    ),
]


def _scenario_write_manifest(
    *,
    capability_key: str,
    title: str,
    summary: str,
    executor_ref: str,
    required_roles: tuple[str, ...],
    operation: str,
) -> CapabilityManifest:
    """Build one preview-first governed scenario write manifest."""

    return CapabilityManifest(
        capability_key=capability_key,
        title=title,
        summary=summary,
        description=(
            "Use a persisted backend preview and idempotency record, verify the exact actor, "
            "payload fingerprint, base version/hash, expiry, and single-use confirmation, then "
            "execute the canonical Risk Center Application use case."
        ),
        owner_app="risk_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref=executor_ref,
        tags=("risk_center", "stress_scenario", operation, "write"),
        input_schema={
            "type": "object",
            "properties": {
                "payload": {"type": "object"},
                "preview_id": {"type": "string", "minLength": 1},
                "proposal_id": {"type": "string", "minLength": 1},
                "expected_active_version": {"type": ["integer", "null"], "minimum": 1},
                "expected_active_hash": {"type": ["string", "null"]},
                "change_reason": {"type": "string", "minLength": 1},
                "correlation_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
            "required": [
                "payload",
                "preview_id",
                "change_reason",
                "correlation_id",
                "idempotency_key",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "scenario_key": {"type": ["string", "null"]},
                "revision_id": {"type": ["string", "null"]},
                "proposal_id": {"type": ["string", "null"]},
                "preview_id": {"type": ["string", "null"]},
                "version": {"type": ["integer", "null"]},
                "content_hash": {"type": ["string", "null"]},
                "diff": {"type": "object"},
                "impact_summary": {"type": "object"},
                "warnings": {"type": "array"},
                "blocked_reason": {"type": ["string", "null"]},
                "must_not_use_for_decision": {"type": "boolean"},
                "audit_id": {"type": ["string", "null"]},
                "correlation_id": {"type": "string"},
            },
            "required": ["status", "correlation_id"],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=required_roles,
        audit_tags=(
            f"risk_center:stress_scenario:{operation}",
            "mcp:write",
            "mcp:native",
        ),
    )


MANIFESTS.extend(
    [
        _scenario_write_manifest(
            capability_key="risk_center.stress_scenario.propose_revision",
            title="Propose stress scenario revision",
            summary="Create an immutable revision proposal without changing production state.",
            executor_ref="risk_center_stress_scenario_propose_revision",
            required_roles=("admin", "investment_manager", "ai_service"),
            operation="propose",
        ),
        _scenario_write_manifest(
            capability_key="risk_center.stress_scenario.activate_revision",
            title="Activate approved stress scenario revision",
            summary="Activate a human-approved proposal under optimistic locking.",
            executor_ref="risk_center_stress_scenario_activate_revision",
            required_roles=("staff",),
            operation="activate",
        ),
        _scenario_write_manifest(
            capability_key="risk_center.stress_scenario.rollback_revision",
            title="Rollback stress scenario revision",
            summary="Copy a prior approved revision into a new version and activate it.",
            executor_ref="risk_center_stress_scenario_rollback_revision",
            required_roles=("staff",),
            operation="rollback",
        ),
        _scenario_write_manifest(
            capability_key="risk_center.stress_scenario.retire",
            title="Retire governed stress scenario",
            summary="Retire a scenario through an approved immutable replacement workflow.",
            executor_ref="risk_center_stress_scenario_retire",
            required_roles=("staff",),
            operation="retire",
        ),
    ]
)
