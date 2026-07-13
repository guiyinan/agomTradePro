"""Catalog replacement evidence for newly governed workflow capabilities."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

WORKFLOW_REPLACEMENTS = [
    (
        "agent_task.create.task",
        "agent_runtime",
        (
            "start_research_task",
            "start_monitoring_task",
            "start_decision_task",
            "start_execution_task",
            "start_ops_task",
        ),
    ),
    ("agent_task.resume.task", "agent_runtime", ("resume_agent_task",)),
    ("agent_task.cancel.task", "agent_runtime", ("cancel_agent_task",)),
    ("alpha.start.inference", "alpha", ("trigger_alpha_ops_inference",)),
    ("alpha.refresh.qlib_data", "alpha", ("refresh_alpha_qlib_data",)),
    ("alpha_trigger.create.trigger", "alpha_trigger", ("create_alpha_trigger",)),
    (
        "alpha_trigger.execute.evaluation",
        "alpha_trigger",
        ("evaluate_alpha_trigger",),
    ),
    (
        "alpha_trigger.execute.invalidation_check",
        "alpha_trigger",
        ("check_alpha_trigger_invalidation",),
    ),
    (
        "alpha_trigger.generate.candidate",
        "alpha_trigger",
        ("generate_alpha_candidate",),
    ),
    ("backtest.run.strategy", "backtest", ("run_backtest",)),
    (
        "backtest.run.decision_replay",
        "backtest",
        ("run_decision_replay_backtest",),
    ),
    (
        "config_center.update.qlib_training_profile",
        "config_center",
        ("save_qlib_training_profile",),
    ),
    (
        "config_center.update.alpha_universe",
        "config_center",
        ("save_alpha_universe",),
    ),
    (
        "config_center.start.qlib_training",
        "config_center",
        ("trigger_qlib_training",),
    ),
    ("dashboard.refresh.alpha", "dashboard", ("trigger_dashboard_alpha_refresh",)),
    (
        "data_center.repair.decision_reliability",
        "data_center",
        ("data_center_repair_decision_data_reliability",),
    ),
    (
        "decision.refresh.recommendations",
        "decision_rhythm",
        ("decision_workflow_refresh_recommendations",),
    ),
    (
        "decision.update.recommendation_action",
        "decision_rhythm",
        ("decision_workflow_apply_recommendation_action",),
    ),
    (
        "decision.create.transition_plan",
        "decision_rhythm",
        ("decision_workflow_generate_transition_plan",),
    ),
    (
        "decision.update.transition_plan",
        "decision_rhythm",
        ("decision_workflow_update_transition_plan",),
    ),
    (
        "equity.run.valuation_repair_scan",
        "equity",
        ("scan_valuation_repairs",),
    ),
    ("equity.sync.valuation_data", "equity", ("sync_valuation_data",)),
    (
        "equity.create.valuation_quality_snapshot",
        "equity",
        ("validate_valuation_data",),
    ),
    ("factor.create.portfolio", "factor", ("create_factor_portfolio",)),
    (
        "fund.create.performance_snapshot",
        "fund",
        ("get_fund_performance",),
    ),
    ("rotation.generate.signal", "rotation", ("generate_rotation_signal",)),
    ("sentiment.execute.analysis", "sentiment", ("analyze_sentiment",)),
    (
        "sentiment.execute.batch_analysis",
        "sentiment",
        ("batch_analyze_sentiment",),
    ),
]


@pytest.mark.parametrize(
    ("capability_key", "owner_app", "legacy_tool_names"),
    WORKFLOW_REPLACEMENTS,
)
def test_remaining_workflows_replace_legacy_catalog_entries(
    capability_key,
    owner_app,
    legacy_tool_names,
):
    manifest = SimpleNamespace(
        capability_key=capability_key,
        summary="Governed workflow",
        description="Preview and confirm the governed workflow.",
        owner_app=owner_app,
        tags=(owner_app, "write"),
        audit_tags=(f"{owner_app}:workflow", "mcp:write"),
        input_schema={"type": "object", "properties": {}},
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=legacy_tool_names,
    )
    raw_tools = [
        SimpleNamespace(name=name, description="Legacy workflow", inputSchema={})
        for name in legacy_tool_names
    ]

    with patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
        return_value=[manifest],
    ), patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
        return_value={"agom_capability_call", "agom_confirmation_resume"},
    ), patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
        return_value=raw_tools,
    ):
        capabilities = SyncCapabilitiesUseCase()._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key[f"mcp_tool.{capability_key}"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["replacement_for"] == list(legacy_tool_names)
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"]
    for legacy_tool_name in legacy_tool_names:
        legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
        assert legacy.execution_target["replacement_capability_key"] == capability_key
        assert legacy.enabled_for_terminal is False
