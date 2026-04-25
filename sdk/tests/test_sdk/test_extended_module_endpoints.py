"""Endpoint contract tests for newly added SDK modules."""

from unittest.mock import ANY, patch

import pytest

from agomtradepro import AgomTradeProClient


@pytest.fixture
def client():
    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


@pytest.mark.parametrize(
    "case",
    [
        (lambda c: c.ai_provider.list_providers(), "GET", "/api/ai/providers/"),
        (lambda c: c.ai_provider.get_provider(7), "GET", "/api/ai/providers/7/"),
        (
            lambda c: c.ai_provider.create_provider({"name": "p1"}),
            "POST",
            "/api/ai/providers/",
            {"json": {"name": "p1"}},
        ),
        (
            lambda c: c.ai_provider.update_provider(7, {"name": "p2"}),
            "PATCH",
            "/api/ai/providers/7/",
            {"json": {"name": "p2"}},
        ),
        (lambda c: c.ai_provider.delete_provider(7), "DELETE", "/api/ai/providers/7/"),
        (
            lambda c: c.ai_provider.toggle_provider(7),
            "POST",
            "/api/ai/providers/7/toggle_active/",
            {"json": {}},
        ),
        (
            lambda c: c.ai_provider.provider_usage_stats(7),
            "GET",
            "/api/ai/providers/7/usage_stats/",
        ),
        (lambda c: c.ai_provider.overall_stats(), "GET", "/api/ai/providers/overall_stats/"),
        (
            lambda c: c.ai_provider.list_usage_logs(provider_id=7, status="success"),
            "GET",
            "/api/ai/logs/",
            {"params": {"provider": 7, "status": "success"}},
        ),
        (lambda c: c.prompt.list_templates(), "GET", "/api/prompt/templates/"),
        (lambda c: c.prompt.get_template(3), "GET", "/api/prompt/templates/3/"),
        (
            lambda c: c.prompt.create_template({"name": "t1"}),
            "POST",
            "/api/prompt/templates/",
            {"json": {"name": "t1"}},
        ),
        (
            lambda c: c.prompt.update_template(3, {"name": "t2"}),
            "PATCH",
            "/api/prompt/templates/3/",
            {"json": {"name": "t2"}},
        ),
        (lambda c: c.prompt.delete_template(3), "DELETE", "/api/prompt/templates/3/"),
        (lambda c: c.prompt.list_chains(), "GET", "/api/prompt/chains/"),
        (
            lambda c: c.prompt.create_chain({"name": "c1"}),
            "POST",
            "/api/prompt/chains/",
            {"json": {"name": "c1"}},
        ),
        (lambda c: c.prompt.list_logs(), "GET", "/api/prompt/logs/"),
        (lambda c: c.prompt.chat({"messages": []}), "POST", "/api/prompt/chat"),
        (
            lambda c: c.prompt.generate_report({"template_id": 1}),
            "POST",
            "/api/prompt/reports/generate",
            {"json": {"template_id": 1}},
        ),
        (
            lambda c: c.prompt.generate_signal({"template_id": 1}),
            "POST",
            "/api/prompt/signals/generate",
            {"json": {"template_id": 1}},
        ),
        (lambda c: c.prompt.chat_providers(), "GET", "/api/prompt/chat/providers"),
        (lambda c: c.prompt.chat_models(), "GET", "/api/prompt/chat/models"),
        (
            lambda c: c.audit.get_summary(),
            "GET",
            "/api/audit/summary/",
            {"params": {"start_date": ANY, "end_date": ANY}},
        ),
        (
            lambda c: c.audit.generate_report({"days": 7}),
            "POST",
            "/api/audit/reports/generate/",
            {"json": {"days": 7}},
        ),
        (
            lambda c: c.audit.get_attribution_chart_data(12),
            "GET",
            "/api/audit/attribution-chart-data/12/",
        ),
        (
            lambda c: c.audit.indicator_performance("CPI"),
            "GET",
            "/api/audit/indicator-performance/CPI/",
        ),
        (
            lambda c: c.audit.indicator_performance_chart(9),
            "GET",
            "/api/audit/indicator-performance-data/9/",
        ),
        (
            lambda c: c.audit.validate_all_indicators(),
            "POST",
            "/api/audit/validate-all-indicators/",
            {"json": {"start_date": ANY, "end_date": ANY}},
        ),
        (
            lambda c: c.audit.update_threshold({"threshold": 0.3}),
            "POST",
            "/api/audit/update-threshold/",
            {"json": {"threshold": 0.3}},
        ),
        (
            lambda c: c.audit.threshold_validation_data(5),
            "GET",
            "/api/audit/threshold-validation-data/5/",
        ),
        (lambda c: c.audit.run_validation({"force": True}), "POST", "/api/audit/run-validation/"),
        (lambda c: c.events.status(), "GET", "/api/events/status/"),
        (lambda c: c.events.publish({"event_type": "test"}), "POST", "/api/events/publish/"),
        (
            lambda c: c.events.query({"event_type": "test"}),
            "GET",
            "/api/events/query/",
            {"params": {"event_type": "test"}},
        ),
        (lambda c: c.events.metrics(), "GET", "/api/events/metrics/"),
        (
            lambda c: c.events.replay({"event_ids": [1]}),
            "POST",
            "/api/events/replay/",
            {"json": {"event_ids": [1]}},
        ),
        (lambda c: c.decision_rhythm.list_quotas(), "GET", "/api/decision-rhythm/quotas/"),
        (lambda c: c.decision_rhythm.list_cooldowns(), "GET", "/api/decision-rhythm/cooldowns/"),
        (lambda c: c.decision_rhythm.list_requests(), "GET", "/api/decision-rhythm/requests/"),
        (
            lambda c: c.decision_rhythm.submit({"request_type": "rebalance"}),
            "POST",
            "/api/decision-rhythm/submit/",
        ),
        (
            lambda c: c.decision_rhythm.submit_batch({"requests": []}),
            "POST",
            "/api/decision-rhythm/submit-batch/",
            {"json": {"requests": []}},
        ),
        (lambda c: c.decision_rhythm.summary(), "GET", "/api/decision-rhythm/summary/"),
        (
            lambda c: c.decision_rhythm.summary({"days": 7}),
            "GET",
            "/api/decision-rhythm/summary/",
            {"params": {"days": 7}},
        ),
        (
            lambda c: c.decision_rhythm.reset_quota({"user_id": "u1"}),
            "POST",
            "/api/decision-rhythm/reset-quota/",
            {"json": {"user_id": "u1"}},
        ),
        (lambda c: c.decision_rhythm.trend_data(), "GET", "/api/decision-rhythm/trend-data/"),
        (
            lambda c: c.decision_rhythm.trend_data({"days": 30}),
            "POST",
            "/api/decision-rhythm/trend-data/",
            {"json": {"days": 30}},
        ),
        (
            lambda c: c.decision_rhythm.update_quota({"limit": 5}),
            "POST",
            "/api/decision-rhythm/quota/update/",
            {"json": {"limit": 5}},
        ),
        (lambda c: c.beta_gate.list_configs(), "GET", "/api/beta-gate/configs/"),
        (lambda c: c.beta_gate.get_config("cfg1"), "GET", "/api/beta-gate/configs/cfg1/"),
        (
            lambda c: c.beta_gate.create_config({"name": "cfg"}),
            "POST",
            "/api/beta-gate/configs/",
            {"json": {"name": "cfg"}},
        ),
        (
            lambda c: c.beta_gate.update_config("cfg1", {"name": "cfg2"}),
            "PATCH",
            "/api/beta-gate/configs/cfg1/",
            {"json": {"name": "cfg2"}},
        ),
        (lambda c: c.beta_gate.delete_config("cfg1"), "DELETE", "/api/beta-gate/configs/cfg1/"),
        (lambda c: c.beta_gate.test_gate({"scenario": "smoke"}), "POST", "/api/beta-gate/test/"),
        (
            lambda c: c.beta_gate.version_compare({"from": "v1", "to": "v2"}),
            "POST",
            "/api/beta-gate/version/compare/",
            {"json": {"from": "v1", "to": "v2"}},
        ),
        (
            lambda c: c.beta_gate.rollback_config("cfg1"),
            "POST",
            "/api/beta-gate/config/rollback/cfg1/",
            {"json": {}},
        ),
        (
            lambda c: c.beta_gate.suggest_config({"signal": "s1"}),
            "POST",
            "/api/beta-gate/config/suggest/",
            {"json": {"signal": "s1"}},
        ),
        (
            lambda c: c.alpha.get_stock_scores(),
            "GET",
            "/api/alpha/scores/",
            {"params": {"universe": "csi300", "top_n": 30}},
        ),
        (
            lambda c: c.alpha.get_stock_scores("csi500", "2026-02-05", 10),
            "GET",
            "/api/alpha/scores/",
            {"params": {"universe": "csi500", "trade_date": "2026-02-05", "top_n": 10}},
        ),
        (
            lambda c: c.alpha.upload_scores(
                scores=[{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                universe_id="csi300",
                asof_date="2026-03-08",
                intended_trade_date="2026-03-10",
            ),
            "POST",
            "/api/alpha/scores/upload/",
            {
                "json": {
                    "universe_id": "csi300",
                    "asof_date": "2026-03-08",
                    "intended_trade_date": "2026-03-10",
                    "model_id": "local_qlib",
                    "scope": "user",
                    "scores": [{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                }
            },
        ),
        (
            lambda c: c.alpha.upload_scores(
                scores=[{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                universe_id="csi300",
                asof_date="2026-03-08",
                intended_trade_date="2026-03-10",
                model_artifact_hash="hash-123",
            ),
            "POST",
            "/api/alpha/scores/upload/",
            {
                "json": {
                    "universe_id": "csi300",
                    "asof_date": "2026-03-08",
                    "intended_trade_date": "2026-03-10",
                    "model_id": "local_qlib",
                    "model_artifact_hash": "hash-123",
                    "scope": "user",
                    "scores": [{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                }
            },
        ),
        (lambda c: c.alpha.get_provider_status(), "GET", "/api/alpha/providers/status/"),
        (lambda c: c.alpha.get_available_universes(), "GET", "/api/alpha/universes/"),
        (lambda c: c.alpha.check_health(), "GET", "/api/alpha/health/"),
        (lambda c: c.alpha_trigger.list_triggers(), "GET", "/api/alpha-triggers/triggers/"),
        (lambda c: c.alpha_trigger.get_trigger("t1"), "GET", "/api/alpha-triggers/triggers/t1/"),
        (
            lambda c: c.alpha_trigger.create_trigger({"name": "t2"}),
            "POST",
            "/api/alpha-triggers/create/",
            {"json": {"name": "t2"}},
        ),
        (
            lambda c: c.alpha_trigger.evaluate({"trigger_id": "t1"}),
            "POST",
            "/api/alpha-triggers/evaluate/",
        ),
        (
            lambda c: c.alpha_trigger.check_invalidation({"trigger_id": "t1"}),
            "POST",
            "/api/alpha-triggers/check-invalidation/",
            {"json": {"trigger_id": "t1"}},
        ),
        (
            lambda c: c.alpha_trigger.generate_candidate({"symbol": "AAPL"}),
            "POST",
            "/api/alpha-triggers/generate-candidate/",
            {"json": {"symbol": "AAPL"}},
        ),
        (lambda c: c.alpha_trigger.performance(), "GET", "/api/alpha-triggers/performance/"),
        (
            lambda c: c.alpha_trigger.performance({"days": 30}),
            "GET",
            "/api/alpha-triggers/performance/",
            {"params": {"days": 30}},
        ),
        (lambda c: c.alpha_trigger.list_candidates(), "GET", "/api/alpha-triggers/candidates/"),
        (
            lambda c: c.alpha_trigger.get_candidate("c1"),
            "GET",
            "/api/alpha-triggers/candidates/c1/",
        ),
        (
            lambda c: c.alpha_trigger.update_candidate_status("c1", "ACTIONABLE"),
            "POST",
            "/api/alpha-triggers/candidates/c1/update-status/",
            {"json": {"status": "ACTIONABLE"}},
        ),
        (
            lambda c: c.strategy.bind_portfolio_strategy(1, 12),
            "POST",
            "/api/strategy/bind-strategy/",
            {"json": {"portfolio_id": 1, "strategy_id": 12}},
        ),
        (
            lambda c: c.strategy.unbind_portfolio_strategy(1),
            "POST",
            "/api/strategy/unbind-strategy/",
            {"json": {"portfolio_id": 1}},
        ),
        (
            lambda c: c.strategy.list_ai_strategy_configs(strategy_id=12, approval_mode="auto"),
            "GET",
            "/api/strategy/ai-configs/",
            {"params": {"limit": 100, "strategy": 12, "approval_mode": "auto"}},
        ),
        (
            lambda c: c.strategy.create_ai_strategy_config(
                strategy_id=12,
                ai_provider_id=3,
                temperature=0.2,
                max_tokens=1200,
                approval_mode="conditional",
                confidence_threshold=0.75,
            ),
            "POST",
            "/api/strategy/ai-configs/",
            {
                "json": {
                    "strategy": 12,
                    "prompt_template": None,
                    "chain_config": None,
                    "ai_provider": 3,
                    "temperature": 0.2,
                    "max_tokens": 1200,
                    "approval_mode": "conditional",
                    "confidence_threshold": 0.75,
                }
            },
        ),
        (
            lambda c: c.strategy.update_ai_strategy_config(8, temperature=0.4),
            "PATCH",
            "/api/strategy/ai-configs/8/",
            {"json": {"temperature": 0.4}},
        ),
        (lambda c: c.dashboard.summary_v1(), "GET", "/api/dashboard/v1/summary/"),
        (lambda c: c.dashboard.position_detail("AAPL"), "GET", "/api/dashboard/position/AAPL/"),
        (lambda c: c.dashboard.positions(), "GET", "/api/dashboard/positions/"),
        (lambda c: c.dashboard.allocation(), "GET", "/api/dashboard/allocation/"),
        (lambda c: c.dashboard.performance(), "GET", "/api/dashboard/performance/"),
        (lambda c: c.dashboard.regime_quadrant_v1(), "GET", "/api/dashboard/v1/regime-quadrant/"),
        (lambda c: c.dashboard.equity_curve_v1(), "GET", "/api/dashboard/v1/equity-curve/"),
        (lambda c: c.dashboard.signal_status_v1(), "GET", "/api/dashboard/v1/signal-status/"),
        (lambda c: c.dashboard.alpha_stocks(), "GET", "/api/dashboard/alpha/stocks/"),
        (
            lambda c: c.dashboard.alpha_refresh(top_n=10, portfolio_id=135),
            "POST",
            "/api/dashboard/alpha/refresh/",
            {"data": {"top_n": 10, "portfolio_id": 135}},
        ),
        (
            lambda c: c.dashboard.alpha_provider_status(),
            "GET",
            "/api/dashboard/alpha/provider-status/",
        ),
        (lambda c: c.dashboard.alpha_coverage(), "GET", "/api/dashboard/alpha/coverage/"),
        (lambda c: c.dashboard.alpha_ic_trends(), "GET", "/api/dashboard/alpha/ic-trends/"),
        (
            lambda c: c.asset_analysis.get_weight_configs(),
            "GET",
            "/api/asset-analysis/weight-configs/",
        ),
        (
            lambda c: c.asset_analysis.multidim_screen({"asset_type": "equity"}),
            "POST",
            "/api/asset-analysis/multidim-screen/",
        ),
        (
            lambda c: c.asset_analysis.get_current_weight(),
            "GET",
            "/api/asset-analysis/current-weight/",
        ),
        (
            lambda c: c.asset_analysis.screen_asset_pool("equity"),
            "GET",
            "/api/asset-analysis/screen/equity/",
        ),
        (
            lambda c: c.asset_analysis.screen_asset_pool("equity", {"top_n": 10}),
            "POST",
            "/api/asset-analysis/screen/equity/",
            {"json": {"top_n": 10}},
        ),
        (lambda c: c.asset_analysis.pool_summary(), "GET", "/api/asset-analysis/pool-summary/"),
        (
            lambda c: c.asset_analysis.pool_summary({"asset_type": "equity"}),
            "GET",
            "/api/asset-analysis/pool-summary/",
            {"params": {"asset_type": "equity"}},
        ),
        (lambda c: c.sentiment.health(), "GET", "/api/sentiment/health/"),
        (lambda c: c.sentiment.analyze({"text": "hello"}), "POST", "/api/sentiment/analyze/"),
        (
            lambda c: c.sentiment.batch_analyze({"texts": ["a", "b"]}),
            "POST",
            "/api/sentiment/batch-analyze/",
            {"json": {"texts": ["a", "b"]}},
        ),
        (lambda c: c.sentiment.get_index(), "GET", "/api/sentiment/index/"),
        (
            lambda c: c.sentiment.get_index({"window_days": 7}),
            "GET",
            "/api/sentiment/index/",
            {"params": {"window_days": 7}},
        ),
        (lambda c: c.sentiment.index_range(), "GET", "/api/sentiment/index/range/"),
        (
            lambda c: c.sentiment.index_range({"start_date": "2026-01-01"}),
            "GET",
            "/api/sentiment/index/range/",
            {"params": {"start_date": "2026-01-01"}},
        ),
        (lambda c: c.sentiment.index_recent(), "GET", "/api/sentiment/index/recent/"),
        (
            lambda c: c.sentiment.index_recent({"limit": 10}),
            "GET",
            "/api/sentiment/index/recent/",
            {"params": {"limit": 10}},
        ),
        (lambda c: c.sentiment.clear_cache(), "POST", "/api/sentiment/cache/clear/", {"json": {}}),
        (lambda c: c.task_monitor.get_task_status("task-1"), "GET", "/api/system/status/task-1/"),
        (lambda c: c.task_monitor.list_tasks(), "GET", "/api/system/list/"),
        (
            lambda c: c.task_monitor.statistics(task_name="sync_equity_valuation_task"),
            "GET",
            "/api/system/statistics/",
            {"params": {"task_name": "sync_equity_valuation_task"}},
        ),
        (lambda c: c.task_monitor.dashboard(), "GET", "/api/system/dashboard/"),
        (lambda c: c.task_monitor.celery_health(), "GET", "/api/system/celery/health/"),
        (lambda c: c.filter.list_filters(), "GET", "/api/filter/indicators/"),
        (lambda c: c.filter.get_filter(indicator_code="PMI"), "GET", "/api/filter/config/PMI/"),
        (
            lambda c: c.filter.create_filter({"name": "f1"}),
            "POST",
            "/api/filter/",
            {"json": {"name": "f1", "filter_type": "HP", "save_results": True}},
        ),
        (
            lambda c: c.filter.update_filter(11, {"name": "f2"}),
            "PATCH",
            "/api/filter/11/",
            {"json": {"name": "f2"}},
        ),
        (lambda c: c.filter.delete_filter(11), "DELETE", "/api/filter/11/"),
        (lambda c: c.filter.health(), "GET", "/api/filter/health/"),
        (
            lambda c: c.decision_workflow.precheck("cand-1"),
            "POST",
            "/api/decision-workflow/precheck/",
            {"json": {"candidate_id": "cand-1"}},
        ),
        (
            lambda c: c.decision_workflow.get_funnel_context("trade-1"),
            "GET",
            "/api/decision/funnel/context/",
            {"params": {"trade_id": "trade-1"}},
        ),
        (
            lambda c: c.decision_workflow.get_funnel_context("trade-1", backtest_id=123),
            "GET",
            "/api/decision/funnel/context/",
            {"params": {"trade_id": "trade-1", "backtest_id": 123}},
        ),
        (lambda c: c.pulse.get_current(), "GET", "/api/pulse/current/"),
        (lambda c: c.pulse.get_history(), "GET", "/api/pulse/history/", {"params": {"limit": 30}}),
        (
            lambda c: c.pulse.get_history(limit=5),
            "GET",
            "/api/pulse/history/",
            {"params": {"limit": 5}},
        ),
        (lambda c: c.pulse.calculate(), "POST", "/api/pulse/calculate/"),
        (lambda c: c.rotation.list_regimes(), "GET", "/api/rotation/regimes/"),
        (lambda c: c.rotation.list_templates(), "GET", "/api/rotation/templates/"),
        (lambda c: c.rotation.list_assets(), "GET", "/api/rotation/assets/"),
        (lambda c: c.rotation.get_asset("510300"), "GET", "/api/rotation/assets/510300/"),
        (
            lambda c: c.rotation.create_asset({"code": "510300", "name": "沪深300ETF"}),
            "POST",
            "/api/rotation/assets/",
            {"json": {"code": "510300", "name": "沪深300ETF"}},
        ),
        (
            lambda c: c.rotation.update_asset("510300", {"name": "沪深300ETF增强"}, partial=False),
            "PUT",
            "/api/rotation/assets/510300/",
            {"json": {"name": "沪深300ETF增强"}},
        ),
        (
            lambda c: c.rotation.update_asset("510300", {"is_active": False}, partial=True),
            "PATCH",
            "/api/rotation/assets/510300/",
            {"json": {"is_active": False}},
        ),
        (lambda c: c.rotation.delete_asset("510300"), "DELETE", "/api/rotation/assets/510300/"),
        (
            lambda c: c.rotation.import_default_assets(),
            "POST",
            "/api/rotation/assets/import-defaults/",
            {"json": {}},
        ),
        (
            lambda c: c.rotation.export_assets("csv"),
            "GET",
            "/api/rotation/assets/export/",
            {"params": {"format": "csv"}},
        ),
        (lambda c: c.rotation.list_account_configs(), "GET", "/api/rotation/account-configs/"),
        (lambda c: c.rotation.get_account_config(5), "GET", "/api/rotation/account-configs/5/"),
        (
            lambda c: c.rotation.get_account_config_by_account(308),
            "GET",
            "/api/rotation/account-configs/by-account/308/",
        ),
        (
            lambda c: c.rotation.create_account_config(
                {"account": 308, "risk_tolerance": "moderate"}
            ),
            "POST",
            "/api/rotation/account-configs/",
            {"json": {"account": 308, "risk_tolerance": "moderate"}},
        ),
        (
            lambda c: c.rotation.update_account_config(5, {"is_enabled": True}, partial=False),
            "PUT",
            "/api/rotation/account-configs/5/",
            {"json": {"is_enabled": True}},
        ),
        (
            lambda c: c.rotation.update_account_config(5, {"is_enabled": True}, partial=True),
            "PATCH",
            "/api/rotation/account-configs/5/",
            {"json": {"is_enabled": True}},
        ),
        (
            lambda c: c.rotation.delete_account_config(5),
            "DELETE",
            "/api/rotation/account-configs/5/",
        ),
        (
            lambda c: c.rotation.apply_template_to_account_config(5, "moderate"),
            "POST",
            "/api/rotation/account-configs/5/apply-template/",
            {"json": {"template_key": "moderate"}},
        ),
        (
            lambda c: c.simulated_trading.delete_account(5),
            "DELETE",
            "/api/simulated-trading/accounts/5/",
        ),
        (
            lambda c: c.simulated_trading.batch_delete_accounts([5, 6]),
            "POST",
            "/api/simulated-trading/accounts/batch-delete/",
            {"json": {"account_ids": [5, 6]}},
        ),
        (
            lambda c: c.simulated_trading.run_daily_inspection(
                5,
                strategy_id=12,
                auto_create_proposal=True,
            ),
            "POST",
            "/api/simulated-trading/accounts/5/inspections/run/",
            {"json": {"strategy_id": 12, "auto_create_proposal": True}},
        ),
        (
            lambda c: c.simulated_trading.run_auto_trading(account_ids=[5, 6]),
            "POST",
            "/api/simulated-trading/auto-trading/run/",
            {"json": {"account_ids": [5, 6]}},
        ),
    ],
)
def test_extended_module_endpoint_contract(client, case):
    if len(case) == 3:
        invoker, expected_method, expected_endpoint = case
        expected_kwargs = {}
    else:
        invoker, expected_method, expected_endpoint, expected_kwargs = case
    with patch.object(client, "_request", return_value={"results": []}) as mock_request:
        invoker(client)
        args, kwargs = mock_request.call_args
        assert args[0] == expected_method
        assert args[1] == expected_endpoint
        for k, v in expected_kwargs.items():
            assert kwargs.get(k) == v
