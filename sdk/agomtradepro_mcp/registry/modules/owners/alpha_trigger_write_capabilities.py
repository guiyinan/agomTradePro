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

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="alpha_trigger.create.trigger",
            title="Create Alpha Trigger",
            summary="Preview and confirm creation of one Alpha trigger.",
            description="Validate and summarize the trigger payload before creating its persisted record.",
            owner_app="alpha_trigger",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_trigger_create_trigger",
            tags=("alpha_trigger", "trigger", "create", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("alpha_trigger:create_trigger", "mcp:write"),
            legacy_tool_names=("create_alpha_trigger",),
        ),
        CapabilityManifest(
            capability_key="alpha_trigger.execute.evaluation",
            title="Evaluate Alpha Trigger",
            summary="Preview and confirm one Alpha trigger evaluation workflow.",
            description="Summarize the exact evaluation payload before running stateful trigger evaluation.",
            owner_app="alpha_trigger",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_trigger_execute_evaluation",
            tags=("alpha_trigger", "trigger", "evaluation", "execute", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("alpha_trigger:evaluate", "mcp:write"),
            legacy_tool_names=("evaluate_alpha_trigger",),
        ),
        CapabilityManifest(
            capability_key="alpha_trigger.execute.invalidation_check",
            title="Check Alpha Trigger Invalidation",
            summary="Preview and confirm one stateful invalidation check.",
            description="Summarize the exact invalidation payload before applying trigger state transitions.",
            owner_app="alpha_trigger",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_trigger_execute_invalidation_check",
            tags=("alpha_trigger", "invalidation", "check", "execute", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("alpha_trigger:invalidation_check", "mcp:write"),
            legacy_tool_names=("check_alpha_trigger_invalidation",),
        ),
        CapabilityManifest(
            capability_key="alpha_trigger.generate.candidate",
            title="Generate Alpha Candidate",
            summary="Preview and confirm generation of one persisted Alpha candidate.",
            description="Summarize candidate-generation inputs before creating or updating candidate state.",
            owner_app="alpha_trigger",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_trigger_generate_candidate",
            tags=("alpha_trigger", "candidate", "generate", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            audit_tags=("alpha_trigger:generate_candidate", "mcp:write"),
            legacy_tool_names=("generate_alpha_candidate",),
        ),
    ]
)
