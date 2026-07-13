# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_strategy."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_strategy_execute_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.execute.run",
        summary="Preview first, then execute the strategy.",
        description="Governed write capability for strategy execution.",
        owner_app="strategy",
        tags=("strategy", "execution", "write"),
        audit_tags=("strategy:execute", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer"},
                "as_of_date": {"type": "string"},
            },
            "required": ["strategy_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("execute_strategy",),
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
                    name="execute_strategy",
                    description="strategy execute",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.execute.run"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["execute_strategy"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:execute",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.execute.run"

    legacy = by_key["mcp_tool.execute_strategy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.execute.run"
    assert legacy.semantic_key == "strategy.execute.run"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_bind_portfolio_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.bind.portfolio",
        summary="Preview first, then bind the strategy to the portfolio.",
        description="Governed write capability for strategy portfolio binding.",
        owner_app="strategy",
        tags=("strategy", "binding", "portfolio", "write"),
        audit_tags=("strategy:bind_portfolio", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "strategy_id": {"type": "integer"},
            },
            "required": ["portfolio_id", "strategy_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("bind_portfolio_strategy",),
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
                    name="bind_portfolio_strategy",
                    description="strategy portfolio bind",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.bind.portfolio"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["bind_portfolio_strategy"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:bind_portfolio",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.bind.portfolio"

    legacy = by_key["mcp_tool.bind_portfolio_strategy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.bind.portfolio"
    assert legacy.semantic_key == "strategy.bind.portfolio"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_unbind_portfolio_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.unbind.portfolio",
        summary="Preview first, then unbind the portfolio strategy.",
        description="Governed write capability for strategy portfolio unbinding.",
        owner_app="strategy",
        tags=("strategy", "unbinding", "portfolio", "write"),
        audit_tags=("strategy:unbind_portfolio", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
            },
            "required": ["portfolio_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("unbind_portfolio_strategy",),
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
                    name="unbind_portfolio_strategy",
                    description="strategy portfolio unbind",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.unbind.portfolio"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["unbind_portfolio_strategy"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:unbind_portfolio",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.unbind.portfolio"

    legacy = by_key["mcp_tool.unbind_portfolio_strategy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.unbind.portfolio"
    assert legacy.semantic_key == "strategy.unbind.portfolio"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_create_position_rule_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.create.position_rule",
        summary="Preview first, then create the strategy position rule.",
        description="Governed write capability for strategy position rule creation.",
        owner_app="strategy",
        tags=("strategy", "position_rule", "create", "write"),
        audit_tags=("strategy:create_position_rule", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["strategy_id", "name"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_position_rule",),
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
                    name="create_position_rule",
                    description="strategy create position rule",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.create.position_rule"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_position_rule"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:create_position_rule",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.create.position_rule"

    legacy = by_key["mcp_tool.create_position_rule"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.create.position_rule"
    assert legacy.semantic_key == "strategy.create.position_rule"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_update_position_rule_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.update.position_rule",
        summary="Preview first, then update the strategy position rule.",
        description="Governed write capability for strategy position rule update.",
        owner_app="strategy",
        tags=("strategy", "position_rule", "update", "write"),
        audit_tags=("strategy:update_position_rule", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer"},
                "updates": {"type": "object"},
            },
            "required": ["rule_id", "updates"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_position_rule",),
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
                    name="update_position_rule",
                    description="strategy update position rule",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.update.position_rule"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_position_rule"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:update_position_rule",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.update.position_rule"

    legacy = by_key["mcp_tool.update_position_rule"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.update.position_rule"
    assert legacy.semantic_key == "strategy.update.position_rule"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_create_ai_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.create.ai_config",
        summary="Preview first, then create the AI strategy config.",
        description="Governed write capability for AI strategy config creation.",
        owner_app="strategy",
        tags=("strategy", "ai_config", "create", "write"),
        audit_tags=("strategy:create_ai_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"strategy_id": {"type": "integer"}},
            "required": ["strategy_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_ai_strategy_config",),
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
                    name="create_ai_strategy_config",
                    description="strategy create ai config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.create.ai_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_ai_strategy_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:create_ai_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.create.ai_config"

    legacy = by_key["mcp_tool.create_ai_strategy_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.create.ai_config"
    assert legacy.semantic_key == "strategy.create.ai_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_create_strategy_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.create.strategy",
        summary="Preview first, then create the strategy.",
        description="Governed write capability for strategy creation.",
        owner_app="strategy",
        tags=("strategy", "create", "write"),
        audit_tags=("strategy:create_strategy", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "strategy_type": {"type": "string"},
                "description": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["name", "strategy_type", "description", "params"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_strategy",),
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
                    name="create_strategy",
                    description="strategy create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.create.strategy"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_strategy"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:create_strategy",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.create.strategy"

    legacy = by_key["mcp_tool.create_strategy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.create.strategy"
    assert legacy.semantic_key == "strategy.create.strategy"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_strategy_update_ai_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="strategy.update.ai_config",
        summary="Preview first, then update the AI strategy config.",
        description="Governed write capability for AI strategy config update.",
        owner_app="strategy",
        tags=("strategy", "ai_config", "update", "write"),
        audit_tags=("strategy:update_ai_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "updates": {"type": "object"},
            },
            "required": ["config_id", "updates"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_ai_strategy_config",),
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
                    name="update_ai_strategy_config",
                    description="strategy update ai config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.strategy.update.ai_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_ai_strategy_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "strategy:update_ai_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "strategy.update.ai_config"

    legacy = by_key["mcp_tool.update_ai_strategy_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "strategy.update.ai_config"
    assert legacy.semantic_key == "strategy.update.ai_config"
    assert legacy.enabled_for_terminal is False
