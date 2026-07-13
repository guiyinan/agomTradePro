# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_filter."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_filter_indicator_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="filter.read.indicator_catalog",
        summary="Read the available filter indicator catalog.",
        description="Return the available indicator list exposed by the filter service.",
        owner_app="filter",
        tags=("filter", "indicator", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_filters",),
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
                    name="list_filters", description="filter indicators", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.filter.read.indicator_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "filter.read.indicator_catalog"
    assert governed.execution_target["replacement_for"] == ["list_filters"]
    assert governed.semantic_key == "filter.read.indicator_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_filters"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "filter.read.indicator_catalog"
    assert legacy.semantic_key == "filter.read.indicator_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_filter_config_detail_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="filter.read.config_detail",
        summary="Read a single filter config detail.",
        description="Return one filter config entry resolved by indicator code or filter id.",
        owner_app="filter",
        tags=("filter", "config", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "filter_id": {"type": "integer"},
                "indicator_code": {"type": "string"},
            },
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_filter",),
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
                    name="get_filter",
                    description="filter config detail",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filter_id": {"type": "integer"},
                            "indicator_code": {"type": "string"},
                        },
                    },
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.filter.read.config_detail"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "filter.read.config_detail"
    assert governed.execution_target["replacement_for"] == ["get_filter"]
    assert governed.semantic_key == "filter.read.config_detail"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_filter"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "filter.read.config_detail"
    assert legacy.semantic_key == "filter.read.config_detail"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_filter_create_filter_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="filter.create.filter",
        summary="Preview first, then create a persisted filter run.",
        description="Governed write capability for filter run creation.",
        owner_app="filter",
        tags=("filter", "apply", "create", "write"),
        audit_tags=("filter:create_filter", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"indicator_code": {"type": "string"}},
            "required": ["indicator_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_filter",),
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
                    name="create_filter",
                    description="filter create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.filter.create.filter"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_filter"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "filter:create_filter",
        "mcp:write",
    ]
    assert governed.semantic_key == "filter.create.filter"

    legacy = by_key["mcp_tool.create_filter"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "filter.create.filter"
    assert legacy.semantic_key == "filter.create.filter"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_filter_update_filter_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="filter.update.filter",
        summary="Preview first, then update the filter config.",
        description="Governed write capability for filter config updates.",
        owner_app="filter",
        tags=("filter", "config", "update", "write"),
        audit_tags=("filter:update_filter", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"indicator_code": {"type": "string"}},
            "required": ["indicator_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_filter",),
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
                    name="update_filter",
                    description="filter update",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.filter.update.filter"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_filter"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "filter:update_filter",
        "mcp:write",
    ]
    assert governed.semantic_key == "filter.update.filter"

    legacy = by_key["mcp_tool.update_filter"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "filter.update.filter"
    assert legacy.semantic_key == "filter.update.filter"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_filter_delete_filter_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="filter.delete.filter",
        summary="Preview first, then delete the filter config override.",
        description="Governed write capability for filter config deletes.",
        owner_app="filter",
        tags=("filter", "config", "delete", "write"),
        audit_tags=("filter:delete_filter", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"indicator_code": {"type": "string"}},
            "required": ["indicator_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("delete_filter",),
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
                    name="delete_filter",
                    description="filter delete",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.filter.delete.filter"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["delete_filter"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "filter:delete_filter",
        "mcp:write",
    ]
    assert governed.semantic_key == "filter.delete.filter"

    legacy = by_key["mcp_tool.delete_filter"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "filter.delete.filter"
    assert legacy.semantic_key == "filter.delete.filter"
    assert legacy.enabled_for_terminal is False
