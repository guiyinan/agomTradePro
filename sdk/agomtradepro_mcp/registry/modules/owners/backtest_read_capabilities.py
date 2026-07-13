"""backtest read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="backtest.read.detail",
        title="Backtest Detail",
        summary="Read one canonical backtest result.",
        description=(
            "Return the normalized metrics for one canonical backtest detail record. "
            "Equity-curve access is governed separately because it currently requires staff."
        ),
        owner_app="backtest",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_backtest_result",
        tags=("backtest", "result", "performance", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "backtest_id": {"type": "integer", "minimum": 1},
            },
            "required": ["backtest_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string"},
                "total_return": {"type": "number"},
                "annual_return": {"type": "number"},
                "max_drawdown": {"type": "number"},
                "sharpe_ratio": {"type": ["number", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_backtest_result",),
    ),
    CapabilityManifest(
        capability_key="backtest.read.list",
        title="Backtest List",
        summary="Read the canonical backtest result list.",
        description=(
            "Return a bounded backtest list filtered by canonical status. The legacy "
            "strategy_name argument is intentionally not published because the current "
            "canonical API does not apply it."
        ),
        owner_app="backtest",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_backtests",
        tags=("backtest", "catalog", "performance", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": ["string", "null"],
                    "enum": ["pending", "running", "completed", "failed", None],
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "backtests": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_backtests",),
    ),
    CapabilityManifest(
        capability_key="backtest.read.equity_curve",
        title="Backtest Equity Curve",
        summary="Read one persisted backtest equity curve.",
        description=(
            "Return the persisted equity-curve points for one backtest through the canonical "
            "staff-only GET action. The capability does not rerun the backtest, calculate "
            "metrics, load market data, generate audit reports, mutate caches, or write rows."
        ),
        owner_app="backtest",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="backtest_read_equity_curve",
        tags=("backtest", "equity_curve", "performance", "research", "staff", "read"),
        required_roles=("staff",),
        input_schema={
            "type": "object",
            "properties": {
                "backtest_id": {"type": "integer", "minimum": 1},
            },
            "required": ["backtest_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "backtest_id": {"type": "integer", "minimum": 1},
                "status": {"type": "string"},
                "curve": {"type": "array", "items": {"type": "object"}},
                "point_count": {"type": "integer", "minimum": 0},
            },
            "required": ["backtest_id", "status", "curve", "point_count"],
        },
        audit_tags=("backtest:equity_curve", "mcp:research_read"),
        legacy_tool_names=("get_backtest_equity_curve",),
    ),
]
