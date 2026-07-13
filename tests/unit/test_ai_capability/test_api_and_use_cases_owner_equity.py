# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_equity."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_equity_valuation_config_create_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="equity.create.valuation_repair_config",
        summary="Preview first, then create an inactive valuation repair config draft.",
        description="Governed staff-only Equity valuation repair config creation capability.",
        owner_app="equity",
        tags=("equity", "valuation", "repair", "configuration", "create", "write"),
        audit_tags=("equity:create_valuation_repair_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "change_reason": {"type": "string"},
                "target_percentile": {"type": "number"},
            },
            "required": ["change_reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_valuation_repair_config",),
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
                    name="create_valuation_repair_config",
                    description="create valuation repair config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.equity.create.valuation_repair_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_valuation_repair_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "equity:create_valuation_repair_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "equity.create.valuation_repair_config"

    legacy = by_key["mcp_tool.create_valuation_repair_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "equity.create.valuation_repair_config"
    )
    assert legacy.semantic_key == "equity.create.valuation_repair_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_equity_valuation_config_activation_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="equity.activate.valuation_repair_config",
        summary="Preview first, then activate one persisted valuation repair config.",
        description="Governed staff-only Equity valuation repair config activation capability.",
        owner_app="equity",
        tags=("equity", "valuation", "repair", "configuration", "activate", "write"),
        audit_tags=("equity:activate_valuation_repair_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"config_id": {"type": "integer"}},
            "required": ["config_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=(
            "activate_valuation_repair_config",
            "rollback_valuation_repair_config",
        ),
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
                    name="activate_valuation_repair_config",
                    description="activate valuation repair config",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="rollback_valuation_repair_config",
                    description="rollback valuation repair config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.equity.activate.valuation_repair_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "activate_valuation_repair_config",
        "rollback_valuation_repair_config",
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "equity:activate_valuation_repair_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "equity.activate.valuation_repair_config"

    for tool_name in (
        "activate_valuation_repair_config",
        "rollback_valuation_repair_config",
    ):
        legacy = by_key[f"mcp_tool.{tool_name}"]
        assert legacy.execution_target["type"] == "mcp_tool"
        assert (
            legacy.execution_target["replacement_capability_key"]
            == "equity.activate.valuation_repair_config"
        )
        assert legacy.semantic_key == "equity.activate.valuation_repair_config"
        assert legacy.enabled_for_terminal is False
