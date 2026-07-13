"""beta_gate write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="beta_gate.create.config",
        title="Create And Activate Beta Gate Config",
        summary=("Preview the staff-only Beta Gate activation change, then create the config."),
        description=(
            "Read all persisted Beta Gate configs through the formal SDK, reject duplicate "
            "config ids, show the active config that will be replaced for the selected risk "
            "profile, then require confirmation before creating and activating the new version."
        ),
        owner_app="beta_gate",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="beta_gate_create_config",
        tags=("beta_gate", "config", "activation", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "string"},
                "risk_profile": {
                    "type": "string",
                    "enum": ["conservative", "balanced", "aggressive"],
                },
                "allowed_regimes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "Recovery",
                            "Overheat",
                            "Deflation",
                            "Stagflation",
                        ],
                    },
                },
                "min_confidence": {"type": "number"},
                "max_policy_level": {"type": "integer"},
                "veto_on_p3": {"type": "boolean"},
                "max_total_position": {"type": "number"},
                "max_single_position": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["risk_profile"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "result": {"type": "object"},
                "summary": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("beta_gate:create_config", "mcp:write"),
        legacy_tool_names=("create_beta_gate_config",),
    ),
    CapabilityManifest(
        capability_key="beta_gate.rollback.config",
        title="Rollback To Persisted Beta Gate Config",
        summary=(
            "Preview the staff-only active-config switch, then activate the selected "
            "persisted Beta Gate config."
        ),
        description=(
            "Read the exact target config and current active config through the formal "
            "Beta Gate SDK, reject active or expired targets, then require confirmation "
            "before activating the historical config for its risk profile."
        ),
        owner_app="beta_gate",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="beta_gate_rollback_config",
        tags=("beta_gate", "config", "activation", "rollback", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "result": {"type": "object"},
                "summary": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("beta_gate:rollback_config", "mcp:write"),
        legacy_tool_names=("rollback_beta_gate_config",),
    ),
]
