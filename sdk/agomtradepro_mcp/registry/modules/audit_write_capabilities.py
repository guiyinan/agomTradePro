"""Governed Audit write capability manifests."""

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="audit.create.attribution_report",
        title="Create Audit Attribution Report",
        summary="Preview one completed backtest, then confirm attribution report generation.",
        description=(
            "Read the exact completed backtest and existing report count without fetching market "
            "data or writing records, then require explicit confirmation before synchronous "
            "attribution analysis creates the report and child audit records."
        ),
        owner_app="audit",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="audit_generate_attribution_report",
        tags=("audit", "attribution", "backtest", "report", "create", "workflow"),
        input_schema={
            "type": "object",
            "properties": {
                "backtest_id": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string"},
            },
            "required": ["backtest_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "backtest_id": {"type": "integer"},
                "loss_analyses": {"type": "array"},
                "experience_summaries": {"type": "array"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("audit:attribution_report", "mcp:write"),
        legacy_tool_names=("generate_audit_report",),
    ),
    CapabilityManifest(
        capability_key="audit.start.threshold_validation",
        title="Start Audit Threshold Validation",
        summary="Preview active audit indicators and write impact, then confirm validation.",
        description=(
            "Read active threshold targets without running validation or writing audit records, "
            "then require explicit confirmation before the canonical synchronous validation "
            "persists its summary and per-indicator performance reports."
        ),
        owner_app="audit",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="audit_start_threshold_validation",
        tags=("audit", "threshold", "validation", "workflow", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "validation_run_id": {"type": ["string", "null"]},
                "report": {"type": ["object", "null"]},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("audit:threshold_validation", "mcp:write"),
        legacy_tool_names=("run_audit_validation", "validate_all_indicators"),
    ),
    CapabilityManifest(
        capability_key="audit.update.threshold_levels",
        title="Update Audit Threshold Levels",
        summary="Preview current and target levels, then confirm one threshold update.",
        description=(
            "Read the exact active indicator threshold configuration without changing it, "
            "reject missing or unchanged targets, and require explicit confirmation before "
            "the canonical Audit API updates level_low and level_high."
        ),
        owner_app="audit",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="audit_update_threshold_levels",
        tags=("audit", "threshold", "configuration", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string", "minLength": 1, "maxLength": 50},
                "level_low": {"type": "number"},
                "level_high": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code", "level_low", "level_high"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "updated": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("audit:threshold_levels", "mcp:write"),
        legacy_tool_names=("update_audit_threshold",),
    ),
]
