"""account write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="account.import.positions",
        title="Import Portfolio Positions",
        summary="Preview a portfolio position import, then confirm the actual import write.",
        description=(
            "Run the account position import in dry-run mode first, then require explicit "
            "confirmation before applying create/update/close changes to the target portfolio."
        ),
        owner_app="account",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="import_positions_json",
        tags=("account", "portfolio", "positions", "import", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "positions": {"type": "array"},
                "mode": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "positions"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "portfolio_id": {"type": "integer"},
                "mode": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "summary": {"type": "object"},
                "errors": {"type": "array"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"dry_run": True},
        confirmation_commit_arguments={"dry_run": False},
        idempotency="required",
        audit_tags=("account:import_positions", "mcp:write"),
        legacy_tool_names=("import_positions_json", "import_positions_csv"),
    ),
    CapabilityManifest(
        capability_key="account.import.transactions",
        title="Import Portfolio Transactions",
        summary="Preview a portfolio transaction import, then confirm the actual transaction write.",
        description=(
            "Run the transaction import in dry-run mode first, then require explicit "
            "confirmation before applying append/replace transaction changes."
        ),
        owner_app="account",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="import_transactions_json",
        tags=("account", "portfolio", "transactions", "import", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "transactions": {"type": "array"},
                "mode": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "transactions"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "portfolio_id": {"type": "integer"},
                "mode": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "summary": {"type": "object"},
                "errors": {"type": "array"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"dry_run": True},
        confirmation_commit_arguments={"dry_run": False},
        idempotency="required",
        audit_tags=("account:import_transactions", "mcp:write"),
        legacy_tool_names=("import_transactions_json", "import_transactions_csv"),
    ),
    CapabilityManifest(
        capability_key="account.import.capital_flows",
        title="Import Portfolio Capital Flows",
        summary="Preview a capital-flow import, then confirm the actual capital-flow write.",
        description=(
            "Run the capital-flow import in dry-run mode first, then require explicit "
            "confirmation before applying append/replace capital-flow changes."
        ),
        owner_app="account",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="import_capital_flows_json",
        tags=("account", "portfolio", "capital_flows", "import", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "capital_flows": {"type": "array"},
                "mode": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "capital_flows"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "portfolio_id": {"type": "integer"},
                "mode": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "summary": {"type": "object"},
                "errors": {"type": "array"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"dry_run": True},
        confirmation_commit_arguments={"dry_run": False},
        idempotency="required",
        audit_tags=("account:import_capital_flows", "mcp:write"),
        legacy_tool_names=("import_capital_flows_json", "import_capital_flows_csv"),
    ),
    CapabilityManifest(
        capability_key="account.import.broker_trades",
        title="Import Broker Trades",
        summary=(
            "Preview owner-scoped broker trades, then confirm ledger and recommendation updates."
        ),
        description=(
            "Submit structured broker executions to the canonical Account preview endpoint, "
            "review duplicate detection and row validation, then require explicit confirmation "
            "before importing transactions, updating positions, recording the import batch, "
            "and matching executions to recommendations."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_import_broker_trades",
        tags=("account", "broker", "trade", "ledger", "import", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "broker_name": {"type": "string"},
                "trades": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "traded_at": {"type": "string"},
                            "action": {"type": "string", "enum": ["buy", "sell"]},
                            "asset_code": {"type": "string"},
                            "shares": {"type": "number"},
                            "price": {"type": "number"},
                            "commission": {"type": "number"},
                            "stamp_duty": {"type": "number"},
                            "transfer_fee": {"type": "number"},
                            "external_trade_id": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": [
                            "traded_at",
                            "action",
                            "asset_code",
                            "shares",
                            "price",
                        ],
                        "additionalProperties": False,
                    },
                },
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "trades"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "total_rows": {"type": "integer"},
                "valid_rows": {"type": "integer"},
                "duplicate_rows": {"type": "integer"},
                "error_rows": {"type": "integer"},
                "imported_rows": {"type": "integer"},
                "skipped_rows": {"type": "integer"},
                "batch_id": {"type": ["integer", "null"]},
                "rows": {"type": "array"},
                "errors": {"type": "array"},
                "summary": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("account:import_broker_trades", "mcp:write"),
        legacy_tool_names=(
            "preview_broker_trades_csv",
            "import_broker_trades_csv",
            "preview_broker_trades_json",
            "import_broker_trades_json",
        ),
    ),
    CapabilityManifest(
        capability_key="account.create.position",
        title="Create Or Increase Portfolio Position",
        summary=(
            "Preview the owner-scoped portfolio ledger impact, then confirm the position write."
        ),
        description=(
            "Read the matching portfolio position through the canonical Account SDK, "
            "calculate the resulting quantity and weighted average cost, then require "
            "explicit confirmation before creating or increasing the unified-ledger position."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_create_position",
        tags=("account", "portfolio", "position", "ledger", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "quantity": {"type": "number"},
                "price": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "asset_code", "quantity", "price"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "quantity": {"type": "number"},
                "avg_cost": {"type": "number"},
                "current_price": {"type": "number"},
                "market_value": {"type": "number"},
                "profit_loss": {"type": "number"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("account:create_position", "mcp:write"),
        legacy_tool_names=("create_position",),
    ),
    CapabilityManifest(
        capability_key="account.create.unified_account",
        title="Create Unified Account",
        summary="Preview an owner-scoped real or simulated account, then confirm creation.",
        description=(
            "Validate the canonical account profile, inspect the authenticated user's "
            "same-type account catalog for name conflicts, then require explicit "
            "confirmation before creating the unified account through the Account SDK."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_create_unified_account",
        tags=("account", "unified_account", "real", "simulated", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "account_type": {
                    "type": "string",
                    "enum": ["real", "simulated"],
                },
                "initial_capital": {"type": "number"},
                "max_position_pct": {"type": "number"},
                "stop_loss_pct": {"type": ["number", "null"]},
                "commission_rate": {"type": "number"},
                "slippage_rate": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_name", "account_type", "initial_capital"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "account_name": {"type": "string"},
                "account_type": {"type": "string"},
                "initial_capital": {"type": "string"},
                "current_cash": {"type": "string"},
                "total_value": {"type": "string"},
                "auto_trading_enabled": {"type": "boolean"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("account:create_unified_account", "mcp:write"),
        legacy_tool_names=("create_account",),
    ),
    CapabilityManifest(
        capability_key="account.create.trading_cost_config",
        title="Create Trading Cost Config",
        summary="Preview portfolio context and trading cost inputs, then confirm creation of the trading cost config.",
        description=(
            "Load the target portfolio context and summarize the requested trading cost "
            "configuration first, then require explicit confirmation before creating the "
            "trading cost config."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_create_trading_cost_config",
        tags=("account", "portfolio", "trading_cost_config", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "commission_rate": {"type": "number"},
                "min_commission": {"type": "number"},
                "stamp_duty_rate": {"type": "number"},
                "transfer_fee_rate": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "min_commission"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "portfolio": {"type": "integer"},
                "commission_rate": {"type": "number"},
                "min_commission": {"type": "number"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("account:create_trading_cost_config", "mcp:write"),
        legacy_tool_names=("create_trading_cost_config",),
    ),
    CapabilityManifest(
        capability_key="account.update.trading_cost_config",
        title="Update Trading Cost Config",
        summary="Preview the current trading cost config and requested changes, then confirm updating the trading cost config.",
        description=(
            "Load the current trading cost config context and summarize the requested "
            "updates first, then require explicit confirmation before updating the "
            "trading cost config."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_update_trading_cost_config",
        tags=("account", "portfolio", "trading_cost_config", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "commission_rate": {"type": "number"},
                "min_commission": {"type": "number"},
                "stamp_duty_rate": {"type": "number"},
                "transfer_fee_rate": {"type": "number"},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "portfolio": {"type": "integer"},
                "commission_rate": {"type": "number"},
                "min_commission": {"type": "number"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("account:update_trading_cost_config", "mcp:write"),
        legacy_tool_names=("update_trading_cost_config",),
    ),
    CapabilityManifest(
        capability_key="account.update.macro_sizing_config",
        title="Update Macro Sizing Config",
        summary="Preview the active macro sizing config and requested changes, then confirm creation of a new active version.",
        description=(
            "Load the current macro sizing configuration and summarize the requested "
            "changes first, then require explicit confirmation before creating and "
            "activating a new configuration version through the canonical Account SDK."
        ),
        owner_app="account",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="account_update_macro_sizing_config",
        tags=("account", "macro", "position_sizing", "config", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "warning_factor": {"type": "number"},
                "regime_tiers_json": {"type": "array"},
                "pulse_tiers_json": {"type": "array"},
                "drawdown_tiers_json": {"type": "array"},
                "market_temperature_cold_factor": {"type": "number"},
                "market_temperature_warm_factor": {"type": "number"},
                "market_temperature_hot_factor": {"type": "number"},
                "market_temperature_overheat_factor": {"type": "number"},
                "market_temperature_extreme_factor": {"type": "number"},
                "block_new_position_on_extreme": {"type": "boolean"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "version": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "warning_factor": {"type": "number"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("account:update_macro_sizing_config", "mcp:write"),
        legacy_tool_names=("update_macro_sizing_config",),
    ),
]
