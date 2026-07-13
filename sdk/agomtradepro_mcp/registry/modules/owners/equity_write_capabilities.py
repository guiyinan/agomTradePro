"""equity write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="equity.create.valuation_repair_config",
        title="Create Valuation Repair Config",
        summary="Preview the next inactive config version, then confirm staff-only draft creation.",
        description=(
            "Read the persisted valuation-repair config catalog and current active config through "
            "the canonical Equity SDK, calculate the expected next version and field differences, "
            "then require explicit confirmation before creating an inactive draft."
        ),
        owner_app="equity",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="equity_create_valuation_repair_config",
        tags=("equity", "valuation", "repair", "configuration", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "change_reason": {"type": "string"},
                "min_history_points": {"type": "integer"},
                "default_lookback_days": {"type": "integer"},
                "confirm_window": {"type": "integer"},
                "min_rebound": {"type": "number", "minimum": 0, "maximum": 1},
                "stall_window": {"type": "integer"},
                "stall_min_progress": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "target_percentile": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "undervalued_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "near_target_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "overvalued_threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "pe_weight": {"type": "number"},
                "pb_weight": {"type": "number"},
                "confidence_base": {"type": "number"},
                "confidence_sample_threshold": {"type": "integer"},
                "confidence_sample_bonus": {"type": "number"},
                "confidence_blend_bonus": {"type": "number"},
                "confidence_repair_start_bonus": {"type": "number"},
                "confidence_not_stalled_bonus": {"type": "number"},
                "repairing_threshold": {"type": "number"},
                "eta_max_days": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["change_reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "version": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "change_reason": {"type": "string"},
                "created_by": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("equity:create_valuation_repair_config", "mcp:write"),
        legacy_tool_names=("create_valuation_repair_config",),
    ),
    CapabilityManifest(
        capability_key="equity.activate.valuation_repair_config",
        title="Activate Valuation Repair Config",
        summary="Preview the active-config switch, then confirm staff-only activation.",
        description=(
            "Read the exact target config and current active config through the canonical Equity "
            "SDK, disclose the activation, deactivation and runtime-cache effects, then require "
            "explicit confirmation before activating the selected persisted version."
        ),
        owner_app="equity",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="equity_activate_valuation_repair_config",
        tags=("equity", "valuation", "repair", "configuration", "activate", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "data": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "version": {"type": "integer"},
                        "is_active": {"type": "boolean"},
                        "effective_from": {"type": "string"},
                    },
                    "required": [],
                },
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("equity:activate_valuation_repair_config", "mcp:write"),
        legacy_tool_names=(
            "activate_valuation_repair_config",
            "rollback_valuation_repair_config",
        ),
    ),
]

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="equity.run.valuation_repair_scan",
            title="Run Valuation Repair Scan",
            summary="Preview and confirm a bounded valuation-repair scan.",
            description="Show universe, lookback, and row limit before persisting repair snapshots.",
            owner_app="equity",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="equity_run_valuation_repair_scan",
            tags=("equity", "valuation", "repair", "scan", "run", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "universe": {
                        "type": "string",
                        "enum": ["all_active", "current_pool"],
                    },
                    "lookback_days": {"type": "integer", "minimum": 30, "maximum": 5000},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10000},
                    "idempotency_key": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("equity:valuation_repair_scan", "mcp:write"),
            legacy_tool_names=("scan_valuation_repairs",),
        ),
        CapabilityManifest(
            capability_key="equity.sync.valuation_data",
            title="Sync Equity Valuation Data",
            summary="Preview and confirm a bounded valuation-data synchronization.",
            description="Show dates, assets, and provider failover order before writing valuation facts.",
            owner_app="equity",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="equity_sync_valuation_data",
            tags=("equity", "valuation", "provider", "sync", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "minimum": 1, "maximum": 5000},
                    "stock_codes": {"type": ["array", "null"], "items": {"type": "string"}},
                    "start_date": {"type": ["string", "null"], "format": "date"},
                    "end_date": {"type": ["string", "null"], "format": "date"},
                    "primary_source": {"type": "string", "minLength": 1, "maxLength": 64},
                    "fallback_source": {"type": "string", "minLength": 1, "maxLength": 64},
                    "idempotency_key": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("equity:sync_valuation_data", "mcp:write"),
            legacy_tool_names=("sync_valuation_data",),
        ),
        CapabilityManifest(
            capability_key="equity.create.valuation_quality_snapshot",
            title="Create Valuation Quality Snapshot",
            summary="Preview and confirm validation of valuation data into a gate snapshot.",
            description="Show as-of date and source before persisting quality and gate evidence.",
            owner_app="equity",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="equity_create_valuation_quality_snapshot",
            tags=("equity", "valuation", "quality", "snapshot", "create", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "as_of_date": {"type": ["string", "null"], "format": "date"},
                    "primary_source": {"type": "string", "minLength": 1, "maxLength": 64},
                    "idempotency_key": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("equity:create_valuation_quality_snapshot", "mcp:write"),
            legacy_tool_names=("validate_valuation_data",),
        ),
    ]
)
