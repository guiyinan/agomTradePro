"""Governed read-only Account capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="account.read.portfolio_catalog",
        title="Portfolio Catalog",
        summary="List portfolios accessible to the authenticated user.",
        description=(
            "Return persisted portfolio summaries for portfolios owned by or shared "
            "with the authenticated user."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_portfolio_catalog",
        tags=("account", "portfolio", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "portfolios": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": ["portfolios", "total_count"],
        },
        legacy_tool_names=("list_portfolios",),
    ),
    CapabilityManifest(
        capability_key="account.read.portfolio_detail",
        title="Portfolio Detail",
        summary="Read one accessible portfolio and its open position summaries.",
        description=(
            "Return one persisted portfolio plus open legacy position projections "
            "without synchronizing the unified ledger."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_portfolio_detail",
        tags=("account", "portfolio", "detail", "positions", "read"),
        input_schema={
            "type": "object",
            "properties": {"portfolio_id": {"type": "integer"}},
            "required": ["portfolio_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "portfolio": {"type": "object"},
                "positions": {"type": "array"},
            },
            "required": ["portfolio", "positions"],
        },
        legacy_tool_names=("get_portfolio",),
    ),
    CapabilityManifest(
        capability_key="account.read.position_records",
        title="Position Records",
        summary="Read detailed persisted position records without ledger synchronization.",
        description=(
            "Return accessible legacy position projections including record identity, "
            "classification, valuation, source, and lifecycle fields."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_position_records",
        tags=("account", "portfolio", "positions", "records", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "include_closed": {"type": "boolean"},
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
            "required": ["positions", "total_count"],
        },
        legacy_tool_names=("get_positions_detailed", "export_positions_json"),
    ),
    CapabilityManifest(
        capability_key="account.read.transaction_records",
        title="Transaction Records",
        summary="Read persisted transaction records for owned portfolios.",
        description=(
            "Return transaction identity, portfolio, asset, quantity, price, cost, "
            "broker, and timestamp fields without mutating account state."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_transaction_records",
        tags=("account", "portfolio", "transactions", "records", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "transactions": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": ["transactions", "total_count"],
        },
        legacy_tool_names=("get_transactions_detailed", "export_transactions_json"),
    ),
    CapabilityManifest(
        capability_key="account.read.capital_flow_records",
        title="Capital Flow Records",
        summary="Read persisted capital-flow records for owned portfolios.",
        description=(
            "Return deposit, withdrawal, dividend, interest, and adjustment records "
            "without mutating account state."
        ),
        owner_app="account",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="account_read_capital_flow_records",
        tags=("account", "portfolio", "capital_flow", "records", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "capital_flows": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": ["capital_flows", "total_count"],
        },
        legacy_tool_names=("get_capital_flows_detailed", "export_capital_flows_json"),
    ),
]
