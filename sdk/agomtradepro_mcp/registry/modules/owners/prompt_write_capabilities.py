"""prompt write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="prompt.create.template",
        title="Create Prompt Template",
        summary="Preview a unique prompt-template definition, then confirm staff-only creation.",
        description=(
            "Check the active and inactive prompt-template catalog for a reserved name, "
            "summarize the requested template contract, then require explicit confirmation "
            "before creating it through the canonical Prompt SDK."
        ),
        owner_app="prompt",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="prompt_create_template",
        tags=("prompt", "template", "configuration", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["report", "signal", "analysis", "chat"],
                },
                "version": {"type": "string"},
                "template_content": {"type": "string"},
                "system_prompt": {"type": "string"},
                "placeholders": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": [
                                    "simple",
                                    "structured",
                                    "function",
                                    "conditional",
                                ],
                            },
                            "description": {"type": "string"},
                            "default_value": {},
                            "required": {"type": "boolean"},
                            "function_name": {"type": "string"},
                            "function_params": {"type": "object"},
                        },
                        "required": ["name", "type"],
                    },
                },
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer"},
                "description": {"type": "string"},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["name", "category", "template_content"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "version": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("prompt:create_template", "mcp:write"),
        legacy_tool_names=("create_prompt_template",),
    ),
]
