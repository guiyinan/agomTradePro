"""Backtest workflow capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="backtest.run.strategy",
        title="Run Strategy Backtest",
        summary="Preview and confirm creation of one strategy backtest run.",
        description=(
            "Validate the strategy, date range, and capital target before creating the "
            "durable backtest result and executing the canonical backtest workflow."
        ),
        owner_app="backtest",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="backtest_run_strategy",
        tags=("backtest", "strategy", "research", "run", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "strategy_name": {"type": "string", "minLength": 1, "maxLength": 100},
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "initial_capital": {"type": "number", "exclusiveMinimum": 0},
                "idempotency_key": {"type": "string"},
            },
            "required": ["strategy_name", "start_date", "end_date"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("backtest:run_strategy", "mcp:write"),
        legacy_tool_names=("run_backtest",),
    ),
    CapabilityManifest(
        capability_key="backtest.run.decision_replay",
        title="Run Decision Replay Backtest",
        summary="Preview and confirm one portfolio decision-replay backtest.",
        description=(
            "Validate the portfolio, branch, date range, and capital target before "
            "creating a durable decision-replay backtest result."
        ),
        owner_app="backtest",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="backtest_run_decision_replay",
        tags=("backtest", "decision", "replay", "run", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "branch_type": {
                    "type": "string",
                    "enum": ["actual", "no_action", "system_plan", "delayed_1d"],
                },
                "initial_capital": {"type": "number", "exclusiveMinimum": 0},
                "idempotency_key": {"type": "string"},
            },
            "required": ["portfolio_id", "start_date", "end_date", "branch_type"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("backtest:run_decision_replay", "mcp:write"),
        legacy_tool_names=("run_decision_replay_backtest",),
    ),
]
