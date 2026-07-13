# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_simulated_trading."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_simulated_trading_submit_order_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.submit.simulated_order",
        summary="Preview first, then submit a simulated trading order.",
        description="Governed write capability for simulated trading order execution.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "execution", "write"),
        audit_tags=("simulated_trading:execute_trade", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "side": {"type": "string"},
                "quantity": {"type": "number"},
            },
            "required": ["account_id", "asset_code", "side", "quantity"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("execute_simulated_trade",),
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
                    name="execute_simulated_trade",
                    description="simulated trading order execute",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.submit.simulated_order"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["execute_simulated_trade"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:execute_trade",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.submit.simulated_order"

    legacy = by_key["mcp_tool.execute_simulated_trade"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "trading.submit.simulated_order"
    assert legacy.semantic_key == "trading.submit.simulated_order"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_close_position_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.close.simulated_position",
        summary="Preview first, then close a simulated trading position.",
        description="Governed write capability for simulated position close execution.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "close", "write"),
        audit_tags=("simulated_trading:close_position", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "asset_code": {"type": "string"},
            },
            "required": ["account_id", "asset_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("close_simulated_position",),
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
                    name="close_simulated_position",
                    description="simulated position close",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.close.simulated_position"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["close_simulated_position"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:close_position",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.close.simulated_position"

    legacy = by_key["mcp_tool.close_simulated_position"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "trading.close.simulated_position"
    )
    assert legacy.semantic_key == "trading.close.simulated_position"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_reset_account_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.reset.simulated_account",
        summary="Preview first, then reset a simulated trading account.",
        description="Governed write capability for simulated account reset.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "reset", "write"),
        audit_tags=("simulated_trading:reset_account", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "new_initial_capital": {"type": "number"},
            },
            "required": ["account_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("reset_simulated_account",),
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
                    name="reset_simulated_account",
                    description="simulated account reset",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.reset.simulated_account"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["reset_simulated_account"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:reset_account",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.reset.simulated_account"

    legacy = by_key["mcp_tool.reset_simulated_account"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "trading.reset.simulated_account"
    )
    assert legacy.semantic_key == "trading.reset.simulated_account"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_delete_account_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.delete.simulated_account",
        summary="Preview first, then delete a simulated trading account.",
        description="Governed write capability for simulated account deletion.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "account", "delete", "write"),
        audit_tags=("simulated_trading:delete_account", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
            },
            "required": ["account_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("delete_simulated_account",),
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
                    name="delete_simulated_account",
                    description="simulated account delete",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.delete.simulated_account"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["delete_simulated_account"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:delete_account",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.delete.simulated_account"

    legacy = by_key["mcp_tool.delete_simulated_account"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "trading.delete.simulated_account"
    )
    assert legacy.semantic_key == "trading.delete.simulated_account"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_batch_delete_account_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.delete.simulated_account_batch",
        summary="Preview first, then batch delete simulated trading accounts.",
        description="Governed write capability for simulated account batch deletion.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "account", "delete", "batch", "write"),
        audit_tags=("simulated_trading:delete_account_batch", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["account_ids"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("batch_delete_simulated_accounts",),
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
                    name="batch_delete_simulated_accounts",
                    description="simulated account batch delete",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.delete.simulated_account_batch"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["batch_delete_simulated_accounts"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:delete_account_batch",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.delete.simulated_account_batch"

    legacy = by_key["mcp_tool.batch_delete_simulated_accounts"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "trading.delete.simulated_account_batch"
    )
    assert legacy.semantic_key == "trading.delete.simulated_account_batch"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_create_account_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.create.simulated_account",
        summary="Preview first, then create a simulated trading account.",
        description="Governed write capability for simulated account creation.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "account", "create", "write"),
        audit_tags=("simulated_trading:create_account", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "initial_capital": {"type": "number"},
            },
            "required": ["account_name", "initial_capital"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_simulated_account",),
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
                    name="create_simulated_account",
                    description="simulated account create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.create.simulated_account"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_simulated_account"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:create_account",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.create.simulated_account"

    legacy = by_key["mcp_tool.create_simulated_account"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "trading.create.simulated_account"
    )
    assert legacy.semantic_key == "trading.create.simulated_account"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_auto_trading_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.start.simulated_auto_trading",
        summary="Preview first, then trigger simulated auto-trading.",
        description="Governed write capability for simulated auto-trading execution.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "auto_trading", "write"),
        audit_tags=("simulated_trading:auto_trading", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "trade_date": {"type": "string"},
                "account_ids": {"type": "array"},
            },
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("run_simulated_auto_trading",),
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
                    name="run_simulated_auto_trading",
                    description="simulated auto trading run",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.start.simulated_auto_trading"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["run_simulated_auto_trading"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:auto_trading",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.start.simulated_auto_trading"

    legacy = by_key["mcp_tool.run_simulated_auto_trading"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "trading.start.simulated_auto_trading"
    )
    assert legacy.semantic_key == "trading.start.simulated_auto_trading"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_simulated_trading_daily_inspection_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="trading.run.simulated_daily_inspection",
        summary="Preview first, then run simulated daily inspection.",
        description="Governed write capability for simulated daily inspection execution.",
        owner_app="simulated_trading",
        tags=("trading", "simulated", "inspection", "write"),
        audit_tags=("simulated_trading:daily_inspection", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "strategy_id": {"type": "integer"},
                "inspection_date": {"type": "string"},
                "auto_create_proposal": {"type": "boolean"},
            },
            "required": ["account_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("run_simulated_daily_inspection",),
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
                    name="run_simulated_daily_inspection",
                    description="simulated daily inspection run",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.trading.run.simulated_daily_inspection"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["run_simulated_daily_inspection"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "simulated_trading:daily_inspection",
        "mcp:write",
    ]
    assert governed.semantic_key == "trading.run.simulated_daily_inspection"

    legacy = by_key["mcp_tool.run_simulated_daily_inspection"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "trading.run.simulated_daily_inspection"
    )
    assert legacy.semantic_key == "trading.run.simulated_daily_inspection"
    assert legacy.enabled_for_terminal is False
