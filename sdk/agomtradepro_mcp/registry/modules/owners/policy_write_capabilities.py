"""policy write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="policy.create.event",
        title="Create Policy Event",
        summary="Preview same-day policy context, then confirm staff-only event creation.",
        description=(
            "Read the existing policy events for the requested date, summarize the canonical "
            "event fields and alert side-effect risk, then require explicit confirmation before "
            "creating the event through the canonical Policy SDK."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_create_event",
        tags=("policy", "event", "configuration", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_date": {"type": "string", "format": "date"},
                "level": {
                    "type": "string",
                    "enum": ["PX", "P0", "P1", "P2", "P3"],
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
                "evidence_url": {"type": "string", "format": "uri"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "event_date",
                "level",
                "title",
                "description",
                "evidence_url",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "event_date": {"type": "string"},
                        "level": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "evidence_url": {"type": "string"},
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
        audit_tags=("policy:create_event", "mcp:write"),
        legacy_tool_names=("create_policy_event",),
    ),
    CapabilityManifest(
        capability_key="policy.start.rss_fetch",
        title="Start Policy RSS Fetch",
        summary="Preview RSS source targets and side effects, then confirm the synchronous fetch.",
        description=(
            "Read persisted RSS source metadata without fetching, AI calls, writes, alerts, "
            "or task submission. Explicit confirmation is required before the canonical "
            "synchronous RSS fetch performs external I/O and policy ingestion writes."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_start_rss_fetch",
        tags=("policy", "rss", "fetch", "workflow", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "minimum": 1},
                "force_refetch": {"type": "boolean", "default": False},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["single", "all"]},
                "sources_processed": {"type": "integer"},
                "total_items": {"type": "integer"},
                "new_policy_events": {"type": "integer"},
                "errors": {"type": "array"},
                "details": {"type": "array"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("policy:rss_fetch", "mcp:write"),
        legacy_tool_names=("trigger_rss_fetch",),
    ),
    CapabilityManifest(
        capability_key="policy.approve.workbench_event",
        title="Approve Policy Workbench Event",
        summary="Preview the current workbench event, then confirm approving it.",
        description=(
            "Load the current policy workbench event detail first, then require explicit "
            "confirmation before approving the event and moving it out of pending review."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_approve_workbench_event",
        tags=("policy", "workbench", "approve", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["event_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("policy:approve_workbench_event", "mcp:write"),
        legacy_tool_names=("approve_workbench_event",),
    ),
    CapabilityManifest(
        capability_key="policy.reject.workbench_event",
        title="Reject Policy Workbench Event",
        summary="Preview the current workbench event, then confirm rejecting it.",
        description=(
            "Load the current policy workbench event detail first, then require explicit "
            "confirmation before rejecting the event with an operator-supplied reason."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_reject_workbench_event",
        tags=("policy", "workbench", "reject", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("policy:reject_workbench_event", "mcp:write"),
        legacy_tool_names=("reject_workbench_event",),
    ),
    CapabilityManifest(
        capability_key="policy.rollback.workbench_event",
        title="Rollback Policy Workbench Event",
        summary="Preview the current workbench event, then confirm rolling it back.",
        description=(
            "Load the current policy workbench event detail first, then require explicit "
            "confirmation before rolling back the event's effective state with an "
            "operator-supplied reason."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_rollback_workbench_event",
        tags=("policy", "workbench", "rollback", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("policy:rollback_workbench_event", "mcp:write"),
        legacy_tool_names=("rollback_workbench_event",),
    ),
    CapabilityManifest(
        capability_key="policy.override.workbench_event",
        title="Override Policy Workbench Event",
        summary="Preview the current workbench event, then confirm overriding it.",
        description=(
            "Load the current policy workbench event detail first, then require explicit "
            "confirmation before applying a manual override reason and optional level "
            "change to the event."
        ),
        owner_app="policy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="policy_override_workbench_event",
        tags=("policy", "workbench", "override", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
                "new_level": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                "idempotency_key": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "event_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("policy:override_workbench_event", "mcp:write"),
        legacy_tool_names=("override_workbench_event",),
    ),
]
