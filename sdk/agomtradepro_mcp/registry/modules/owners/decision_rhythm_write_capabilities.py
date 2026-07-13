"""decision_rhythm write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="decision.create.execution_request",
        title="Create Decision Execution Request",
        summary="Preview a transition-plan execution, then create an approval request after confirmation.",
        description=(
            "Run the decision execution preview first with create_request=false, then require "
            "explicit confirmation before creating the approval request with create_request=true."
        ),
        owner_app="decision_rhythm",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="decision_workflow_preview_execution",
        tags=("decision", "execution", "approval", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "plan_id": {"type": "string"},
                "recommendation_id": {"type": "string"},
                "market_price": {},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"create_request": False},
        confirmation_commit_arguments={"create_request": True},
        idempotency="required",
        audit_tags=("decision:create_execution_request", "mcp:write"),
        legacy_tool_names=("decision_workflow_preview_execution",),
    ),
    CapabilityManifest(
        capability_key="decision.submit.request_batch",
        title="Submit Decision Requests Batch",
        summary="Preview a batch decision submission, then confirm creation of the decision requests.",
        description=(
            "Build a preview summary of the decision request batch first, then require "
            "explicit confirmation before submitting the batch into the decision rhythm workflow."
        ),
        owner_app="decision_rhythm",
        risk_level="medium",
        executor_kind="internal_handler",
        executor_ref="decision_submit_request_batch",
        tags=("decision", "workflow", "batch", "submit", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "payload": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["payload"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "requests": {"type": "array"},
                "summary": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("decision_rhythm:submit_batch", "mcp:write"),
        legacy_tool_names=("submit_batch_decision_request",),
    ),
    CapabilityManifest(
        capability_key="decision.submit.request",
        title="Submit Decision Request",
        summary="Preview a single decision submission, then confirm creation of the decision request.",
        description=(
            "Build a preview summary of the single decision request first, then require "
            "explicit confirmation before submitting it into the decision rhythm workflow."
        ),
        owner_app="decision_rhythm",
        risk_level="medium",
        executor_kind="internal_handler",
        executor_ref="decision_submit_request",
        tags=("decision", "workflow", "submit", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "payload": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["payload"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "request": {"type": "object"},
                "summary": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("decision_rhythm:submit_request", "mcp:write"),
        legacy_tool_names=("submit_decision_request",),
    ),
    CapabilityManifest(
        capability_key="decision.execute.request",
        title="Execute Decision Request",
        summary="Preview request status and execution payload, then confirm execution of an approved decision request.",
        description=(
            "Load the current decision request and execution payload summary first, then require "
            "explicit confirmation before executing the approved request into its target system."
        ),
        owner_app="decision_rhythm",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="decision_execute_request",
        tags=("decision", "workflow", "execution", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "payload": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["request_id", "payload"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "request_id": {"type": "string"},
                "execution_status": {"type": "string"},
                "execution_ref": {},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("decision_rhythm:execute_request", "mcp:write"),
        legacy_tool_names=("decision_execute_request",),
    ),
    CapabilityManifest(
        capability_key="decision.cancel.request",
        title="Cancel Decision Request",
        summary="Preview current request status, then confirm cancellation of the decision request.",
        description=(
            "Load the current decision request state first, then require explicit "
            "confirmation before cancelling the pending or approved request."
        ),
        owner_app="decision_rhythm",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="decision_cancel_request",
        tags=("decision", "workflow", "cancel", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["request_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "request_id": {"type": "string"},
                "status": {"type": "string"},
                "candidate_status": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("decision_rhythm:cancel_request", "mcp:write"),
        legacy_tool_names=("decision_cancel_request",),
    ),
    CapabilityManifest(
        capability_key="decision.reset.quota",
        title="Reset Decision Quota",
        summary="Preview the selected account quota state, then confirm resetting one or all periods.",
        description=(
            "Load the persisted quota state for the selected account through the canonical "
            "Decision Rhythm SDK, then require explicit confirmation before resetting usage "
            "counters for one period or every existing period."
        ),
        owner_app="decision_rhythm",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="decision_reset_quota",
        tags=("decision", "quota", "reset", "account", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "period": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly"],
                },
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "account_id": {"type": "string"},
                "reset_periods": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("decision_rhythm:reset_quota", "mcp:write"),
        legacy_tool_names=("reset_decision_quota",),
    ),
]

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="decision.refresh.recommendations",
            title="Refresh Decision Recommendations",
            summary="Preview and confirm one bounded recommendation refresh.",
            description="Stage account and security scope before refreshing persisted recommendations.",
            owner_app="decision_rhythm",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="decision_refresh_recommendations",
            tags=("decision", "recommendation", "refresh", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "account_id": {"type": ["string", "null"], "maxLength": 128},
                    "security_codes": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "maxItems": 500,
                    },
                    "force": {"type": "boolean"},
                    "async_mode": {"type": "boolean"},
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
            audit_tags=("decision:refresh_recommendations", "mcp:write"),
            legacy_tool_names=("decision_workflow_refresh_recommendations",),
        ),
        CapabilityManifest(
            capability_key="decision.update.recommendation_action",
            title="Update Recommendation Action",
            summary="Preview and confirm one user action on a recommendation.",
            description="Show the exact recommendation, account, action, and note before persisting it.",
            owner_app="decision_rhythm",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="decision_update_recommendation_action",
            tags=("decision", "recommendation", "action", "update", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "recommendation_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "action": {
                        "type": "string",
                        "enum": ["watch", "adopt", "ignore", "pending"],
                    },
                    "account_id": {"type": ["string", "null"], "maxLength": 128},
                    "note": {"type": ["string", "null"], "maxLength": 2000},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["recommendation_id", "action"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("decision:update_recommendation_action", "mcp:write"),
            legacy_tool_names=("decision_workflow_apply_recommendation_action",),
        ),
        CapabilityManifest(
            capability_key="decision.create.transition_plan",
            title="Create Transition Plan",
            summary="Preview and confirm generation of one persisted transition plan.",
            description="Show account and recommendation scope before generating orders and a durable plan.",
            owner_app="decision_rhythm",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="decision_create_transition_plan",
            tags=("decision", "transition", "plan", "create", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "recommendation_ids": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "maxItems": 200,
                    },
                    "idempotency_key": {"type": "string"},
                },
                "required": ["account_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("decision:create_transition_plan", "mcp:write"),
            legacy_tool_names=("decision_workflow_generate_transition_plan",),
        ),
        CapabilityManifest(
            capability_key="decision.update.transition_plan",
            title="Update Transition Plan",
            summary="Preview and confirm replacement of transition-plan order parameters.",
            description="Load current plan state and show bounded order changes before persisting them.",
            owner_app="decision_rhythm",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="decision_update_transition_plan",
            tags=("decision", "transition", "plan", "update", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "orders": {
                        "type": "array",
                        "maxItems": 500,
                        "items": {"type": "object"},
                    },
                    "idempotency_key": {"type": "string"},
                },
                "required": ["plan_id", "orders"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("decision:update_transition_plan", "mcp:write"),
            legacy_tool_names=("decision_workflow_update_transition_plan",),
        ),
    ]
)
