# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_ai_provider."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_ai_provider_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.read.provider_catalog",
        summary="Read the AI provider catalog list.",
        description="Return the AI provider catalog used by operators.",
        owner_app="ai_provider",
        tags=("ai_provider", "provider", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_ai_providers",),
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
                    name="list_ai_providers",
                    description="ai provider catalog",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.read.provider_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "ai_provider.read.provider_catalog"
    assert governed.execution_target["replacement_for"] == ["list_ai_providers"]
    assert governed.semantic_key == "ai_provider.read.provider_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_ai_providers"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "ai_provider.read.provider_catalog"
    )
    assert legacy.semantic_key == "ai_provider.read.provider_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_ai_provider_detail_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.read.provider_detail",
        summary="Read a single AI provider configuration detail.",
        description="Return one configured AI provider entry used by operator workflows.",
        owner_app="ai_provider",
        tags=("ai_provider", "provider", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {"provider_id": {"type": "integer"}},
            "required": ["provider_id"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_ai_provider",),
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
                    name="get_ai_provider",
                    description="ai provider detail",
                    inputSchema={
                        "type": "object",
                        "properties": {"provider_id": {"type": "integer"}},
                    },
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.read.provider_detail"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "ai_provider.read.provider_detail"
    assert governed.execution_target["replacement_for"] == ["get_ai_provider"]
    assert governed.semantic_key == "ai_provider.read.provider_detail"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_ai_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "ai_provider.read.provider_detail"
    )
    assert legacy.semantic_key == "ai_provider.read.provider_detail"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_ai_provider_usage_logs_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.read.usage_logs",
        summary="Read AI provider usage logs.",
        description="Return recent AI provider usage log entries for operator audit workflows.",
        owner_app="ai_provider",
        tags=("ai_provider", "usage", "logs", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_ai_usage_logs",),
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
                    name="list_ai_usage_logs",
                    description="ai usage logs",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "provider_id": {"type": "integer"},
                            "status": {"type": "string"},
                        },
                    },
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.read.usage_logs"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "ai_provider.read.usage_logs"
    assert governed.execution_target["replacement_for"] == ["list_ai_usage_logs"]
    assert governed.semantic_key == "ai_provider.read.usage_logs"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_ai_usage_logs"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "ai_provider.read.usage_logs"
    assert legacy.semantic_key == "ai_provider.read.usage_logs"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_ai_provider_update_provider_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.update.provider",
        summary="Preview first, then update the AI provider config.",
        description="Governed write capability for AI provider config updates.",
        owner_app="ai_provider",
        tags=("ai_provider", "provider", "config", "update", "write"),
        audit_tags=("ai_provider:update_provider", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"provider_id": {"type": "integer"}},
            "required": ["provider_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_ai_provider",),
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
                    name="update_ai_provider",
                    description="ai provider update",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.update.provider"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_ai_provider"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "ai_provider:update_provider",
        "mcp:write",
    ]
    assert governed.semantic_key == "ai_provider.update.provider"

    legacy = by_key["mcp_tool.update_ai_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "ai_provider.update.provider"
    assert legacy.semantic_key == "ai_provider.update.provider"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_ai_provider_create_provider_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.create.provider",
        summary="Preview first, then create the AI provider config.",
        description="Governed write capability for AI provider config creation.",
        owner_app="ai_provider",
        tags=("ai_provider", "provider", "config", "create", "write"),
        audit_tags=("ai_provider:create_provider", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "provider_type": {"type": "string"}},
            "required": ["name", "provider_type"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_ai_provider",),
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
                    name="create_ai_provider",
                    description="ai provider create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.create.provider"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_ai_provider"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "ai_provider:create_provider",
        "mcp:write",
    ]
    assert governed.semantic_key == "ai_provider.create.provider"

    legacy = by_key["mcp_tool.create_ai_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "ai_provider.create.provider"
    assert legacy.semantic_key == "ai_provider.create.provider"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_ai_provider_toggle_provider_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="ai_provider.toggle.provider",
        summary="Preview first, then toggle the AI provider state.",
        description="Governed write capability for AI provider active-state toggles.",
        owner_app="ai_provider",
        tags=("ai_provider", "provider", "toggle", "active", "write"),
        audit_tags=("ai_provider:toggle_provider", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"provider_id": {"type": "integer"}},
            "required": ["provider_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("toggle_ai_provider",),
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
                    name="toggle_ai_provider",
                    description="ai provider toggle",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.ai_provider.toggle.provider"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["toggle_ai_provider"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "ai_provider:toggle_provider",
        "mcp:write",
    ]
    assert governed.semantic_key == "ai_provider.toggle.provider"

    legacy = by_key["mcp_tool.toggle_ai_provider"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "ai_provider.toggle.provider"
    assert legacy.semantic_key == "ai_provider.toggle.provider"
    assert legacy.enabled_for_terminal is False
