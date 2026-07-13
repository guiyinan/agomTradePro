"""signal write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="signal.create.signal",
        title="Create Investment Signal",
        summary="Preview signal eligibility and payload summary, then confirm creation of a new investment signal.",
        description=(
            "Run signal eligibility and payload preview first, then require explicit "
            "confirmation before creating the pending investment signal record."
        ),
        owner_app="signal",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="signal_create_signal",
        tags=("signal", "investment", "eligibility", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "logic_desc": {"type": "string"},
                "invalidation_logic": {"type": "string"},
                "invalidation_threshold": {"type": "number"},
                "target_regime": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "asset_code",
                "logic_desc",
                "invalidation_logic",
                "invalidation_threshold",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "status": {"type": "string"},
                "created_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("signal:create_signal", "mcp:write"),
        legacy_tool_names=("create_signal",),
    ),
    CapabilityManifest(
        capability_key="signal.approve.signal",
        title="Approve Investment Signal",
        summary="Preview current signal status, then confirm approval of a pending investment signal.",
        description=(
            "Load the current signal snapshot first, then require explicit confirmation "
            "before approving the pending investment signal."
        ),
        owner_app="signal",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="signal_approve_signal",
        tags=("signal", "investment", "approval", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "signal_id": {"type": "integer"},
                "approver": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["signal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string"},
                "approved_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("signal:approve_signal", "mcp:write"),
        legacy_tool_names=("approve_signal",),
    ),
    CapabilityManifest(
        capability_key="signal.reject.signal",
        title="Reject Investment Signal",
        summary="Preview current signal status, then confirm rejection of a pending investment signal.",
        description=(
            "Load the current signal snapshot first, then require explicit confirmation "
            "before rejecting the pending investment signal."
        ),
        owner_app="signal",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="signal_reject_signal",
        tags=("signal", "investment", "rejection", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "signal_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["signal_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("signal:reject_signal", "mcp:write"),
        legacy_tool_names=("reject_signal",),
    ),
    CapabilityManifest(
        capability_key="signal.invalidate.signal",
        title="Invalidate Investment Signal",
        summary="Preview current signal status, then confirm invalidation of an investment signal.",
        description=(
            "Load the current signal snapshot first, then require explicit confirmation "
            "before invalidating the investment signal with a recorded reason."
        ),
        owner_app="signal",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="signal_invalidate_signal",
        tags=("signal", "investment", "invalidation", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "signal_id": {"type": "integer"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["signal_id", "reason"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string"},
                "invalidated_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("signal:invalidate_signal", "mcp:write"),
        legacy_tool_names=("invalidate_signal",),
    ),
]
