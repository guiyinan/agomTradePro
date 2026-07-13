# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_beta_gate."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_beta_gate_create_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="beta_gate.create.config",
        summary="Preview and create an active Beta Gate config.",
        description="Governed staff-only Beta Gate config creation.",
        owner_app="beta_gate",
        tags=("beta_gate", "config", "activation", "create", "write"),
        audit_tags=("beta_gate:create_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "string"},
                "risk_profile": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["risk_profile"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_beta_gate_config",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="create_beta_gate_config",
                    description="create Beta Gate config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.beta_gate.create.config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_beta_gate_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "beta_gate:create_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "beta_gate.create.config"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.create_beta_gate_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "beta_gate.create.config"
    assert legacy.semantic_key == "beta_gate.create.config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_beta_gate_rollback_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="beta_gate.rollback.config",
        summary="Preview and activate a persisted Beta Gate config.",
        description="Governed staff-only Beta Gate config rollback.",
        owner_app="beta_gate",
        tags=("beta_gate", "config", "activation", "rollback", "write"),
        audit_tags=("beta_gate:rollback_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("rollback_beta_gate_config",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="rollback_beta_gate_config",
                    description="rollback Beta Gate config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.beta_gate.rollback.config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["rollback_beta_gate_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "beta_gate:rollback_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "beta_gate.rollback.config"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.rollback_beta_gate_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "beta_gate.rollback.config"
    assert legacy.semantic_key == "beta_gate.rollback.config"
    assert legacy.enabled_for_terminal is False
