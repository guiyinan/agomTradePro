"""strategy read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="strategy.read.catalog",
        title="Strategy Catalog",
        summary="Read the persisted strategy catalog.",
        description=(
            "Return a bounded catalog of persisted strategies using the canonical Strategy "
            "GET endpoint. Filtering uses the real strategy_type and is_active API fields; "
            "the read does not execute strategies or change activation state."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_catalog",
        tags=("strategy", "catalog", "configuration", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_type": {"type": ["string", "null"], "minLength": 1},
                "is_active": {"type": ["boolean", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "strategies": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["strategies", "total_count"],
        },
        legacy_tool_names=("list_strategies",),
    ),
    CapabilityManifest(
        capability_key="strategy.read.detail",
        title="Strategy Detail",
        summary="Read one persisted strategy definition.",
        description=(
            "Return one persisted strategy and its read-only detail projection from the "
            "canonical Strategy GET endpoint without executing or updating the strategy."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_detail",
        tags=("strategy", "detail", "configuration", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "strategy": {"type": "object"},
            },
            "required": ["strategy"],
        },
        legacy_tool_names=("get_strategy",),
    ),
    CapabilityManifest(
        capability_key="strategy.read.ai_config_catalog",
        title="AI Strategy Configuration Catalog",
        summary="Read AI execution configurations for visible strategies.",
        description=(
            "Return a bounded owner/staff-scoped catalog of persisted AI strategy "
            "configurations without creating or updating strategy execution settings."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_ai_config_catalog",
        tags=("strategy", "ai", "configuration", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": ["integer", "null"], "minimum": 1},
                "approval_mode": {
                    "type": ["string", "null"],
                    "enum": ["always", "conditional", "auto", None],
                },
                "ai_provider_id": {"type": ["integer", "null"], "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "configs": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["configs", "total_count"],
        },
        legacy_tool_names=("list_ai_strategy_configs",),
    ),
    CapabilityManifest(
        capability_key="strategy.read.ai_config_detail",
        title="AI Strategy Configuration Detail",
        summary="Read the AI execution configuration for one visible strategy.",
        description=(
            "Return the persisted AI configuration for one owner/staff-scoped strategy, "
            "or an explicit not-configured result, without creating defaults."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_ai_config_detail",
        tags=("strategy", "ai", "configuration", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
                "exists": {"type": "boolean"},
                "config": {"type": ["object", "null"]},
            },
            "required": ["strategy_id", "exists", "config"],
        },
        legacy_tool_names=("get_strategy_ai_config",),
    ),
    CapabilityManifest(
        capability_key="strategy.read.position_rule_catalog",
        title="Strategy Position Rule Catalog",
        summary="Read position-management rules for visible strategies.",
        description=(
            "Return a bounded owner/staff-scoped catalog of persisted position-management "
            "rules without evaluating, creating, updating, enabling, or disabling rules."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_position_rule_catalog",
        tags=("strategy", "position", "rule", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": ["integer", "null"], "minimum": 1},
                "is_active": {"type": ["boolean", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "rules": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["rules", "total_count"],
        },
        legacy_tool_names=("list_position_rules",),
    ),
    CapabilityManifest(
        capability_key="strategy.read.position_rule_detail",
        title="Strategy Position Rule Detail",
        summary="Read the position-management rule bound to one visible strategy.",
        description=(
            "Return the persisted position-management rule for an owner/staff-scoped "
            "strategy without evaluating or modifying the rule."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_read_position_rule_detail",
        tags=("strategy", "position", "rule", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
            },
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
                "rule": {"type": "object"},
            },
            "required": ["strategy_id", "rule"],
        },
        legacy_tool_names=("get_strategy_position_rule",),
    ),
    CapabilityManifest(
        capability_key="strategy.compute.position_rule",
        title="Strategy Position Rule Calculation",
        summary="Calculate position guidance with one visible persisted rule.",
        description=(
            "Evaluate one owner/staff-scoped active position-management rule against "
            "caller-supplied context. The canonical POST endpoint only parses validated "
            "expressions and returns calculation results; it does not persist positions, "
            "orders, execution logs, rule changes, cache state, or background tasks."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_compute_position_rule",
        tags=("strategy", "position", "rule", "calculation", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer", "minimum": 1},
                "context": {"type": "object"},
            },
            "required": ["rule_id", "context"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "should_buy": {"type": "boolean"},
                "should_sell": {"type": "boolean"},
                "buy_price": {"type": "number"},
                "sell_price": {"type": "number"},
                "stop_loss_price": {"type": "number"},
                "take_profit_price": {"type": "number"},
                "position_size": {"type": "number"},
                "risk_reward_ratio": {"type": ["number", "null"]},
            },
            "required": [
                "should_buy",
                "should_sell",
                "buy_price",
                "sell_price",
                "stop_loss_price",
                "take_profit_price",
                "position_size",
                "risk_reward_ratio",
            ],
        },
        legacy_tool_names=("evaluate_position_rule",),
    ),
    CapabilityManifest(
        capability_key="strategy.compute.position_management",
        title="Strategy Position Management Calculation",
        summary="Calculate position guidance for one visible strategy.",
        description=(
            "Evaluate the active position-management rule bound to one owner/staff-scoped "
            "strategy. The canonical POST endpoint performs deterministic expression "
            "calculation only and does not persist positions, orders, execution logs, "
            "rule changes, cache state, or background tasks."
        ),
        owner_app="strategy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="strategy_compute_position_management",
        tags=("strategy", "position", "management", "calculation", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_id": {"type": "integer", "minimum": 1},
                "context": {"type": "object"},
            },
            "required": ["strategy_id", "context"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "should_buy": {"type": "boolean"},
                "should_sell": {"type": "boolean"},
                "buy_price": {"type": "number"},
                "sell_price": {"type": "number"},
                "stop_loss_price": {"type": "number"},
                "take_profit_price": {"type": "number"},
                "position_size": {"type": "number"},
                "risk_reward_ratio": {"type": ["number", "null"]},
            },
            "required": [
                "should_buy",
                "should_sell",
                "buy_price",
                "sell_price",
                "stop_loss_price",
                "take_profit_price",
                "position_size",
                "risk_reward_ratio",
            ],
        },
        legacy_tool_names=("evaluate_strategy_position_management",),
    ),
]

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="strategy.read.performance",
            title="Strategy Execution Performance",
            summary="Read persisted execution performance for one visible strategy.",
            description=(
                "Summarize persisted execution logs for an owner-scoped strategy without "
                "executing it or inventing portfolio-return metrics."
            ),
            owner_app="strategy",
            risk_level="low",
            executor_kind="legacy_tool",
            executor_ref="strategy_read_performance",
            tags=("strategy", "performance", "execution", "persisted", "read"),
            input_schema={
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "minimum": 1},
                    "start_date": {"type": ["string", "null"], "format": "date"},
                    "end_date": {"type": ["string", "null"], "format": "date"},
                },
                "required": ["strategy_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            legacy_tool_names=("get_strategy_performance",),
        ),
        CapabilityManifest(
            capability_key="strategy.read.signals",
            title="Strategy Signal History",
            summary="Read persisted signals generated by one visible strategy.",
            description=(
                "Flatten persisted strategy execution-log signals without executing rules, "
                "creating signals, or changing signal state."
            ),
            owner_app="strategy",
            risk_level="low",
            executor_kind="legacy_tool",
            executor_ref="strategy_read_signals",
            tags=("strategy", "signals", "execution", "persisted", "read"),
            input_schema={
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "minimum": 1},
                    "status": {"type": ["string", "null"], "maxLength": 32},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["strategy_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "signals": {"type": "array", "items": {"type": "object"}},
                    "total_count": {"type": "integer", "minimum": 0},
                },
                "required": ["signals", "total_count"],
            },
            legacy_tool_names=("get_strategy_signals",),
        ),
        CapabilityManifest(
            capability_key="strategy.read.positions",
            title="Strategy Assigned Portfolio Positions",
            summary="Read positions in portfolios actively assigned to one visible strategy.",
            description=(
                "Return current persisted positions for portfolios assigned to an owner-scoped "
                "strategy without refreshing prices, executing trades, or changing assignments."
            ),
            owner_app="strategy",
            risk_level="low",
            executor_kind="legacy_tool",
            executor_ref="strategy_read_positions",
            tags=("strategy", "positions", "portfolio", "persisted", "read"),
            input_schema={
                "type": "object",
                "properties": {"strategy_id": {"type": "integer", "minimum": 1}},
                "required": ["strategy_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "positions": {"type": "array", "items": {"type": "object"}},
                    "total_count": {"type": "integer", "minimum": 0},
                },
                "required": ["positions", "total_count"],
            },
            legacy_tool_names=("get_strategy_positions",),
        ),
    ]
)
