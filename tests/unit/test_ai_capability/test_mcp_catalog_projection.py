"""Tests for projecting governed MCP metadata into the AI catalog."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES

from apps.ai_capability.application.mcp_catalog_projection import (
    build_governed_mcp_capability,
    build_legacy_replacement_map,
)
from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

GOVERNED_MANIFESTS = tuple(CapabilityRegistryLoader().load_manifests())


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


@pytest.mark.parametrize(
    "manifest",
    GOVERNED_MANIFESTS,
    ids=lambda manifest: manifest.capability_key,
)
def test_governed_manifest_projection_matrix_preserves_all_metadata(manifest) -> None:
    """Every governed manifest must project without owner-specific handwritten tests."""

    capability = build_governed_mcp_capability(manifest)

    assert capability.capability_key == f"mcp_tool.{manifest.capability_key}"
    assert capability.source_ref == manifest.capability_key
    assert capability.name == manifest.capability_key
    assert capability.summary == manifest.summary
    assert capability.description == manifest.description
    assert capability.category == manifest.owner_app
    assert capability.semantic_key == manifest.capability_key
    assert capability.tags == ["mcp", "capability", *manifest.tags]
    assert capability.input_schema == manifest.input_schema
    assert capability.execution_target == {
        "type": "mcp_capability",
        "tool_name": "agom_capability_call",
        "capability_key": manifest.capability_key,
        "replacement_for": list(manifest.legacy_tool_names),
        "idempotency": manifest.idempotency,
        "idempotency_argument_name": manifest.idempotency_argument_name,
        "audit_tags": list(manifest.audit_tags),
        "required_roles": list(manifest.required_roles),
    }
    assert capability.risk_level.value == manifest.risk_level
    assert capability.requires_confirmation is manifest.requires_confirmation
    assert capability.requires_mcp is True
    assert capability.enabled_for_routing is True
    assert capability.enabled_for_terminal is True
    assert capability.enabled_for_chat is False
    assert capability.enabled_for_agent is True


def test_governed_manifest_legacy_projection_matrix_preserves_every_alias() -> None:
    """Sync must retain every declared legacy alias as a disabled compatibility entry."""

    legacy_replacements = build_legacy_replacement_map(list(GOVERNED_MANIFESTS))
    legacy_tools = [
        SimpleNamespace(name=name, description=f"Legacy alias for {replacement}", inputSchema={})
        for name, replacement in sorted(legacy_replacements.items())
    ]
    core_tools = [
        SimpleNamespace(name=name, description="Core MCP tool", inputSchema={})
        for name in sorted(CORE_TOOL_NAMES)
    ]
    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=list(GOVERNED_MANIFESTS),
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value=set(CORE_TOOL_NAMES),
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[*core_tools, *legacy_tools],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {capability.capability_key: capability for capability in capabilities}
    for manifest in GOVERNED_MANIFESTS:
        governed = by_key[f"mcp_tool.{manifest.capability_key}"]
        assert governed.execution_target["replacement_for"] == list(manifest.legacy_tool_names)
        for legacy_tool_name in manifest.legacy_tool_names:
            legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
            assert legacy.semantic_key == manifest.capability_key
            assert legacy.execution_target["replacement_capability_key"] == (
                manifest.capability_key
            )
            assert legacy.enabled_for_terminal is False
            assert legacy.enabled_for_chat is False
            assert legacy.enabled_for_agent is False
