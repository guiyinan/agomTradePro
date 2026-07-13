# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_config_center."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_config_center_update_runtime_setting_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="config_center.update.runtime_setting",
        summary="Preview first, then update the Qlib runtime setting.",
        description="Governed write capability for Qlib runtime config updates.",
        owner_app="config_center",
        tags=("config_center", "qlib", "runtime", "settings", "update", "write"),
        audit_tags=("config_center:update_runtime_setting", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"provider_uri": {"type": "string"}},
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_qlib_runtime_config",),
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
                    name="update_qlib_runtime_config",
                    description="config center update qlib runtime config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.config_center.update.runtime_setting"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_qlib_runtime_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "config_center:update_runtime_setting",
        "mcp:write",
    ]
    assert governed.semantic_key == "config_center.update.runtime_setting"

    legacy = by_key["mcp_tool.update_qlib_runtime_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "config_center.update.runtime_setting"
    )
    assert legacy.semantic_key == "config_center.update.runtime_setting"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_config_center_update_data_center_provider_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="config_center.update.data_center_provider",
        summary="Preview first, then update the data-center provider.",
        description="Governed write capability for data-center provider updates.",
        owner_app="config_center",
        tags=("config_center", "data_center", "provider", "update", "write"),
        audit_tags=("config_center:update_data_center_provider", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"provider_id": {"type": "integer"}},
            "required": ["provider_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_data_center_provider",),
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
                    name="update_data_center_provider",
                    description="config center update data center provider",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.config_center.update.data_center_provider"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_data_center_provider"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "config_center:update_data_center_provider",
        "mcp:write",
    ]
    assert governed.semantic_key == "config_center.update.data_center_provider"

    legacy = by_key["mcp_tool.update_data_center_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "config_center.update.data_center_provider"
    )
    assert legacy.semantic_key == "config_center.update.data_center_provider"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_config_center_create_data_center_provider_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="config_center.create.data_center_provider",
        summary="Preview first, then create the data-center provider.",
        description="Governed write capability for data-center provider creation.",
        owner_app="config_center",
        tags=("config_center", "data_center", "provider", "create", "write"),
        audit_tags=("config_center:create_data_center_provider", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source_type": {"type": "string"},
            },
            "required": ["name", "source_type"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_data_center_provider",),
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
                    name="create_data_center_provider",
                    description="config center create data center provider",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.config_center.create.data_center_provider"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_data_center_provider"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "config_center:create_data_center_provider",
        "mcp:write",
    ]
    assert governed.semantic_key == "config_center.create.data_center_provider"

    legacy = by_key["mcp_tool.create_data_center_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "config_center.create.data_center_provider"
    )
    assert legacy.semantic_key == "config_center.create.data_center_provider"
    assert legacy.enabled_for_terminal is False
