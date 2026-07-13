"""agent_runtime write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="agent_proposal.create.proposal",
        title="Create Agent Proposal",
        summary="Preview an agent proposal payload, then confirm creation of the proposal record.",
        description=(
            "Build a preview of the proposal metadata first, then require explicit "
            "confirmation before creating the persisted agent proposal request."
        ),
        owner_app="agent_runtime",
        risk_level="medium",
        executor_kind="internal_handler",
        executor_ref="agent_proposal_create_proposal",
        tags=("agent_runtime", "proposal", "approval", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "proposal_type": {"type": "string"},
                "task_id": {"type": "integer"},
                "risk_level": {"type": "string"},
                "approval_required": {"type": "boolean"},
                "proposal_payload": {"type": "object"},
                "approval_reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["proposal_type"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "request_id": {"type": "string"},
                "proposal": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("agent_runtime:create_proposal", "mcp:write"),
        legacy_tool_names=("create_agent_proposal",),
    ),
    CapabilityManifest(
        capability_key="agent_proposal.execute.proposal",
        title="Execute Agent Proposal",
        summary="Preview proposal execution context, then confirm execution of an approved proposal.",
        description=(
            "Load the proposal and its execution context first, then require explicit "
            "confirmation before executing the approved proposal through guardrail checks."
        ),
        owner_app="agent_runtime",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="agent_proposal_execute_proposal",
        tags=("agent_runtime", "proposal", "execution", "guardrail", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "proposal_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["proposal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "proposal": {"type": "object"},
                "execution_record_id": {"type": "integer"},
                "guardrail_decision": {},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("agent_runtime:execute_proposal", "mcp:write"),
        legacy_tool_names=("execute_agent_proposal",),
    ),
    CapabilityManifest(
        capability_key="agent_proposal.approve.proposal",
        title="Approve Agent Proposal",
        summary="Preview the proposal approval transition, then confirm approval of a submitted proposal.",
        description=(
            "Load the current proposal status and approval context first, then require explicit "
            "confirmation before transitioning the submitted proposal into approved state."
        ),
        owner_app="agent_runtime",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="agent_proposal_approve_proposal",
        tags=("agent_runtime", "proposal", "approval", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "proposal_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["proposal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "proposal": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("agent_runtime:approve_proposal", "mcp:write"),
        legacy_tool_names=("approve_agent_proposal",),
    ),
    CapabilityManifest(
        capability_key="agent_proposal.reject.proposal",
        title="Reject Agent Proposal",
        summary="Preview the proposal rejection transition, then confirm rejection of a submitted proposal.",
        description=(
            "Load the current proposal status and rejection context first, then require explicit "
            "confirmation before transitioning the submitted proposal into rejected state."
        ),
        owner_app="agent_runtime",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="agent_proposal_reject_proposal",
        tags=("agent_runtime", "proposal", "rejection", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "proposal_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["proposal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "proposal": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("agent_runtime:reject_proposal", "mcp:write"),
        legacy_tool_names=("reject_agent_proposal",),
    ),
]
