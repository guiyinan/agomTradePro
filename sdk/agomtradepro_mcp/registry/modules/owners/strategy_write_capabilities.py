"""strategy write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="strategy.execute.run",
        title="Execute Strategy",
        summary="Preview strategy context and execution date, then confirm strategy execution.",
        description=(
            "Load the target strategy context first, then require explicit confirmation "
            "before executing the strategy and generating fresh results."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_execute_run",
        tags=("strategy", "execution", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer"},
                "as_of_date": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["strategy_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "strategy_id": {"type": "integer"},
                "signals_created": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:execute", "mcp:write"),
        legacy_tool_names=("execute_strategy",),
    ),
    CapabilityManifest(
        capability_key="strategy.bind.portfolio",
        title="Bind Strategy To Portfolio",
        summary="Preview portfolio and strategy context, then confirm binding the strategy to the portfolio.",
        description=(
            "Load the target portfolio and strategy context first, then require explicit "
            "confirmation before activating the strategy binding for that portfolio."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_bind_portfolio",
        tags=("strategy", "binding", "portfolio", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "strategy_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "strategy_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "portfolio_id": {"type": "integer"},
                "strategy_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:bind_portfolio", "mcp:write"),
        legacy_tool_names=("bind_portfolio_strategy",),
    ),
    CapabilityManifest(
        capability_key="strategy.unbind.portfolio",
        title="Unbind Strategy From Portfolio",
        summary="Preview portfolio context, then confirm unbinding the active strategy from the portfolio.",
        description=(
            "Load the target portfolio context first, then require explicit confirmation "
            "before deactivating the portfolio's active strategy binding."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_unbind_portfolio",
        tags=("strategy", "unbinding", "portfolio", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "portfolio_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:unbind_portfolio", "mcp:write"),
        legacy_tool_names=("unbind_portfolio_strategy",),
    ),
    CapabilityManifest(
        capability_key="strategy.create.position_rule",
        title="Create Strategy Position Rule",
        summary="Preview strategy context and rule definition, then confirm creation of the position rule.",
        description=(
            "Load the target strategy context and summarize the requested position rule "
            "definition first, then require explicit confirmation before creating the "
            "position rule."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_create_position_rule",
        tags=("strategy", "position_rule", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer"},
                "name": {"type": "string"},
                "buy_price_expr": {"type": "string"},
                "sell_price_expr": {"type": "string"},
                "stop_loss_expr": {"type": "string"},
                "take_profit_expr": {"type": "string"},
                "position_size_expr": {"type": "string"},
                "buy_condition_expr": {"type": "string"},
                "sell_condition_expr": {"type": "string"},
                "description": {"type": "string"},
                "price_precision": {"type": "integer"},
                "variables_schema": {"type": "array"},
                "metadata": {"type": "object"},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "strategy_id",
                "name",
                "buy_price_expr",
                "sell_price_expr",
                "stop_loss_expr",
                "take_profit_expr",
                "position_size_expr",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "strategy": {"type": "integer"},
                "name": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:create_position_rule", "mcp:write"),
        legacy_tool_names=("create_position_rule",),
    ),
    CapabilityManifest(
        capability_key="strategy.update.position_rule",
        title="Update Strategy Position Rule",
        summary="Preview the current position rule and requested changes, then confirm updating the rule.",
        description=(
            "Load the current position rule context and summarize the requested updates "
            "first, then require explicit confirmation before updating the position rule."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_update_position_rule",
        tags=("strategy", "position_rule", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer"},
                "updates": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["rule_id", "updates"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "strategy": {"type": "integer"},
                "name": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:update_position_rule", "mcp:write"),
        legacy_tool_names=("update_position_rule",),
    ),
    CapabilityManifest(
        capability_key="strategy.create.ai_config",
        title="Create Strategy AI Config",
        summary="Preview strategy context and AI config inputs, then confirm creation of the AI strategy config.",
        description=(
            "Load the target strategy context and summarize the requested AI config payload "
            "first, then require explicit confirmation before creating the AI strategy config."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_create_ai_config",
        tags=("strategy", "ai_config", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer"},
                "prompt_template_id": {"type": "integer"},
                "chain_config_id": {"type": "integer"},
                "ai_provider_id": {"type": "integer"},
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer"},
                "approval_mode": {"type": "string"},
                "confidence_threshold": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["strategy_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "strategy": {"type": "integer"},
                "approval_mode": {"type": "string"},
                "confidence_threshold": {"type": "number"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:create_ai_config", "mcp:write"),
        legacy_tool_names=("create_ai_strategy_config",),
    ),
    CapabilityManifest(
        capability_key="strategy.create.strategy",
        title="Create Strategy",
        summary="Preview strategy definition inputs, then confirm creation of the strategy.",
        description=(
            "Summarize the requested strategy definition first, then require explicit "
            "confirmation before creating the strategy."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_create_strategy",
        tags=("strategy", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "strategy_type": {"type": "string"},
                "description": {"type": "string"},
                "params": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["name", "strategy_type", "description", "params"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "strategy_type": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:create_strategy", "mcp:write"),
        legacy_tool_names=("create_strategy",),
    ),
    CapabilityManifest(
        capability_key="strategy.update.ai_config",
        title="Update Strategy AI Config",
        summary="Preview the current AI strategy config and requested changes, then confirm updating the AI strategy config.",
        description=(
            "Load the current AI strategy config context and summarize the requested updates "
            "first, then require explicit confirmation before updating the AI strategy config."
        ),
        owner_app="strategy",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="strategy_update_ai_config",
        tags=("strategy", "ai_config", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "updates": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id", "updates"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "strategy": {"type": "integer"},
                "approval_mode": {"type": "string"},
                "confidence_threshold": {"type": "number"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("strategy:update_ai_config", "mcp:write"),
        legacy_tool_names=("update_ai_strategy_config",),
    ),
]
