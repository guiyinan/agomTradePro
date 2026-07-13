"""simulated_trading write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="trading.submit.simulated_order",
        title="Submit Simulated Trading Order",
        summary="Preview account and position state, then confirm execution of the simulated trading order.",
        description=(
            "Load the target simulated account and related position context first, then require "
            "explicit confirmation before executing the simulated trading order."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_submit_simulated_order",
        tags=("trading", "simulated", "execution", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "side": {"type": "string"},
                "quantity": {"type": "number"},
                "price": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "asset_code", "side", "quantity"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "order_id": {},
                "trade_id": {},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:execute_trade", "mcp:write"),
        legacy_tool_names=("execute_simulated_trade",),
    ),
    CapabilityManifest(
        capability_key="trading.close.simulated_position",
        title="Close Simulated Trading Position",
        summary="Preview the current position state, then confirm closing the simulated position.",
        description=(
            "Load the target simulated account and matching position first, then require "
            "explicit confirmation before closing the simulated trading position."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_close_simulated_position",
        tags=("trading", "simulated", "close", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "order_id": {},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:close_position", "mcp:write"),
        legacy_tool_names=("close_simulated_position",),
    ),
    CapabilityManifest(
        capability_key="trading.reset.simulated_account",
        title="Reset Simulated Trading Account",
        summary="Preview current account state, then confirm resetting the simulated account.",
        description=(
            "Load the target simulated account summary first, then require explicit "
            "confirmation before resetting the simulated account capital and state."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_reset_simulated_account",
        tags=("trading", "simulated", "reset", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "new_initial_capital": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "account_id": {"type": "integer"},
                "new_initial_capital": {"type": "number"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:reset_account", "mcp:write"),
        legacy_tool_names=("reset_simulated_account",),
    ),
    CapabilityManifest(
        capability_key="trading.delete.simulated_account",
        title="Delete Simulated Trading Account",
        summary="Preview current account state, then confirm deleting the simulated account.",
        description=(
            "Load the target simulated account summary first, then require explicit "
            "confirmation before deleting the simulated account and its related records."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_delete_simulated_account",
        tags=("trading", "simulated", "account", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "account_id": {"type": "integer"},
                "account_name": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:delete_account", "mcp:write"),
        legacy_tool_names=("delete_simulated_account",),
    ),
    CapabilityManifest(
        capability_key="trading.delete.simulated_account_batch",
        title="Batch Delete Simulated Trading Accounts",
        summary="Preview the requested simulated account batch, then confirm batch deletion.",
        description=(
            "Load the target simulated account batch first, surface partial-failure risk "
            "for missing or inaccessible accounts, then require explicit confirmation "
            "before submitting the real batch delete request."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_delete_simulated_account_batch",
        tags=("trading", "simulated", "account", "delete", "batch", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                },
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_ids"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "requested_count": {"type": "integer"},
                "deleted_count": {"type": "integer"},
                "deleted_account_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "deleted_account_names": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "failed": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:delete_account_batch", "mcp:write"),
        legacy_tool_names=("batch_delete_simulated_accounts",),
    ),
    CapabilityManifest(
        capability_key="trading.create.simulated_account",
        title="Create Simulated Trading Account",
        summary="Preview the simulated account settings, then confirm account creation.",
        description=(
            "Validate the requested simulated account profile first, surface the "
            "default risk settings and possible same-name overlaps, then require "
            "explicit confirmation before creating the simulated account."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_create_simulated_account",
        tags=("trading", "simulated", "account", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_name": {"type": "string"},
                "initial_capital": {"type": "number"},
                "max_position_pct": {"type": "number"},
                "stop_loss_pct": {"type": "number"},
                "commission_rate": {"type": "number"},
                "slippage_rate": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_name", "initial_capital"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "id": {"type": "integer"},
                "account_name": {"type": "string"},
                "account_type": {"type": "string"},
                "initial_capital": {"type": "number"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:create_account", "mcp:write"),
        legacy_tool_names=("create_simulated_account",),
    ),
    CapabilityManifest(
        capability_key="trading.start.simulated_auto_trading",
        title="Start Simulated Auto Trading",
        summary="Preview the target trade date and account scope, then confirm auto-trading execution.",
        description=(
            "Load the target trade date and affected simulated accounts first, then require "
            "explicit confirmation before triggering simulated auto-trading execution."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_start_simulated_auto_trading",
        tags=("trading", "simulated", "auto_trading", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "trade_date": {"type": "string"},
                "account_ids": {"type": "array", "items": {"type": "integer"}},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "trade_date": {"type": "string"},
                "account_ids": {"type": "array"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:auto_trading", "mcp:write"),
        legacy_tool_names=("run_simulated_auto_trading",),
    ),
    CapabilityManifest(
        capability_key="trading.run.simulated_daily_inspection",
        title="Run Simulated Daily Inspection",
        summary="Preview the inspection scope, then confirm execution of simulated daily inspection.",
        description=(
            "Load the target simulated account and inspection parameters first, then require "
            "explicit confirmation before running the simulated daily inspection."
        ),
        owner_app="simulated_trading",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="trading_run_simulated_daily_inspection",
        tags=("trading", "simulated", "inspection", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "strategy_id": {"type": "integer"},
                "inspection_date": {"type": "string"},
                "auto_create_proposal": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "account_id": {"type": "integer"},
                "inspection_date": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("simulated_trading:daily_inspection", "mcp:write"),
        legacy_tool_names=("run_simulated_daily_inspection",),
    ),
]
