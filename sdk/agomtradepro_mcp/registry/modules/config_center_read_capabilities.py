"""Governed Config Center read capability manifests."""

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="config_center.read.snapshot",
        title="Read Config Center Snapshot",
        summary="Read the staff-visible configuration status snapshot without creating defaults.",
        description=(
            "Return the canonical staff-only configuration-center sections and redacted summary "
            "metadata through the formal SDK without creating settings, profiles, providers, "
            "training records, tokens, or capability catalog rows."
        ),
        owner_app="config_center",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="get_config_center_snapshot",
        tags=("config_center", "snapshot", "configuration", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "generated_at": {"type": "string"},
                "sections": {"type": "array"},
            },
            "required": ["sections"],
        },
        required_roles=("staff",),
        audit_tags=("config_center:snapshot", "mcp:read"),
        legacy_tool_names=("get_config_center_snapshot",),
    ),
]
