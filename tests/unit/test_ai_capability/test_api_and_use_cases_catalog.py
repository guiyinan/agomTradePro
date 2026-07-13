# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: catalog."""

from .api_and_use_cases_support import *


@pytest.mark.django_db
def test_sync_capabilities_disables_missing_source_entries():
    CapabilityCatalogModel.objects.create(
        capability_key="api.get.api.legacy.status",
        source_type="api",
        source_ref="GET api/legacy/status/",
        name="Legacy Status",
        summary="Legacy endpoint",
        route_group="read_api",
        category="legacy",
        execution_target={"type": "api", "method": "GET", "path": "api/legacy/status/"},
        enabled_for_routing=True,
    )

    use_case = SyncCapabilitiesUseCase()
    with patch.object(SyncCapabilitiesUseCase, "_sync_apis", return_value=[]):
        result = use_case.execute(sync_type="incremental", source="api")

    assert result.disabled_count == 1
    assert (
        CapabilityCatalogModel.objects.get(
            capability_key="api.get.api.legacy.status"
        ).enabled_for_routing
        is False
    )


def test_sync_mcp_tools_marks_mutating_tools_high_risk_and_non_routable():
    use_case = SyncCapabilitiesUseCase()

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value=set(),
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(
                    name="update_portfolio_config", description="update", inputSchema={}
                ),
                SimpleNamespace(name="get_asset_info", description="get", inputSchema={}),
                SimpleNamespace(name="get_portfolio_status", description="get", inputSchema={}),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    mutating = by_key["mcp_tool.update_portfolio_config"]
    assert mutating.risk_level.value == "high"
    assert mutating.requires_confirmation is True
    assert mutating.enabled_for_routing is False
    assert mutating.visibility.value == "admin"

    asset_read = by_key["mcp_tool.get_asset_info"]
    assert asset_read.risk_level.value == "low"
    assert asset_read.requires_confirmation is True
    assert asset_read.enabled_for_routing is True

    readonly = by_key["mcp_tool.get_portfolio_status"]
    assert readonly.risk_level.value == "low"
    assert readonly.requires_confirmation is True
    assert readonly.enabled_for_routing is True
    assert readonly.visibility.value == "admin"


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name", "owner_app", "input_schema"),
    [
        (
            "system.read.policy.status",
            "get_policy_status",
            "policy",
            {"type": "object", "properties": {}, "required": []},
        ),
        (
            "regime.read.history",
            "get_regime_history",
            "regime",
            {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        ),
        (
            "policy.read.events",
            "get_policy_events",
            "policy",
            {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        ),
    ],
)
def test_sync_mcp_tools_preserves_regime_policy_read_family_metadata(
    capability_key,
    legacy_tool_name,
    owner_app,
    input_schema,
):
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key=capability_key,
        summary=f"Read governed capability {capability_key}.",
        description=f"Return the canonical payload for {capability_key}.",
        owner_app=owner_app,
        tags=(owner_app, "macro", "read"),
        input_schema=input_schema,
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=(legacy_tool_name,),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name=legacy_tool_name,
                    description=f"legacy read tool {legacy_tool_name}",
                    inputSchema=input_schema,
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key[f"mcp_tool.{capability_key}"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == capability_key
    assert governed.execution_target["replacement_for"] == [legacy_tool_name]
    assert governed.semantic_key == capability_key
    assert governed.input_schema == input_schema
    assert governed.enabled_for_terminal is True

    legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == capability_key
    assert legacy.semantic_key == capability_key
    assert legacy.enabled_for_terminal is False


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_names"),
    [
        ("realtime.read.price", ("get_realtime_price",)),
        ("realtime.read.price_batch", ("get_multiple_realtime_prices",)),
        (
            "data_center.read.price_history",
            ("data_center_get_price_history", "get_price_history"),
        ),
        ("realtime.read.market_summary", ("get_market_summary",)),
        ("data_center.read.latest_quote", ("data_center_get_quotes",)),
        ("data_center.read.news", ("data_center_get_news",)),
        (
            "data_center.read.capital_flows",
            ("data_center_get_capital_flows",),
        ),
        ("data_center.read.publisher_detail", ("data_center_get_publisher",)),
        ("data_center.read.publisher_catalog", ("data_center_list_publishers",)),
        ("data_center.read.indicator_detail", ("data_center_get_indicator",)),
        (
            "data_center.read.indicator_unit_rules",
            ("data_center_list_indicator_unit_rules",),
        ),
        (
            "data_center.read.indicator_unit_rule_detail",
            ("data_center_get_indicator_unit_rule",),
        ),
        ("account.read.macro_sizing_config", ("get_macro_sizing_config",)),
        ("account.read.positions", ("get_positions",)),
        ("account.read.portfolio_catalog", ("list_portfolios",)),
        ("account.read.portfolio_detail", ("get_portfolio",)),
        (
            "account.read.position_records",
            ("get_positions_detailed", "export_positions_json"),
        ),
        (
            "account.read.transaction_records",
            ("get_transactions_detailed", "export_transactions_json"),
        ),
        (
            "account.read.capital_flow_records",
            ("get_capital_flows_detailed", "export_capital_flows_json"),
        ),
        ("account.read.portfolio_statistics", ("get_portfolio_statistics",)),
        ("account.read.trading_cost_configs", ("get_trading_cost_configs",)),
        ("account.calculate.trading_cost", ("calculate_trading_cost",)),
        (
            "account.read.account_list",
            ("list_accounts", "list_simulated_accounts"),
        ),
        (
            "account.read.account_detail",
            ("get_account", "get_simulated_account"),
        ),
        (
            "account.read.account_positions",
            ("get_account_positions", "get_simulated_positions"),
        ),
        (
            "account.read.account_performance",
            ("get_account_performance", "get_simulated_performance"),
        ),
        (
            "simulated_trading.read.daily_inspection_list",
            ("list_simulated_daily_inspections",),
        ),
        (
            "hedge.compute.correlation_matrix",
            (
                "get_hedge_correlation_matrix",
                "get_correlation_matrix",
            ),
        ),
        ("hedge.read.pair_catalog", ("list_hedge_pairs",)),
        ("hedge.read.pair_detail", ("get_hedge_pair_info",)),
        ("hedge.read.alert_list", ("get_hedge_alerts",)),
        ("hedge.read.portfolio_state", ("get_hedge_portfolio_state",)),
        (
            "asset_analysis.read.weight_config_catalog",
            ("get_asset_weight_configs",),
        ),
        (
            "asset_analysis.read.current_weight",
            ("get_asset_current_weight",),
        ),
        ("asset_analysis.read.pool_summary", ("asset_pool_summary",)),
        (
            "equity.read.pool_catalog",
            ("list_stocks", "get_sector_stocks"),
        ),
        (
            "equity.read.valuation_analysis",
            ("get_stock_valuation",),
        ),
        (
            "equity.read.valuation_repair_list",
            ("list_valuation_repairs",),
        ),
        (
            "equity.read.valuation_freshness",
            ("get_valuation_data_freshness",),
        ),
        (
            "equity.read.valuation_quality_latest",
            ("get_valuation_data_quality_latest",),
        ),
        (
            "equity.compute.valuation_repair_status",
            ("get_valuation_repair_status",),
        ),
        (
            "equity.compute.valuation_repair_history",
            ("get_valuation_repair_history",),
        ),
        (
            "equity.read.valuation_repair_config",
            ("get_valuation_repair_config",),
        ),
        (
            "equity.read.valuation_repair_config_catalog",
            ("list_valuation_repair_configs",),
        ),
        (
            "decision.read.advisor_sheet",
            ("get_auto_advisor_decision_sheet",),
        ),
        (
            "dashboard.read.auto_advisor_console",
            ("get_auto_advisor_console",),
        ),
        (
            "dashboard.query.auto_advisor",
            ("ask_auto_advisor",),
        ),
        (
            "dashboard.read.auto_advisor_weekly_report",
            ("get_auto_advisor_weekly_report",),
        ),
        (
            "dashboard.read.auto_advisor_weekly_report_history",
            ("list_auto_advisor_weekly_report_history",),
        ),
        (
            "dashboard.read.auto_advisor_notifications",
            ("list_auto_advisor_notifications",),
        ),
        (
            "dashboard.read.alpha_history",
            ("get_dashboard_alpha_history",),
        ),
        (
            "dashboard.read.alpha_history_detail",
            ("get_dashboard_alpha_history_detail",),
        ),
        (
            "factor.compute.top_stocks",
            ("get_factor_top_stocks",),
        ),
        (
            "factor.compute.stock_explanation",
            ("explain_factor_stock",),
        ),
        (
            "factor.read.definition_catalog",
            ("list_factor_definitions",),
        ),
        (
            "factor.read.config_catalog",
            ("list_factor_configs",),
        ),
        ("strategy.read.catalog", ("list_strategies",)),
        ("strategy.read.detail", ("get_strategy",)),
        (
            "strategy.read.ai_config_catalog",
            ("list_ai_strategy_configs",),
        ),
        (
            "strategy.read.ai_config_detail",
            ("get_strategy_ai_config",),
        ),
        (
            "strategy.read.position_rule_catalog",
            ("list_position_rules",),
        ),
        (
            "strategy.read.position_rule_detail",
            ("get_strategy_position_rule",),
        ),
        (
            "strategy.compute.position_rule",
            ("evaluate_position_rule",),
        ),
        (
            "strategy.compute.position_management",
            ("evaluate_strategy_position_management",),
        ),
        ("agent_proposal.read.proposal_detail", ("get_agent_proposal",)),
        ("beta_gate.read.config_catalog", ("list_beta_gate_configs",)),
        ("filter.read.health", ("get_filter_health",)),
        ("sentiment.read.index", ("get_sentiment_index",)),
        ("sentiment.read.recent", ("get_sentiment_recent",)),
        ("sentiment.read.health", ("get_sentiment_health",)),
        ("events.read.query", ("query_events",)),
        ("events.read.metrics", ("get_event_metrics",)),
        ("events.read.status", ("get_event_bus_status",)),
        ("audit.read.summary", ("get_audit_summary",)),
        ("audit.read.execution_links", ("list_audit_execution_links",)),
        ("fund.read.ranking", ("rank_funds",)),
        ("fund.compute.screen", ("screen_funds",)),
        ("fund.read.detail", ("get_fund_detail",)),
        ("fund.read.nav_history", ("get_fund_nav_history",)),
        ("fund.read.holdings", ("get_fund_holdings",)),
        ("backtest.read.detail", ("get_backtest_result",)),
        ("backtest.read.list", ("list_backtests",)),
        ("alpha.read.provider_status", ("get_alpha_provider_status",)),
        ("alpha.read.universe_catalog", ("get_alpha_available_universes",)),
        ("alpha.read.health", ("check_alpha_health",)),
        (
            "alpha.read.inference_ops_overview",
            ("get_alpha_ops_inference_overview",),
        ),
        (
            "alpha.read.qlib_data_ops_overview",
            ("get_alpha_ops_qlib_data_overview",),
        ),
        ("alpha_trigger.read.trigger_list", ("list_alpha_triggers",)),
        ("alpha_trigger.read.candidate_list", ("list_alpha_candidates",)),
        ("alpha_trigger.read.candidate_detail", ("get_alpha_candidate",)),
        ("alpha_trigger.read.performance", ("alpha_trigger_performance",)),
        ("decision_rhythm.read.quota_list", ("list_decision_quotas",)),
        ("decision_rhythm.read.request_list", ("list_decision_requests",)),
        ("decision_rhythm.read.request_detail", ("get_decision_request",)),
        ("decision_rhythm.read.summary", ("get_decision_rhythm_summary",)),
        (
            "decision.read.recommendation_list",
            ("decision_workflow_list_recommendations",),
        ),
        (
            "decision.read.transition_plan_detail",
            ("decision_workflow_get_transition_plan",),
        ),
        ("config_center.read.capability_catalog", ("list_config_capabilities",)),
        ("config_center.read.qlib_runtime", ("get_qlib_runtime_config",)),
        (
            "config_center.read.qlib_training_profiles",
            ("list_qlib_training_profiles",),
        ),
        (
            "config_center.read.alpha_universe_catalog",
            ("list_alpha_universes",),
        ),
        (
            "config_center.read.alpha_universe_members",
            ("get_alpha_universe_members",),
        ),
        (
            "config_center.read.qlib_training_runs",
            ("list_qlib_training_runs",),
        ),
        (
            "config_center.read.qlib_training_run_detail",
            ("get_qlib_training_run_detail",),
        ),
        ("rotation.read.regime_catalog", ("list_rotation_regimes",)),
        ("rotation.read.template_catalog", ("list_rotation_templates",)),
        ("rotation.read.config_detail", ("get_rotation_config",)),
        (
            "rotation.read.account_config_list",
            ("list_account_rotation_configs",),
        ),
        (
            "rotation.read.account_config_detail",
            ("get_account_rotation_config",),
        ),
        ("rotation.read.asset_catalog", ("list_rotation_asset_master",)),
        ("rotation.read.asset_detail", ("get_rotation_asset",)),
        (
            "rotation.read.latest_signal_list",
            ("get_latest_rotation_signals",),
        ),
        (
            "rotation.compute.asset_comparison",
            ("compare_assets",),
        ),
        (
            "beta_gate.compute.config_comparison",
            ("compare_beta_gate_version",),
        ),
        (
            "beta_gate.compute.batch_evaluation",
            ("test_beta_gate",),
        ),
        ("regime.read.navigator", ("get_regime_navigator",)),
        ("regime.read.distribution", ("get_regime_distribution",)),
        ("regime.compute.calculate", ("calculate_regime",)),
    ],
)
def test_sync_mcp_tools_preserves_governed_read_replacements(
    capability_key,
    legacy_tool_names,
):
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key=capability_key,
        summary="Read governed realtime price data.",
        description="Governed read capability for realtime price data.",
        owner_app="realtime",
        tags=("realtime", "market_data", "price", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=legacy_tool_names,
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                *[
                    SimpleNamespace(
                        name=legacy_tool_name,
                        description="market data read",
                        inputSchema={},
                    )
                    for legacy_tool_name in legacy_tool_names
                ],
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key[f"mcp_tool.{capability_key}"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["replacement_for"] == list(legacy_tool_names)
    assert governed.semantic_key == capability_key
    assert governed.enabled_for_terminal is True

    for legacy_tool_name in legacy_tool_names:
        legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
        assert legacy.execution_target["type"] == "mcp_tool"
        assert legacy.execution_target["replacement_capability_key"] == capability_key
        assert legacy.semantic_key == capability_key
        assert legacy.enabled_for_terminal is False
