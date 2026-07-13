"""simulated_trading read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="simulated_trading.read.daily_inspection_list",
        title="Simulated Trading Daily Inspection List",
        summary="Read daily inspection reports for one simulated account.",
        description=(
            "Return persisted daily inspection reports for one accessible simulated "
            "account, optionally filtered by inspection date."
        ),
        owner_app="simulated_trading",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="simulated_trading_read_daily_inspection_list",
        tags=("simulated_trading", "account", "inspection", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                "inspection_date": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "reports": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["account_id", "reports", "total_count", "query"],
        },
        legacy_tool_names=("list_simulated_daily_inspections",),
    ),
]
