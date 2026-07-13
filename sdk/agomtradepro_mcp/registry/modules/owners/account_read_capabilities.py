"""account read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="account.read.macro_sizing_config",
        title="Macro Sizing Configuration",
        summary="Read the active macro sizing configuration.",
        description=(
            "Return the active macro sizing factors and tier configuration used by "
            "portfolio sizing workflows."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_macro_sizing_config",
        tags=("account", "portfolio", "macro", "sizing", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "version": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "warning_factor": {"type": "number"},
                "regime_tiers_json": {"type": "array"},
                "pulse_tiers_json": {"type": "array"},
                "drawdown_tiers_json": {"type": "array"},
                "block_new_position_on_extreme": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("get_macro_sizing_config",),
    ),
    CapabilityManifest(
        capability_key="account.read.positions",
        title="Account Positions",
        summary="Read positions across accessible portfolios.",
        description=(
            "Return normalized persisted position summaries, optionally filtered by "
            "portfolio or asset code, without synchronizing the unified ledger."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_positions",
        tags=("account", "portfolio", "positions", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "positions": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_positions",),
    ),
    CapabilityManifest(
        capability_key="account.read.portfolio_statistics",
        title="Portfolio Statistics",
        summary="Read summary statistics for one portfolio.",
        description=(
            "Return valuation, profit and loss, allocation, and capital-flow statistics "
            "for one accessible portfolio."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_portfolio_statistics",
        tags=("account", "portfolio", "statistics", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
            },
            "required": ["portfolio_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "total_value": {"type": "number"},
                "total_cost": {"type": "number"},
                "total_pnl": {"type": "number"},
                "total_pnl_pct": {"type": "number"},
                "position_count": {"type": "integer"},
                "asset_class_breakdown": {"type": "object"},
                "region_breakdown": {"type": "object"},
                "total_capital_inflow": {"type": "number"},
                "total_capital_outflow": {"type": "number"},
                "net_capital_flow": {"type": "number"},
            },
            "required": [],
        },
        legacy_tool_names=("get_portfolio_statistics",),
    ),
    CapabilityManifest(
        capability_key="account.read.trading_cost_configs",
        title="Trading Cost Configurations",
        summary="Read trading-cost configurations for one portfolio.",
        description=(
            "Return the accessible trading-cost configurations associated with one portfolio."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_trading_cost_configs",
        tags=("account", "portfolio", "trading_cost", "config", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["portfolio_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "configs": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_trading_cost_configs",),
    ),
    CapabilityManifest(
        capability_key="account.calculate.trading_cost",
        title="Trading Cost Calculation",
        summary="Calculate trading costs without mutating account state.",
        description=(
            "Calculate commission, stamp duty, transfer fee, and total cost from an "
            "existing trading-cost configuration. This operation is side-effect free."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="calculate_trading_cost",
        tags=("account", "portfolio", "trading_cost", "calculate", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "action": {"type": "string", "enum": ["buy", "sell"]},
                "amount": {"type": "number"},
                "is_shanghai": {"type": "boolean"},
            },
            "required": ["config_id", "action", "amount"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "commission": {"type": "number"},
                "stamp_duty": {"type": "number"},
                "transfer_fee": {"type": "number"},
                "total": {"type": "number"},
                "cost_ratio": {"type": "number"},
                "action": {"type": "string"},
                "amount": {"type": "number"},
                "is_shanghai": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("calculate_trading_cost",),
    ),
    CapabilityManifest(
        capability_key="account.read.account_list",
        title="Unified Account List",
        summary="Read the authenticated user's unified accounts.",
        description=(
            "Return real and simulated accounts visible to the authenticated user, "
            "optionally filtered by account type and active state."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_account_list",
        tags=("account", "unified_account", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean"},
                "account_type": {
                    "type": "string",
                    "enum": ["real", "simulated"],
                },
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "accounts": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["accounts", "total_count", "query"],
        },
        legacy_tool_names=("list_accounts", "list_simulated_accounts"),
    ),
    CapabilityManifest(
        capability_key="account.read.account_detail",
        title="Unified Account Detail",
        summary="Read one unified account visible to the authenticated user.",
        description=(
            "Return one real or simulated account after the canonical API applies "
            "authentication and account ownership checks."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_account_detail",
        tags=("account", "unified_account", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "account": {"type": "object"},
            },
            "required": ["account_id", "account"],
        },
        legacy_tool_names=("get_account", "get_simulated_account"),
    ),
    CapabilityManifest(
        capability_key="account.read.account_positions",
        title="Unified Account Positions",
        summary="Read positions for one unified account.",
        description=(
            "Return the positions for one accessible account using the canonical "
            "account API and a stable list envelope."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_account_positions",
        tags=("account", "unified_account", "positions", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "positions": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": ["account_id", "positions", "total_count"],
        },
        legacy_tool_names=("get_account_positions", "get_simulated_positions"),
    ),
    CapabilityManifest(
        capability_key="account.read.account_performance",
        title="Unified Account Performance",
        summary="Read basic or date-range performance for one unified account.",
        description=(
            "Return a basic performance summary when no dates are provided, or a "
            "date-range performance report when both start_date and end_date are supplied."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_account_performance",
        tags=("account", "unified_account", "performance", "report", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "mode": {
                    "type": "string",
                    "enum": ["basic", "date_range"],
                },
                "query": {"type": "object"},
                "performance": {"type": "object"},
            },
            "required": ["account_id", "mode", "query", "performance"],
        },
        legacy_tool_names=("get_account_performance", "get_simulated_performance"),
    ),
]
