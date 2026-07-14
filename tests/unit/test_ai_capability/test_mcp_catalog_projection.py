"""Tests for projecting governed MCP metadata into the AI catalog."""

from types import SimpleNamespace

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

from apps.ai_capability.application.mcp_catalog_projection import (
    build_governed_mcp_capability,
)


def test_governed_projection_preserves_required_roles_for_terminal_filtering():
    manifest = SimpleNamespace(
        capability_key="config_center.update.runtime_setting",
        title="Update Runtime Setting",
        summary="Update one protected runtime setting.",
        description="Update one protected runtime setting.",
        owner_app="config_center",
        risk_level="high",
        tags=("config", "write"),
        input_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        required_roles=("staff",),
        legacy_tool_names=(),
        idempotency="required",
        idempotency_argument_name="idempotency_key",
        audit_tags=("mcp:write",),
    )

    capability = build_governed_mcp_capability(manifest)

    assert capability.execution_target["required_roles"] == ["staff"]


def test_terminal_action_bridge_manifests_project_into_ai_catalog():
    manifests = CapabilityRegistryLoader().load_manifests()
    projected = {
        capability.source_ref: capability
        for capability in (
            build_governed_mcp_capability(manifest)
            for manifest in manifests
            if manifest.owner_app == "terminal"
        )
    }

    assert set(projected) == {
        "terminal.search.user_actions",
        "terminal.read.user_action_schema",
        "terminal.read.user_action_result",
        "terminal.execute.user_action",
    }
    assert projected["terminal.execute.user_action"].requires_confirmation is True
