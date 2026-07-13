# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_rotation."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_rotation_create_account_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.create.account_config",
        summary="Preview first, then create the account rotation config.",
        description="Governed write capability for account rotation config creation.",
        owner_app="rotation",
        tags=("rotation", "account_config", "create", "write"),
        audit_tags=("rotation:create_account_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "is_enabled": {"type": "boolean"},
                "regime_allocations": {"type": "object"},
            },
            "required": ["account_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_account_rotation_config",),
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
                    name="create_account_rotation_config",
                    description="rotation account config create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.create.account_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_account_rotation_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:create_account_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "rotation.create.account_config"

    legacy = by_key["mcp_tool.create_account_rotation_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.create.account_config"
    assert legacy.semantic_key == "rotation.create.account_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_delete_account_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.delete.account_config",
        summary="Preview first, then delete the account rotation config.",
        description="Governed write capability for account rotation config deletion.",
        owner_app="rotation",
        tags=("rotation", "account_config", "delete", "write"),
        audit_tags=("rotation:delete_account_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
            },
            "required": ["config_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("delete_account_rotation_config",),
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
                    name="delete_account_rotation_config",
                    description="rotation account config delete",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.delete.account_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["delete_account_rotation_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:delete_account_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "rotation.delete.account_config"

    legacy = by_key["mcp_tool.delete_account_rotation_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.delete.account_config"
    assert legacy.semantic_key == "rotation.delete.account_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_update_account_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.update.account_config",
        summary="Preview first, then update the account rotation config.",
        description="Governed write capability for account rotation config update.",
        owner_app="rotation",
        tags=("rotation", "account_config", "update", "write"),
        audit_tags=("rotation:update_account_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "payload": {"type": "object"},
                "partial": {"type": "boolean"},
            },
            "required": ["config_id", "payload"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_account_rotation_config",),
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
                    name="update_account_rotation_config",
                    description="rotation account config update",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.update.account_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_account_rotation_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:update_account_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "rotation.update.account_config"

    legacy = by_key["mcp_tool.update_account_rotation_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.update.account_config"
    assert legacy.semantic_key == "rotation.update.account_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_apply_template_account_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.apply_template.account_config",
        summary="Preview first, then apply a template to the account rotation config.",
        description="Governed write capability for account rotation config template application.",
        owner_app="rotation",
        tags=("rotation", "account_config", "template", "apply", "write"),
        audit_tags=("rotation:apply_template_account_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "template_key": {"type": "string"},
            },
            "required": ["config_id", "template_key"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("apply_rotation_template_to_account_config",),
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
                    name="apply_rotation_template_to_account_config",
                    description="rotation account config apply template",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.apply_template.account_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "apply_rotation_template_to_account_config"
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:apply_template_account_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "rotation.apply_template.account_config"

    legacy = by_key["mcp_tool.apply_rotation_template_to_account_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "rotation.apply_template.account_config"
    )
    assert legacy.semantic_key == "rotation.apply_template.account_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_asset_create_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.create.asset",
        summary="Preview and create a global Rotation asset.",
        description="Governed staff-only Rotation asset catalog creation.",
        owner_app="rotation",
        tags=("rotation", "asset", "catalog", "configuration", "create", "write"),
        audit_tags=("rotation:create_asset", "mcp:write", "catalog:global"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["code", "name", "category"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_rotation_asset",),
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
                    name="create_rotation_asset",
                    description="create Rotation asset",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.create.asset"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_rotation_asset"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:create_asset",
        "mcp:write",
        "catalog:global",
    ]
    assert governed.semantic_key == "rotation.create.asset"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.create_rotation_asset"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.create.asset"
    assert legacy.semantic_key == "rotation.create.asset"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_asset_update_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.update.asset",
        summary="Preview and update a global Rotation asset.",
        description="Governed staff-only Rotation asset catalog update.",
        owner_app="rotation",
        tags=("rotation", "asset", "catalog", "configuration", "update", "write"),
        audit_tags=("rotation:update_asset", "mcp:write", "catalog:global"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["asset_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_rotation_asset",),
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
                    name="update_rotation_asset",
                    description="update Rotation asset",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.update.asset"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_rotation_asset"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:update_asset",
        "mcp:write",
        "catalog:global",
    ]
    assert governed.semantic_key == "rotation.update.asset"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.update_rotation_asset"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.update.asset"
    assert legacy.semantic_key == "rotation.update.asset"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_asset_delete_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.delete.asset",
        summary="Preview and soft-delete a global Rotation asset.",
        description="Governed staff-only Rotation asset catalog soft delete.",
        owner_app="rotation",
        tags=("rotation", "asset", "catalog", "configuration", "delete", "write"),
        audit_tags=("rotation:delete_asset", "mcp:write", "catalog:global"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["asset_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("delete_rotation_asset",),
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
                    name="delete_rotation_asset",
                    description="delete Rotation asset",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.delete.asset"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["delete_rotation_asset"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:delete_asset",
        "mcp:write",
        "catalog:global",
    ]
    assert governed.semantic_key == "rotation.delete.asset"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.delete_rotation_asset"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.delete.asset"
    assert legacy.semantic_key == "rotation.delete.asset"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_rotation_default_asset_import_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="rotation.import.default_assets",
        summary="Preview and import the server-owned default Rotation assets.",
        description="Governed staff-only Rotation default asset import.",
        owner_app="rotation",
        tags=("rotation", "asset", "catalog", "configuration", "import", "write"),
        audit_tags=("rotation:import_default_assets", "mcp:write", "catalog:global"),
        input_schema={
            "type": "object",
            "properties": {
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("import_default_rotation_assets",),
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
                    name="import_default_rotation_assets",
                    description="import default Rotation assets",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.rotation.import.default_assets"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["import_default_rotation_assets"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "rotation:import_default_assets",
        "mcp:write",
        "catalog:global",
    ]
    assert governed.semantic_key == "rotation.import.default_assets"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.import_default_rotation_assets"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "rotation.import.default_assets"
    assert legacy.semantic_key == "rotation.import.default_assets"
    assert legacy.enabled_for_terminal is False
