"""dashboard write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="dashboard.create.auto_advisor_weekly_report",
        title="Create Auto Advisor Weekly Report",
        summary="Preview the weekly report and target snapshot, then confirm persistence outputs.",
        description=(
            "Generate the user-scoped weekly report through the canonical read endpoint and inspect "
            "persisted history without mutation, then require explicit confirmation before "
            "upserting the report snapshot and creating its notification and audit outputs."
        ),
        owner_app="dashboard",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="dashboard_create_auto_advisor_weekly_report",
        tags=("dashboard", "auto_advisor", "weekly_report", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": ["integer", "string"],
                },
                "as_of": {"type": "string", "format": "date"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "as_of"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "account": {"type": "object"},
                "week": {"type": "object"},
                "investment_diary": {"type": "object"},
                "persisted": {
                    "type": "object",
                    "properties": {
                        "report": {"type": "object"},
                        "notification": {"type": "object"},
                        "audit": {"type": "object"},
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
        audit_tags=("dashboard:create_auto_advisor_weekly_report", "mcp:write"),
        legacy_tool_names=("create_auto_advisor_weekly_report",),
    ),
]

MANIFESTS.append(
    CapabilityManifest(
        capability_key="dashboard.refresh.alpha",
        title="Refresh Dashboard Alpha",
        summary="Preview and confirm one scoped Dashboard Alpha refresh task.",
        description=(
            "Stage a general research or portfolio-scoped Alpha refresh and preserve "
            "the contract that queued output is not yet an investment recommendation."
        ),
        owner_app="dashboard",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="dashboard_refresh_alpha",
        tags=("dashboard", "alpha", "refresh", "task", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "top_n": {"type": "integer", "minimum": 1, "maximum": 500},
                "portfolio_id": {"type": ["integer", "null"], "minimum": 1},
                "pool_mode": {"type": ["string", "null"], "maxLength": 64},
                "alpha_scope": {
                    "type": "string",
                    "enum": ["general", "portfolio"],
                },
                "idempotency_key": {"type": "string"},
            },
            "required": ["alpha_scope"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("dashboard:refresh_alpha", "mcp:write"),
        legacy_tool_names=("trigger_dashboard_alpha_refresh",),
    )
)
