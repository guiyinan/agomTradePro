# ruff: noqa: F403, F405, I001
"""Core dispatcher evidence for newly governed workflow capabilities."""

from .core_registry_support import *


WORKFLOW_CASES = [
    (
        "agent_task.create.task",
        "agent_task_create_task",
        (
            "start_research_task",
            "start_monitoring_task",
            "start_decision_task",
            "start_execution_task",
            "start_ops_task",
        ),
        {"task_domain": "research", "task_type": "macro_review"},
    ),
    (
        "agent_task.resume.task",
        "agent_task_resume_task",
        ("resume_agent_task",),
        {"task_id": 7},
    ),
    (
        "agent_task.cancel.task",
        "agent_task_cancel_task",
        ("cancel_agent_task",),
        {"task_id": 7, "reason": "superseded"},
    ),
    (
        "alpha.start.inference",
        "alpha_start_inference",
        ("trigger_alpha_ops_inference",),
        {"mode": "general", "trade_date": "2026-07-13"},
    ),
    (
        "alpha.refresh.qlib_data",
        "alpha_refresh_qlib_data",
        ("refresh_alpha_qlib_data",),
        {"mode": "universes", "target_date": "2026-07-13"},
    ),
    (
        "alpha_trigger.create.trigger",
        "alpha_trigger_create_trigger",
        ("create_alpha_trigger",),
        {"payload": {"asset_code": "000001.SZ"}},
    ),
    (
        "alpha_trigger.execute.evaluation",
        "alpha_trigger_execute_evaluation",
        ("evaluate_alpha_trigger",),
        {"payload": {"trigger_id": "trigger-1"}},
    ),
    (
        "alpha_trigger.execute.invalidation_check",
        "alpha_trigger_execute_invalidation_check",
        ("check_alpha_trigger_invalidation",),
        {"payload": {"trigger_id": "trigger-1"}},
    ),
    (
        "alpha_trigger.generate.candidate",
        "alpha_trigger_generate_candidate",
        ("generate_alpha_candidate",),
        {"payload": {"trigger_id": "trigger-1"}},
    ),
    (
        "backtest.run.strategy",
        "backtest_run_strategy",
        ("run_backtest",),
        {
            "strategy_name": "momentum",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        },
    ),
    (
        "backtest.run.decision_replay",
        "backtest_run_decision_replay",
        ("run_decision_replay_backtest",),
        {
            "portfolio_id": 1,
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "branch_type": "actual",
        },
    ),
    (
        "config_center.update.qlib_training_profile",
        "config_center_update_qlib_training_profile",
        ("save_qlib_training_profile",),
        {"payload": {"profile_key": "daily", "name": "Daily"}},
    ),
    (
        "config_center.update.alpha_universe",
        "config_center_update_alpha_universe",
        ("save_alpha_universe",),
        {"payload": {"universe_id": "csi300", "name": "CSI 300"}},
    ),
    (
        "config_center.start.qlib_training",
        "config_center_start_qlib_training",
        ("trigger_qlib_training",),
        {"payload": {"profile_key": "daily"}},
    ),
    (
        "dashboard.refresh.alpha",
        "dashboard_refresh_alpha",
        ("trigger_dashboard_alpha_refresh",),
        {"top_n": 10, "alpha_scope": "general"},
    ),
    (
        "data_center.repair.decision_reliability",
        "data_center_repair_decision_reliability",
        ("data_center_repair_decision_data_reliability",),
        {"target_date": "2026-07-13", "asset_codes": ["000001.SZ"]},
    ),
    (
        "decision.refresh.recommendations",
        "decision_refresh_recommendations",
        ("decision_workflow_refresh_recommendations",),
        {"account_id": "account-1"},
    ),
    (
        "decision.update.recommendation_action",
        "decision_update_recommendation_action",
        ("decision_workflow_apply_recommendation_action",),
        {"recommendation_id": "recommendation-1", "action": "watch"},
    ),
    (
        "decision.create.transition_plan",
        "decision_create_transition_plan",
        ("decision_workflow_generate_transition_plan",),
        {"account_id": "account-1"},
    ),
    (
        "decision.update.transition_plan",
        "decision_update_transition_plan",
        ("decision_workflow_update_transition_plan",),
        {"plan_id": "plan-1", "orders": []},
    ),
    (
        "equity.run.valuation_repair_scan",
        "equity_run_valuation_repair_scan",
        ("scan_valuation_repairs",),
        {"universe": "all_active"},
    ),
    (
        "equity.sync.valuation_data",
        "equity_sync_valuation_data",
        ("sync_valuation_data",),
        {"days_back": 1},
    ),
    (
        "equity.create.valuation_quality_snapshot",
        "equity_create_valuation_quality_snapshot",
        ("validate_valuation_data",),
        {"as_of_date": "2026-07-13"},
    ),
    (
        "factor.create.portfolio",
        "factor_create_portfolio",
        ("create_factor_portfolio",),
        {"config_name": "balanced"},
    ),
    (
        "fund.create.performance_snapshot",
        "fund_create_performance_snapshot",
        ("get_fund_performance",),
        {"fund_code": "000001.OF", "period": "1y"},
    ),
    (
        "rotation.generate.signal",
        "rotation_generate_signal",
        ("generate_rotation_signal",),
        {"config_name": "momentum"},
    ),
    (
        "sentiment.execute.analysis",
        "sentiment_execute_analysis",
        ("analyze_sentiment",),
        {"payload": {"text": "market sentiment improved"}},
    ),
    (
        "sentiment.execute.batch_analysis",
        "sentiment_execute_batch_analysis",
        ("batch_analyze_sentiment",),
        {"payload": {"texts": ["positive", "negative"]}},
    ),
]


@pytest.mark.parametrize(
    ("capability_key", "executor_ref", "legacy_tool_names", "arguments"),
    WORKFLOW_CASES,
)
def test_remaining_workflows_require_preview_and_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
):
    import agomtradepro_mcp.server as server_module

    calls = []

    def fake_handler(preview_only=False, idempotency_key=None, **kwargs):
        calls.append({"preview_only": preview_only, **kwargs})
        return {
            "success": True,
            "preview_only": preview_only,
            "legacy_tool_names": list(legacy_tool_names),
        }

    monkeypatch.setitem(
        server_module.INTERNAL_GOVERNED_HANDLERS,
        executor_ref,
        fake_handler,
    )
    request_arguments = {
        **arguments,
        "idempotency_key": f"test-{capability_key}",
    }

    preview = server_module.CORE_DISPATCHER.call(
        capability_key=capability_key,
        arguments=request_arguments,
        context={"mcp_role": "staff"},
    )

    assert "agom_capability_call"
    assert preview["status"] == "confirmation_required"
    assert preview["preview_result"]["preview_only"] is True
    assert calls == [{"preview_only": True, **arguments}]

    committed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview["confirmation_token"],
        approve=True,
    )

    assert committed["status"] == "completed"
    assert committed["result"]["preview_only"] is False
    assert calls[-1] == {"preview_only": False, **arguments}


@pytest.mark.parametrize(
    ("capability_key", "executor_ref", "legacy_tool_names", "arguments"),
    WORKFLOW_CASES,
)
def test_remaining_workflow_handlers_have_side_effect_free_preview(
    monkeypatch: pytest.MonkeyPatch,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
):
    import agomtradepro_mcp.server as server_module

    class _AgentRuntime:
        @staticmethod
        def get_task(task_id):
            return {"id": task_id, "status": "needs_human"}

    class _Alpha:
        @staticmethod
        def get_ops_inference_overview():
            return {"active_model": {"name": "alpha-v1"}, "recent_tasks": []}

        @staticmethod
        def get_ops_qlib_data_overview():
            return {"local_data_status": {"status": "fresh"}, "recent_tasks": []}

    class _DecisionWorkflow:
        @staticmethod
        def get_transition_plan(plan_id):
            return {"id": plan_id, "status": "draft", "orders": []}

    class _Factor:
        @staticmethod
        def get_all_configs():
            return [{"name": "balanced", "id": 1}]

    class _Fund:
        @staticmethod
        def get_nav_history(fund_code, limit):
            assert fund_code == "000001.OF"
            assert limit == 5000
            return [{"nav_date": "2026-07-11", "unit_nav": "1.1"}]

    class _Rotation:
        @staticmethod
        def get_all_configs():
            return [{"name": "momentum", "id": 2}]

    class _FakeClient:
        agent_runtime = _AgentRuntime()
        alpha = _Alpha()
        decision_workflow = _DecisionWorkflow()
        factor = _Factor()
        fund = _Fund()
        rotation = _Rotation()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    handler = server_module.INTERNAL_GOVERNED_HANDLERS[executor_ref]

    preview = handler(**arguments, preview_only=True)

    assert capability_key
    assert legacy_tool_names
    assert preview["success"] is True
    assert preview["preview_only"] is True
