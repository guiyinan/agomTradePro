# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_account."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_account_import_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.import.positions",
        summary="Preview first, then import portfolio positions.",
        description="Governed write capability for account position import.",
        owner_app="account",
        tags=("account", "portfolio", "positions", "import", "write"),
        audit_tags=("account:import_positions", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"portfolio_id": {"type": "integer"}, "positions": {"type": "array"}},
            "required": ["portfolio_id", "positions"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("import_positions_json", "import_positions_csv"),
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
                    name="import_positions_json",
                    description="positions import",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="import_positions_csv",
                    description="positions CSV transport",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.import.positions"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "import_positions_json",
        "import_positions_csv",
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "account:import_positions",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.import.positions"

    for legacy_key in ("mcp_tool.import_positions_json", "mcp_tool.import_positions_csv"):
        legacy = by_key[legacy_key]
        assert legacy.execution_target["type"] == "mcp_tool"
        assert legacy.execution_target["replacement_capability_key"] == "account.import.positions"
        assert legacy.semantic_key == "account.import.positions"
        assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_import_transactions_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.import.transactions",
        summary="Preview first, then import portfolio transactions.",
        description="Governed write capability for account transaction import.",
        owner_app="account",
        tags=("account", "portfolio", "transactions", "import", "write"),
        audit_tags=("account:import_transactions", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "transactions": {"type": "array"},
            },
            "required": ["portfolio_id", "transactions"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("import_transactions_json", "import_transactions_csv"),
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
                    name="import_transactions_json",
                    description="transactions import",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="import_transactions_csv",
                    description="transactions CSV transport",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.import.transactions"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "import_transactions_json",
        "import_transactions_csv",
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "account:import_transactions",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.import.transactions"

    for legacy_key in (
        "mcp_tool.import_transactions_json",
        "mcp_tool.import_transactions_csv",
    ):
        legacy = by_key[legacy_key]
        assert legacy.execution_target["type"] == "mcp_tool"
        assert (
            legacy.execution_target["replacement_capability_key"] == "account.import.transactions"
        )
        assert legacy.semantic_key == "account.import.transactions"
        assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_import_capital_flows_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.import.capital_flows",
        summary="Preview first, then import portfolio capital flows.",
        description="Governed write capability for account capital-flow import.",
        owner_app="account",
        tags=("account", "portfolio", "capital_flows", "import", "write"),
        audit_tags=("account:import_capital_flows", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "capital_flows": {"type": "array"},
            },
            "required": ["portfolio_id", "capital_flows"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("import_capital_flows_json", "import_capital_flows_csv"),
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
                    name="import_capital_flows_json",
                    description="capital flows import",
                    inputSchema={},
                ),
                SimpleNamespace(
                    name="import_capital_flows_csv",
                    description="capital flows CSV transport",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.import.capital_flows"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == [
        "import_capital_flows_json",
        "import_capital_flows_csv",
    ]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "account:import_capital_flows",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.import.capital_flows"

    for legacy_key in (
        "mcp_tool.import_capital_flows_json",
        "mcp_tool.import_capital_flows_csv",
    ):
        legacy = by_key[legacy_key]
        assert legacy.execution_target["type"] == "mcp_tool"
        assert (
            legacy.execution_target["replacement_capability_key"] == "account.import.capital_flows"
        )
        assert legacy.semantic_key == "account.import.capital_flows"
        assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_import_broker_trades_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    legacy_tool_names = (
        "preview_broker_trades_csv",
        "import_broker_trades_csv",
        "preview_broker_trades_json",
        "import_broker_trades_json",
    )
    governed_manifest = SimpleNamespace(
        capability_key="account.import.broker_trades",
        summary="Preview first, then import broker trades.",
        description="Governed write capability for owner-scoped broker trade import.",
        owner_app="account",
        tags=("account", "broker", "trade", "import", "write"),
        audit_tags=("account:import_broker_trades", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "trades": {"type": "array"},
            },
            "required": ["portfolio_id", "trades"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=legacy_tool_names,
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
                *[
                    SimpleNamespace(name=name, description=name, inputSchema={})
                    for name in legacy_tool_names
                ],
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.account.import.broker_trades"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == list(legacy_tool_names)
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "account:import_broker_trades",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.import.broker_trades"

    for tool_name in legacy_tool_names:
        legacy = by_key[f"mcp_tool.{tool_name}"]
        assert (
            legacy.execution_target["replacement_capability_key"] == "account.import.broker_trades"
        )
        assert legacy.semantic_key == "account.import.broker_trades"
        assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_unified_account_create_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.create.unified_account",
        summary="Preview first, then create a unified account.",
        description="Governed owner-scoped unified account creation.",
        owner_app="account",
        tags=("account", "unified_account", "real", "simulated", "create", "write"),
        audit_tags=("account:create_unified_account", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "account_type": {"type": "string"},
                "initial_capital": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_name", "account_type", "initial_capital"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_account",),
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
                    name="create_account",
                    description="unified account create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.create.unified_account"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_account"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "account:create_unified_account",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.create.unified_account"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.create_account"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == (
        "account.create.unified_account"
    )
    assert legacy.semantic_key == "account.create.unified_account"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_create_position_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.create.position",
        summary="Preview first, then create or increase a portfolio ledger position.",
        description="Governed write capability for owner-scoped portfolio position creation.",
        owner_app="account",
        tags=("account", "portfolio", "position", "ledger", "create", "write"),
        audit_tags=("account:create_position", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "quantity": {"type": "number"},
                "price": {"type": "number"},
            },
            "required": ["portfolio_id", "asset_code", "quantity", "price"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_position",),
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
                    name="create_position",
                    description="account create position",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.create.position"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_position"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "account:create_position",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.create.position"

    legacy = by_key["mcp_tool.create_position"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "account.create.position"
    assert legacy.semantic_key == "account.create.position"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_create_trading_cost_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.create.trading_cost_config",
        summary="Preview first, then create the trading cost config.",
        description="Governed write capability for trading cost config creation.",
        owner_app="account",
        tags=("account", "portfolio", "trading_cost_config", "create", "write"),
        audit_tags=("account:create_trading_cost_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"portfolio_id": {"type": "integer"}},
            "required": ["portfolio_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_trading_cost_config",),
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
                    name="create_trading_cost_config",
                    description="account create trading cost config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.create.trading_cost_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_trading_cost_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "account:create_trading_cost_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.create.trading_cost_config"

    legacy = by_key["mcp_tool.create_trading_cost_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "account.create.trading_cost_config"
    )
    assert legacy.semantic_key == "account.create.trading_cost_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_update_trading_cost_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.update.trading_cost_config",
        summary="Preview first, then update the trading cost config.",
        description="Governed write capability for trading cost config update.",
        owner_app="account",
        tags=("account", "portfolio", "trading_cost_config", "update", "write"),
        audit_tags=("account:update_trading_cost_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"config_id": {"type": "integer"}},
            "required": ["config_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_trading_cost_config",),
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
                    name="update_trading_cost_config",
                    description="account update trading cost config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.update.trading_cost_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_trading_cost_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "account:update_trading_cost_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.update.trading_cost_config"

    legacy = by_key["mcp_tool.update_trading_cost_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "account.update.trading_cost_config"
    )
    assert legacy.semantic_key == "account.update.trading_cost_config"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_account_update_macro_sizing_config_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="account.update.macro_sizing_config",
        summary="Preview first, then create a new active macro sizing config version.",
        description="Governed write capability for macro sizing config updates.",
        owner_app="account",
        tags=("account", "macro", "position_sizing", "config", "update", "write"),
        audit_tags=("account:update_macro_sizing_config", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"warning_factor": {"type": "number"}},
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_macro_sizing_config",),
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
                    name="update_macro_sizing_config",
                    description="account update macro sizing config",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.account.update.macro_sizing_config"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_macro_sizing_config"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "account:update_macro_sizing_config",
        "mcp:write",
    ]
    assert governed.semantic_key == "account.update.macro_sizing_config"

    legacy = by_key["mcp_tool.update_macro_sizing_config"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "account.update.macro_sizing_config"
    )
    assert legacy.semantic_key == "account.update.macro_sizing_config"
    assert legacy.enabled_for_terminal is False
