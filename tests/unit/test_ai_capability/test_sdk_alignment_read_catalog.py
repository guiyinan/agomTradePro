"""Catalog replacement evidence for SDK-aligned persisted reads."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


@pytest.mark.parametrize(
    ("capability_key", "owner_app", "legacy_tool_name"),
    [
        ("alpha.read.stock_scores", "alpha", "get_alpha_stock_scores"),
        ("alpha.read.factor_exposure", "alpha", "get_alpha_factor_exposure"),
        (
            "asset_analysis.compute.multidim_screen",
            "asset_analysis",
            "asset_multidim_screen",
        ),
        (
            "asset_analysis.compute.pool_screen",
            "asset_analysis",
            "asset_pool_screen",
        ),
        (
            "decision.compute.workflow_precheck",
            "decision_rhythm",
            "decision_workflow_precheck",
        ),
        (
            "decision.read.funnel_context",
            "decision_rhythm",
            "decision_workflow_get_funnel_context",
        ),
        ("equity.read.score", "equity", "get_stock_score"),
        (
            "equity.compute.recommendations",
            "equity",
            "get_stock_recommendations",
        ),
        ("equity.compute.analysis", "equity", "analyze_stock"),
        ("fund.read.catalog", "fund", "list_funds"),
        ("sector.compute.analysis", "sector", "analyze_sector"),
        ("sector.compute.comparison", "sector", "compare_sectors"),
        ("realtime.read.top_movers", "realtime", "get_top_movers"),
        ("equity.read.financial_history", "equity", "get_stock_financials"),
        ("fund.read.score", "fund", "get_fund_score"),
        ("sector.read.score", "sector", "get_sector_score"),
        (
            "realtime.read.sector_performance",
            "realtime",
            "get_sector_realtime_performance",
        ),
        ("strategy.read.performance", "strategy", "get_strategy_performance"),
        ("strategy.read.signals", "strategy", "get_strategy_signals"),
        ("strategy.read.positions", "strategy", "get_strategy_positions"),
        ("factor.read.portfolio", "factor", "get_factor_portfolio"),
        (
            "ai_provider.read.provider_catalog",
            "ai_provider",
            "list_ai_providers",
        ),
        ("ai_provider.read.provider_detail", "ai_provider", "get_ai_provider"),
        ("ai_provider.read.usage_logs", "ai_provider", "list_ai_usage_logs"),
        (
            "data_center.read.provider_status",
            "data_center",
            "get_data_center_provider_status",
        ),
        (
            "data_center.read.provider_catalog",
            "data_center",
            "list_data_center_providers",
        ),
        (
            "data_center.read.macro_series",
            "data_center",
            "data_center_get_macro_series",
        ),
        (
            "data_center.read.indicator_catalog",
            "data_center",
            "data_center_list_indicators",
        ),
        ("filter.read.indicator_catalog", "filter", "list_filters"),
        ("filter.read.config_detail", "filter", "get_filter"),
        (
            "policy.read.workbench.bootstrap",
            "policy",
            "get_workbench_bootstrap",
        ),
        ("policy.read.workbench.summary", "policy", "get_workbench_summary"),
        (
            "policy.read.workbench.event_detail",
            "policy",
            "get_workbench_event_detail",
        ),
        ("policy.read.workbench.items", "policy", "get_workbench_items"),
        (
            "policy.read.sentiment_gate.state",
            "policy",
            "get_sentiment_gate_state",
        ),
        ("prompt.read.template_catalog", "prompt", "list_prompt_templates"),
        ("prompt.read.chain_catalog", "prompt", "list_prompt_chains"),
        ("pulse.read.current", "pulse", "get_pulse_current"),
        ("pulse.read.history", "pulse", "get_pulse_history"),
        ("risk_center.read.floor", "risk_center", "get_risk_floor"),
        (
            "risk_center.read.template_catalog",
            "risk_center",
            "list_risk_templates",
        ),
        (
            "risk_center.read.effective_policy",
            "risk_center",
            "get_effective_risk_policy",
        ),
        (
            "risk_center.read.account_policy",
            "risk_center",
            "get_account_risk_policy",
        ),
        (
            "risk_center.read.exception_list",
            "risk_center",
            "list_risk_exceptions",
        ),
        (
            "risk_center.read.pre_trade_check",
            "risk_center",
            "check_pre_trade_risk",
        ),
        (
            "risk_center.read.post_investment_check",
            "risk_center",
            "check_post_investment_risk",
        ),
        (
            "risk_center.read.daily_report",
            "risk_center",
            "get_risk_center_daily_report",
        ),
        (
            "risk_center.read.daily_report_history",
            "risk_center",
            "list_risk_center_daily_reports",
        ),
        (
            "system.read.task_monitor.statistics",
            "task_monitor",
            "get_task_monitor_statistics",
        ),
        (
            "task_monitor.read.task_status",
            "task_monitor",
            "get_task_monitor_status",
        ),
        ("task_monitor.read.task_list", "task_monitor", "list_task_monitor_tasks"),
        (
            "task_monitor.read.dashboard",
            "task_monitor",
            "get_task_monitor_dashboard",
        ),
        (
            "task_monitor.read.celery_health",
            "task_monitor",
            "get_task_monitor_celery_health",
        ),
    ],
)
def test_sdk_aligned_reads_replace_legacy_catalog_entries(
    capability_key,
    owner_app,
    legacy_tool_name,
):
    manifest = SimpleNamespace(
        capability_key=capability_key,
        summary="Canonical persisted read",
        description="Canonical persisted read contract.",
        owner_app=owner_app,
        tags=(owner_app, "read"),
        audit_tags=(),
        input_schema={"type": "object", "properties": {}},
        risk_level="low",
        requires_confirmation=False,
        idempotency="none",
        legacy_tool_names=(legacy_tool_name,),
    )
    raw_tool = SimpleNamespace(
        name=legacy_tool_name,
        description="Legacy read",
        inputSchema={},
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[raw_tool],
        ),
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key[f"mcp_tool.{capability_key}"]
    legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
    assert governed.execution_target["replacement_for"] == [legacy_tool_name]
    assert legacy.execution_target["replacement_capability_key"] == capability_key
    assert legacy.enabled_for_terminal is False
