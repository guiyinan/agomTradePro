"""dashboard read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="dashboard.read.auto_advisor_console",
        title="Auto Advisor Console",
        summary="Read the current homepage auto-advisor console.",
        description=(
            "Return the authenticated user's account-level tradeability, portfolio risk, "
            "alerts, freshness, advice, and confirmation state without persisting outputs."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_auto_advisor_console",
        tags=("dashboard", "auto_advisor", "console", "account", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string"]},
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "account": {"type": "object"},
                "generated_at": {"type": ["string", "null"]},
                "today_tradeability": {"type": "object"},
                "macro_regime": {"type": "object"},
                "portfolio_risk": {"type": "object"},
                "today_advice": {"type": "object"},
                "must_handle_alerts": {"type": "array"},
                "data_freshness": {"type": "object"},
                "execution": {"type": "object"},
                "next_actions": {"type": "array"},
            },
            "required": [
                "status",
                "account",
                "today_tradeability",
                "macro_regime",
                "portfolio_risk",
                "today_advice",
                "must_handle_alerts",
                "data_freshness",
                "execution",
                "next_actions",
            ],
        },
        legacy_tool_names=("get_auto_advisor_console",),
    ),
    CapabilityManifest(
        capability_key="dashboard.query.auto_advisor",
        title="Auto Advisor Query",
        summary="Ask a deterministic question over the current auto-advisor context.",
        description=(
            "Answer supported account-level risk, reduction, invalidation, market-shock, "
            "execution-gap, and overview questions from the current read-only advisor sheet."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_query_auto_advisor",
        tags=("dashboard", "auto_advisor", "query", "account", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string"]},
                "question": {"type": "string", "minLength": 1},
            },
            "required": ["account_id", "question"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "account": {"type": "object"},
                "generated_at": {"type": ["string", "null"]},
                "query": {"type": "object"},
                "answer": {"type": "string"},
                "highlights": {"type": "array"},
                "evidence": {"type": "object"},
            },
            "required": [
                "status",
                "account",
                "query",
                "answer",
                "highlights",
                "evidence",
            ],
        },
        legacy_tool_names=("ask_auto_advisor",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.auto_advisor_weekly_report",
        title="Auto Advisor Weekly Report",
        summary="Read a generated weekly auto-advisor report without persisting it.",
        description=(
            "Return the authenticated user's generated weekly report payload for the requested "
            "date. This GET capability does not create report, diary, notification, or audit rows."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_auto_advisor_weekly_report",
        tags=("dashboard", "auto_advisor", "weekly_report", "generated", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string"]},
                "as_of": {
                    "type": ["string", "null"],
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                },
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "account": {"type": "object"},
                "generated_at": {"type": ["string", "null"]},
                "week": {"type": "object"},
                "portfolio_change": {"type": "object"},
                "largest_risk_exposure": {"type": "object"},
                "system_vs_actual": {"type": "object"},
                "unexecuted_recommendations": {"type": "object"},
                "invalidated_recommendations": {"type": "object"},
                "investment_diary": {"type": "object"},
                "next_week_watchlist": {"type": "array"},
                "evidence": {"type": "object"},
            },
            "required": [
                "status",
                "account",
                "week",
                "portfolio_change",
                "largest_risk_exposure",
                "system_vs_actual",
                "unexecuted_recommendations",
                "invalidated_recommendations",
                "investment_diary",
                "next_week_watchlist",
                "evidence",
            ],
        },
        legacy_tool_names=("get_auto_advisor_weekly_report",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.auto_advisor_weekly_report_history",
        title="Auto Advisor Weekly Report History",
        summary="Read persisted personal auto-advisor weekly reports.",
        description=(
            "Return user-scoped persisted auto-advisor weekly report snapshots, "
            "optionally filtered by account, without generating or persisting a report."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_auto_advisor_weekly_report_history",
        tags=("dashboard", "auto_advisor", "weekly_report", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "reports": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["status", "reports", "total_count", "query"],
        },
        legacy_tool_names=("list_auto_advisor_weekly_report_history",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.auto_advisor_notifications",
        title="Auto Advisor Notification History",
        summary="Read persisted personal auto-advisor notifications.",
        description=(
            "Return user-scoped persisted auto-advisor notification and output records, "
            "optionally filtered by account, without generating reports or notifications."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_auto_advisor_notifications",
        tags=("dashboard", "auto_advisor", "notification", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "notifications": {"type": "array"},
                "total_count": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["status", "notifications", "total_count", "query"],
        },
        legacy_tool_names=("list_auto_advisor_notifications",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.alpha_history",
        title="Dashboard Alpha History",
        summary="Read persisted Dashboard Alpha recommendation runs.",
        description=(
            "Return recommendation history owned by the authenticated user, optionally filtered "
            "by portfolio, trade date, stock, stage, or provider source. The capability only "
            "reads persisted runs and snapshots and does not trigger Alpha inference or refresh."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_alpha_history",
        tags=("dashboard", "alpha", "recommendation", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": ["integer", "null"], "minimum": 1},
                "trade_date": {
                    "type": ["string", "null"],
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                },
                "stock_code": {"type": ["string", "null"], "minLength": 1},
                "stage": {"type": ["string", "null"], "minLength": 1},
                "source": {"type": ["string", "null"], "minLength": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "runs": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
                "query": {"type": "object"},
            },
            "required": ["runs", "total_count", "query"],
        },
        legacy_tool_names=("get_dashboard_alpha_history",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.alpha_history_detail",
        title="Dashboard Alpha History Detail",
        summary="Read one persisted Dashboard Alpha recommendation run.",
        description=(
            "Return one recommendation run and its persisted stock snapshots for the authenticated "
            "owner. Missing display names may be resolved from existing facts without writing "
            "asset-master records or refreshing Alpha results."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_alpha_history_detail",
        tags=("dashboard", "alpha", "recommendation", "history", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "integer", "minimum": 1},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "run": {"type": "object"},
            },
            "required": ["run"],
        },
        legacy_tool_names=("get_dashboard_alpha_history_detail",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.equity_curve",
        title="Dashboard Equity Curve",
        summary="Read the authenticated user's portfolio equity curve.",
        description=(
            "Return the current persisted portfolio-value history from the canonical Dashboard "
            "V1 GET endpoint. Empty histories use the endpoint's explicit current-value fallback; "
            "the read does not refresh prices, execute strategies, populate caches, or persist rows."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_equity_curve",
        tags=("dashboard", "portfolio", "equity_curve", "performance", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "range": {"type": "string"},
                "has_history": {"type": "boolean"},
                "series": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["range", "has_history", "series"],
        },
        legacy_tool_names=("get_dashboard_equity_curve_v1",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.asset_allocation",
        title="Dashboard Asset Allocation",
        summary="Read the authenticated user's aggregate asset allocation.",
        description=(
            "Aggregate persisted simulated positions by asset class through the canonical "
            "Dashboard JSON endpoint. The zero-argument contract covers all accessible "
            "accounts and does not create accounts, synchronize ledgers, refresh prices, "
            "populate caches, or persist allocation snapshots."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_asset_allocation",
        tags=("dashboard", "account", "portfolio", "asset_allocation", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "allocation": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
                "total_market_value": {"type": "number"},
            },
            "required": ["allocation", "total_market_value"],
        },
        legacy_tool_names=("get_dashboard_allocation",),
    ),
    CapabilityManifest(
        capability_key="dashboard.read.position_catalog",
        title="Dashboard Position Catalog",
        summary="Read positions across the authenticated user's simulated accounts.",
        description=(
            "Return persisted simulated positions with account metadata through the dedicated "
            "canonical Dashboard JSON endpoint. The zero-argument contract covers all of the "
            "authenticated user's accessible accounts and does not create accounts, synchronize "
            "ledgers, refresh prices, backfill snapshots, or render HTMX content."
        ),
        owner_app="dashboard",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="dashboard_read_position_catalog",
        tags=("dashboard", "account", "portfolio", "positions", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
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
        legacy_tool_names=("get_dashboard_positions",),
    ),
]
