"""alpha_trigger write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="alpha_trigger.update.candidate_status",
        title="Update Alpha Trigger Candidate Status",
        summary="Preview the current alpha candidate and target status, then confirm updating the candidate status.",
        description=(
            "Load the current alpha candidate context first and summarize the target status "
            "change, then require explicit confirmation before updating the candidate status "
            "through the existing alpha-trigger write path."
        ),
        owner_app="alpha_trigger",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="alpha_trigger_update_candidate_status",
        tags=("alpha_trigger", "candidate", "status", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "status": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["candidate_id", "status"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "asset_code": {"type": "string"},
                "asset_class": {"type": "string"},
                "direction": {"type": "string"},
                "status": {"type": "string"},
                "confidence": {"type": "number"},
                "created_at": {"type": "string"},
                "expires_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("alpha_trigger:update_candidate_status", "mcp:write"),
        legacy_tool_names=("update_alpha_candidate_status",),
    ),
]
