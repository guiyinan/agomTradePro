# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_data_center."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_data_center_provider_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.read.provider_catalog",
        summary="Read the data-center provider catalog list.",
        description="Return the data-center provider catalog used by operators.",
        owner_app="data_center",
        tags=("data_center", "provider", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_data_center_providers",),
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
                    name="list_data_center_providers",
                    description="data center provider catalog",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.read.provider_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "data_center.read.provider_catalog"
    assert governed.execution_target["replacement_for"] == ["list_data_center_providers"]
    assert governed.semantic_key == "data_center.read.provider_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_data_center_providers"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "data_center.read.provider_catalog"
    )
    assert legacy.semantic_key == "data_center.read.provider_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_provider_status_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.read.provider_status",
        summary="Read provider health and status across the data center.",
        description="Return the current provider health snapshot for the AgomTradePro data center.",
        owner_app="data_center",
        tags=("data_center", "operations", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_data_center_provider_status",),
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
                    name="get_data_center_provider_status",
                    description="data center provider status",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.read.provider_status"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "data_center.read.provider_status"
    assert governed.execution_target["replacement_for"] == ["get_data_center_provider_status"]
    assert governed.semantic_key == "data_center.read.provider_status"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_data_center_provider_status"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "data_center.read.provider_status"
    )
    assert legacy.semantic_key == "data_center.read.provider_status"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_macro_series_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.read.macro_series",
        summary="Read one normalized macro time series from the data center.",
        description="Return standardized macro indicator observations and provenance metadata.",
        owner_app="data_center",
        tags=("data_center", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["indicator_code"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("data_center_get_macro_series",),
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
                    name="data_center_get_macro_series",
                    description="data center macro series",
                    inputSchema={
                        "type": "object",
                        "properties": {"indicator_code": {"type": "string"}},
                    },
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.read.macro_series"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "data_center.read.macro_series"
    assert governed.execution_target["replacement_for"] == ["data_center_get_macro_series"]
    assert governed.semantic_key == "data_center.read.macro_series"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.data_center_get_macro_series"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.read.macro_series"
    assert legacy.semantic_key == "data_center.read.macro_series"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_indicator_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.read.indicator_catalog",
        summary="Read the normalized data-center indicator catalog.",
        description="Return indicator catalog metadata and unit-rule summaries.",
        owner_app="data_center",
        tags=("data_center", "catalog", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {"active_only": {"type": "boolean"}},
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("data_center_list_indicators",),
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
                    name="data_center_list_indicators",
                    description="data center indicator catalog",
                    inputSchema={
                        "type": "object",
                        "properties": {"active_only": {"type": "boolean"}},
                    },
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.read.indicator_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "data_center.read.indicator_catalog"
    assert governed.execution_target["replacement_for"] == ["data_center_list_indicators"]
    assert governed.semantic_key == "data_center.read.indicator_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.data_center_list_indicators"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "data_center.read.indicator_catalog"
    )
    assert legacy.semantic_key == "data_center.read.indicator_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_create_publisher_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.create.publisher",
        summary="Preview first, then create the publisher catalog entry.",
        description="Governed write capability for data-center publisher creation.",
        owner_app="data_center",
        tags=("data_center", "publisher", "catalog", "create", "write"),
        audit_tags=("data_center:create_publisher", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "canonical_name": {"type": "string"},
                "publisher_class": {"type": "string"},
            },
            "required": ["code", "canonical_name", "publisher_class"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_create_publisher",),
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
                    name="data_center_create_publisher",
                    description="data center create publisher",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.create.publisher"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_create_publisher"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:create_publisher",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.create.publisher"

    legacy = by_key["mcp_tool.data_center_create_publisher"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.create.publisher"
    assert legacy.semantic_key == "data_center.create.publisher"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_delete_publisher_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.delete.publisher",
        summary="Preview first, then delete the publisher catalog entry.",
        description="Governed write capability for data-center publisher deletion.",
        owner_app="data_center",
        tags=("data_center", "publisher", "catalog", "delete", "write"),
        audit_tags=("data_center:delete_publisher", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "publisher_code": {"type": "string"},
            },
            "required": ["publisher_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_delete_publisher",),
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
                    name="data_center_delete_publisher",
                    description="data center delete publisher",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.delete.publisher"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_delete_publisher"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:delete_publisher",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.delete.publisher"

    legacy = by_key["mcp_tool.data_center_delete_publisher"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.delete.publisher"
    assert legacy.semantic_key == "data_center.delete.publisher"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_create_indicator_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.create.indicator",
        summary="Preview first, then create the indicator catalog entry.",
        description="Governed write capability for data-center indicator creation.",
        owner_app="data_center",
        tags=("data_center", "indicator", "catalog", "create", "write"),
        audit_tags=("data_center:create_indicator", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name_cn": {"type": "string"},
            },
            "required": ["code", "name_cn"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_create_indicator",),
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
                    name="data_center_create_indicator",
                    description="data center create indicator",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.create.indicator"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_create_indicator"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:create_indicator",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.create.indicator"

    legacy = by_key["mcp_tool.data_center_create_indicator"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.create.indicator"
    assert legacy.semantic_key == "data_center.create.indicator"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_delete_indicator_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.delete.indicator",
        summary="Preview first, then delete the indicator catalog entry.",
        description="Governed write capability for data-center indicator deletion.",
        owner_app="data_center",
        tags=("data_center", "indicator", "catalog", "delete", "write"),
        audit_tags=("data_center:delete_indicator", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_delete_indicator",),
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
                    name="data_center_delete_indicator",
                    description="data center delete indicator",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.delete.indicator"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_delete_indicator"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:delete_indicator",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.delete.indicator"

    legacy = by_key["mcp_tool.data_center_delete_indicator"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.delete.indicator"
    assert legacy.semantic_key == "data_center.delete.indicator"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_create_indicator_unit_rule_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.create.indicator_unit_rule",
        summary="Preview first, then create the indicator unit rule.",
        description="Governed write capability for data-center indicator unit-rule creation.",
        owner_app="data_center",
        tags=("data_center", "indicator", "unit_rule", "create", "write"),
        audit_tags=("data_center:create_indicator_unit_rule", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "dimension_key": {"type": "string"},
            },
            "required": ["indicator_code", "dimension_key"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_create_indicator_unit_rule",),
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
                    name="data_center_create_indicator_unit_rule",
                    description="data center create indicator unit rule",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.create.indicator_unit_rule"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "data_center_create_indicator_unit_rule"
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:create_indicator_unit_rule",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.create.indicator_unit_rule"

    legacy = by_key["mcp_tool.data_center_create_indicator_unit_rule"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "data_center.create.indicator_unit_rule"
    )
    assert legacy.semantic_key == "data_center.create.indicator_unit_rule"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_delete_indicator_unit_rule_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.delete.indicator_unit_rule",
        summary="Preview first, then delete the indicator unit rule.",
        description="Governed write capability for data-center indicator unit-rule deletion.",
        owner_app="data_center",
        tags=("data_center", "indicator", "unit_rule", "delete", "write"),
        audit_tags=("data_center:delete_indicator_unit_rule", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
            },
            "required": ["indicator_code", "rule_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_delete_indicator_unit_rule",),
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
                    name="data_center_delete_indicator_unit_rule",
                    description="data center delete indicator unit rule",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.delete.indicator_unit_rule"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "data_center_delete_indicator_unit_rule"
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:delete_indicator_unit_rule",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.delete.indicator_unit_rule"

    legacy = by_key["mcp_tool.data_center_delete_indicator_unit_rule"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "data_center.delete.indicator_unit_rule"
    )
    assert legacy.semantic_key == "data_center.delete.indicator_unit_rule"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_update_indicator_unit_rule_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.update.indicator_unit_rule",
        summary="Preview first, then update the indicator unit rule.",
        description="Governed write capability for data-center indicator unit-rule updates.",
        owner_app="data_center",
        tags=("data_center", "indicator", "unit_rule", "update", "write"),
        audit_tags=("data_center:update_indicator_unit_rule", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
            },
            "required": ["indicator_code", "rule_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_update_indicator_unit_rule",),
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
                    name="data_center_update_indicator_unit_rule",
                    description="data center update indicator unit rule",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.update.indicator_unit_rule"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "data_center_update_indicator_unit_rule"
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:update_indicator_unit_rule",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.update.indicator_unit_rule"

    legacy = by_key["mcp_tool.data_center_update_indicator_unit_rule"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "data_center.update.indicator_unit_rule"
    )
    assert legacy.semantic_key == "data_center.update.indicator_unit_rule"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_start_sync_job_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.start.sync_job",
        summary="Preview first, then start the selected data-center sync job.",
        description="Governed write capability for starting a data-center sync job.",
        owner_app="data_center",
        tags=("data_center", "sync", "job", "macro", "start", "write"),
        audit_tags=("data_center:start_sync_job", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "job_kind": {"type": "string"},
                "provider_id": {"type": "integer"},
                "indicator_code": {"type": "string"},
                "asset_code": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["job_kind", "provider_id"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=(
            "data_center_sync_macro",
            "data_center_sync_capital_flows",
            "data_center_sync_news",
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
                    name="data_center_sync_macro",
                    description="data center sync macro",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="data_center_sync_capital_flows",
                    description="data center sync capital flows",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="data_center_sync_news",
                    description="data center sync news",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.start.sync_job"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "data_center_sync_macro",
        "data_center_sync_capital_flows",
        "data_center_sync_news",
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:start_sync_job",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.start.sync_job"

    legacy = by_key["mcp_tool.data_center_sync_macro"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.start.sync_job"
    assert legacy.semantic_key == "data_center.start.sync_job"
    assert legacy.enabled_for_terminal is False

    capital_flows_legacy = by_key["mcp_tool.data_center_sync_capital_flows"]
    assert capital_flows_legacy.execution_target["type"] == "mcp_tool"
    assert (
        capital_flows_legacy.execution_target["replacement_capability_key"]
        == "data_center.start.sync_job"
    )
    assert capital_flows_legacy.semantic_key == "data_center.start.sync_job"
    assert capital_flows_legacy.enabled_for_terminal is False

    news_legacy = by_key["mcp_tool.data_center_sync_news"]
    assert news_legacy.execution_target["type"] == "mcp_tool"
    assert (
        news_legacy.execution_target["replacement_capability_key"] == "data_center.start.sync_job"
    )
    assert news_legacy.semantic_key == "data_center.start.sync_job"
    assert news_legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_update_publisher_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.update.publisher",
        summary="Preview first, then update the publisher catalog entry.",
        description="Governed write capability for data-center publisher updates.",
        owner_app="data_center",
        tags=("data_center", "publisher", "catalog", "update", "write"),
        audit_tags=("data_center:update_publisher", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"publisher_code": {"type": "string"}},
            "required": ["publisher_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_update_publisher",),
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
                    name="data_center_update_publisher",
                    description="data center update publisher",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.update.publisher"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_update_publisher"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:update_publisher",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.update.publisher"

    legacy = by_key["mcp_tool.data_center_update_publisher"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.update.publisher"
    assert legacy.semantic_key == "data_center.update.publisher"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_data_center_update_indicator_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="data_center.update.indicator",
        summary="Preview first, then update the indicator catalog entry.",
        description="Governed write capability for data-center indicator updates.",
        owner_app="data_center",
        tags=("data_center", "indicator", "catalog", "update", "write"),
        audit_tags=("data_center:update_indicator", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"indicator_code": {"type": "string"}},
            "required": ["indicator_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("data_center_update_indicator",),
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
                    name="data_center_update_indicator",
                    description="data center update indicator",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.data_center.update.indicator"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["data_center_update_indicator"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "data_center:update_indicator",
        "mcp:write",
    ]
    assert governed.semantic_key == "data_center.update.indicator"

    legacy = by_key["mcp_tool.data_center_update_indicator"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "data_center.update.indicator"
    assert legacy.semantic_key == "data_center.update.indicator"
    assert legacy.enabled_for_terminal is False
