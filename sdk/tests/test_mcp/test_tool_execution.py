"""Execution smoke tests for extended MCP tools."""

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.ai_provider = SimpleNamespace(
            list_providers=lambda: [{"id": 1}],
            get_provider=lambda provider_id: {"id": provider_id},
            create_provider=lambda payload: {"id": 2, **payload},
            update_provider=lambda provider_id, payload: {"id": provider_id, **payload},
            toggle_provider=lambda provider_id: {"id": provider_id, "is_active": True},
            list_usage_logs=lambda provider_id=None, status=None: [
                {"provider_id": provider_id, "status": status}
            ],
        )
        self.prompt = SimpleNamespace(
            list_templates=lambda: [{"id": 1}],
            create_template=lambda payload: {"id": 2, **payload},
            list_chains=lambda: [{"id": 3}],
            chat=lambda payload: {"content": "ok", "payload": payload},
            generate_report=lambda payload: {"report": True, "payload": payload},
            generate_signal=lambda payload: {"signal": True, "payload": payload},
        )
        self.audit = SimpleNamespace(
            get_summary=lambda: {"ok": True},
            generate_report=lambda payload: {"ok": True, "payload": payload},
            run_validation=lambda payload: {"ok": True, "payload": payload},
            validate_all_indicators=lambda: {"ok": True},
            update_threshold=lambda payload: {"ok": True, "payload": payload},
        )
        self.events = SimpleNamespace(
            publish=lambda payload: {"published": True, "payload": payload},
            query=lambda payload: {"items": [], "payload": payload},
            metrics=lambda: {"qps": 1},
            status=lambda: {"status": "ok"},
            replay=lambda payload: {"replayed": True, "payload": payload},
        )
        self.decision_rhythm = SimpleNamespace(
            list_quotas=lambda: [{"id": 1}],
            list_requests=lambda: [{"id": 2}],
            submit=lambda payload: {"submitted": True, "payload": payload},
            submit_batch=lambda payload: {"submitted": True, "payload": payload},
            summary=lambda payload=None: {"summary": True, "payload": payload},
            reset_quota=lambda payload: {"reset": True, "payload": payload},
        )
        self.decision_workflow = SimpleNamespace(
            precheck=lambda candidate_id: {"candidate_id": candidate_id, "ok": True},
            get_funnel_context=lambda trade_id="unknown", backtest_id=None: {
                "trade_id": trade_id,
                "backtest_id": backtest_id,
                "data": {
                    "step3_sectors": {
                        "rotation_data_source": "stored_signal",
                        "rotation_is_stale": False,
                        "rotation_warning_message": None,
                        "rotation_signal_date": "2026-03-31",
                    }
                },
                "ok": True,
            },
        )
        self.pulse = SimpleNamespace(
            get_current=lambda: {"composite_score": 0.2, "regime_strength": "moderate"},
            get_history=lambda limit=20: [{"limit": limit, "composite_score": 0.2}],
            get_navigator=lambda: {"regime_name": "Recovery", "movement": {"direction": "stable"}},
            get_action_recommendation=lambda: {
                "risk_budget_pct": 0.7,
                "asset_weights": {"equity": 0.6},
            },
        )
        self.beta_gate = SimpleNamespace(
            list_configs=lambda: [{"config_id": "c1"}],
            create_config=lambda payload: {"config_id": "c2", "payload": payload},
            test_gate=lambda payload: {"passed": True, "payload": payload},
            version_compare=lambda payload: {"diff": {}, "payload": payload},
            rollback_config=lambda config_id: {"rolled_back": config_id},
        )
        self.alpha_trigger = SimpleNamespace(
            list_triggers=lambda: [{"id": "t1"}],
            create_trigger=lambda payload: {"id": "t2", "payload": payload},
            evaluate=lambda payload: {"evaluated": True, "payload": payload},
            check_invalidation=lambda payload: {"invalidated": False, "payload": payload},
            generate_candidate=lambda payload: {"candidate": True, "payload": payload},
            performance=lambda payload=None: {"performance": True, "payload": payload},
        )
        self.dashboard = SimpleNamespace(
            summary_v1=lambda: {"summary": True},
            regime_quadrant_v1=lambda: {"quadrant": "Recovery"},
            equity_curve_v1=lambda: {"curve": []},
            signal_status_v1=lambda: {"status": []},
            alpha_decision_chain_v1=lambda top_n=10, max_candidates=5, max_pending=10: {
                "overview": {
                    "top_ranked_count": top_n,
                    "actionable_count": min(top_n, max_candidates),
                    "pending_count": min(top_n, max_pending),
                },
                "top_stocks": [],
                "actionable_candidates": [],
                "pending_requests": [],
            },
            alpha_stocks=lambda top_n=10, portfolio_id=None, pool_mode=None: {
                "success": True,
                "data": {
                    "top_candidates": [],
                    "pending_requests": [{"id": 1, "stock_code": "600519.SH"}],
                    "meta": {
                        "refresh_status": "queued",
                        "async_task_id": "task-alpha-1",
                        "poll_after_ms": 5000,
                        "hardcoded_fallback_used": False,
                        "no_recommendation_reason": "No account-scope Alpha cache.",
                        "scope_hash": "scope-1",
                        "pool_mode": pool_mode,
                    },
                },
                "contract": {
                    "recommendation_ready": False,
                    "must_not_treat_as_recommendation": True,
                    "async_refresh_queued": True,
                    "refresh_status": "queued",
                    "async_task_id": "task-alpha-1",
                    "poll_after_ms": 5000,
                    "hardcoded_fallback_used": False,
                },
            },
            alpha_refresh=lambda top_n=10, portfolio_id=None, pool_mode=None: {
                "success": True,
                "task_id": "task-alpha-refresh-1",
                "pool_mode": pool_mode,
                "contract": {
                    "recommendation_ready": False,
                    "must_not_treat_as_recommendation": True,
                    "async_refresh_queued": True,
                    "refresh_status": "queued",
                    "async_task_id": "task-alpha-refresh-1",
                    "poll_after_ms": 5000,
                    "hardcoded_fallback_used": False,
                },
            },
            positions=lambda: {"positions": []},
            allocation=lambda: {"allocation": []},
        )
        self.simulated_trading = SimpleNamespace(
            list_accounts=lambda status=None, account_type=None, limit=20: [
                {"id": 1, "status": status, "account_type": account_type, "limit": limit}
            ],
            get_account=lambda account_id: {"id": account_id},
            delete_account=lambda account_id: {"success": True, "account_id": account_id},
            batch_delete_accounts=lambda account_ids: {
                "success": True,
                "deleted_account_ids": account_ids,
            },
            create_account=lambda name, initial_capital, start_date: {
                "id": 2,
                "name": name,
                "initial_capital": initial_capital,
                "start_date": str(start_date),
            },
            execute_trade=lambda account_id, asset_code, side, quantity, price=None: {
                "account_id": account_id,
                "asset_code": asset_code,
                "side": side,
                "quantity": quantity,
                "price": price,
            },
            get_positions=lambda account_id: [{"account_id": account_id}],
            get_performance=lambda account_id: {"account_id": account_id},
            reset_account=lambda account_id, new_initial_capital=None: {
                "account_id": account_id,
                "new_initial_capital": new_initial_capital,
            },
            close_position=lambda account_id, asset_code: {
                "account_id": account_id,
                "asset_code": asset_code,
            },
            run_daily_inspection=lambda account_id, strategy_id=None, inspection_date=None: {
                "account_id": account_id,
                "strategy_id": strategy_id,
                "inspection_date": inspection_date,
            },
            list_daily_inspections=lambda account_id, limit=20, inspection_date=None: {
                "account_id": account_id,
                "limit": limit,
                "inspection_date": inspection_date,
            },
        )
        self.account = SimpleNamespace(
            get_trading_cost_configs=lambda limit=100: [{"id": 1, "portfolio": 1, "limit": limit}],
            list_accounts=lambda status=None, account_type=None, limit=20: [
                {"id": 1, "status": status}
            ],
            get_account=lambda account_id: {"id": account_id},
            create_account=lambda name, initial_capital, start_date, account_type=None: {
                "id": 2,
                "name": name,
            },
            get_account_positions=lambda account_id: [{"account_id": account_id}],
            get_account_performance=lambda account_id: {"account_id": account_id},
        )
        self.asset_analysis = SimpleNamespace(
            multidim_screen=lambda payload: {"screen": True, "payload": payload},
            get_weight_configs=lambda: {"weights": []},
            get_current_weight=lambda: {"weight": {}},
            screen_asset_pool=lambda asset_type, payload=None: {
                "asset_type": asset_type,
                "payload": payload,
            },
            pool_summary=lambda payload=None: {"summary": True, "payload": payload},
        )
        self.sentiment = SimpleNamespace(
            analyze=lambda payload: {"score": 0.1, "payload": payload},
            batch_analyze=lambda payload: {"scores": [], "payload": payload},
            get_index=lambda payload=None: {"index": 0.0, "payload": payload},
            index_recent=lambda payload=None: {"recent": [], "payload": payload},
            health=lambda: {"ok": True},
            clear_cache=lambda: {"cleared": True},
        )
        self.task_monitor = SimpleNamespace(
            get_task_status=lambda task_id: {"task_id": task_id, "status": "done"},
            list_tasks=lambda: {"tasks": []},
            statistics=lambda: {"stats": {}},
            dashboard=lambda: {"dashboard": {}},
            celery_health=lambda: {"celery": "ok"},
        )
        self.filter = SimpleNamespace(
            list_filters=lambda: [{"id": 1}],
            get_filter=lambda filter_id: {"id": filter_id},
            create_filter=lambda payload: {"id": 2, "payload": payload},
            update_filter=lambda filter_id, payload: {"id": filter_id, "payload": payload},
            delete_filter=lambda filter_id: None,
            health=lambda: {"ok": True},
        )
        self.rotation = SimpleNamespace(
            list_regimes=lambda: [{"key": "Overheat", "label": "Overheat"}],
            list_templates=lambda: [{"id": 1, "key": "moderate"}],
            list_assets=lambda: [{"code": "510300", "name": "沪深300ETF"}],
            get_asset=lambda asset_code: {"code": asset_code, "name": "沪深300ETF"},
            create_asset=lambda payload: {"code": payload["code"], **payload},
            update_asset=lambda asset_code, payload, partial=False: {
                "code": asset_code,
                "partial": partial,
                **payload,
            },
            delete_asset=lambda asset_code: {"deleted": True, "code": asset_code},
            import_default_assets=lambda: {"created": 18, "reactivated": 0, "existing": 0},
            export_assets=lambda export_format="json": {"format": export_format, "items": 18},
            list_account_configs=lambda: [{"id": 2, "account": 308}],
            get_account_config=lambda config_id: {"id": config_id, "account": 308},
            get_account_config_by_account=lambda account_id: {"id": 2, "account": account_id},
            create_account_config=lambda payload: {"id": 3, **payload},
            update_account_config=lambda config_id, payload, partial=True: {
                "id": config_id,
                "partial": partial,
                **payload,
            },
            delete_account_config=lambda config_id: {"deleted": True, "id": config_id},
            apply_template_to_account_config=lambda config_id, template_key: {
                "id": config_id,
                "template_key": template_key,
            },
        )
        self.alpha = SimpleNamespace(
            get_stock_scores=lambda universe="csi300", trade_date=None, top_n=20, user_id=None: {
                "success": True,
                "source": "cache",
                "status": "available",
                "stocks": [{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                "user_id": user_id,
                "trade_date": trade_date,
                "universe": universe,
                "top_n": top_n,
            },
            upload_scores=lambda **payload: {
                "success": True,
                "count": len(payload.get("scores", [])),
                "scope": payload.get("scope", "user"),
                "id": 99,
                "created": True,
            },
        )

    def get(self, path, params=None):
        if path == "api/account/trading-cost-configs/":
            return {
                "results": [{"id": 1, "portfolio": params.get("portfolio_id", 1) if params else 1}]
            }
        return {"ok": True, "path": path, "params": params}

    def post(self, path, json=None):
        return {"ok": True, "path": path, "json": json, "data": json or {}}

    def patch(self, path, json=None):
        return {"ok": True, "path": path, "json": json}


def _patch_extended_tool_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    module_names = [
        "agomtradepro_mcp.tools.ai_provider_tools",
        "agomtradepro_mcp.tools.prompt_tools",
        "agomtradepro_mcp.tools.audit_tools",
        "agomtradepro_mcp.tools.events_tools",
        "agomtradepro_mcp.tools.decision_rhythm_tools",
        "agomtradepro_mcp.tools.decision_workflow_tools",
        "agomtradepro_mcp.tools.beta_gate_tools",
        "agomtradepro_mcp.tools.alpha_trigger_tools",
        "agomtradepro_mcp.tools.dashboard_tools",
        "agomtradepro_mcp.tools.simulated_trading_tools",
        "agomtradepro_mcp.tools.account_tools",
        "agomtradepro_mcp.tools.asset_analysis_tools",
        "agomtradepro_mcp.tools.sentiment_tools",
        "agomtradepro_mcp.tools.task_monitor_tools",
        "agomtradepro_mcp.tools.filter_tools",
        "agomtradepro_mcp.tools.rotation_tools",
        "agomtradepro_mcp.tools.alpha_tools",
        "agomtradepro_mcp.tools.pulse_tools",
    ]
    for module_name in module_names:
        mod = importlib.import_module(module_name)
        monkeypatch.setattr(mod, "AgomTradeProClient", _FakeClient)

    audit_mod = importlib.import_module("agomtradepro_mcp.audit")
    monkeypatch.setattr(
        audit_mod,
        "get_audit_logger",
        lambda: SimpleNamespace(log_mcp_call=lambda **kwargs: None),
    )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("list_ai_providers", {}),
        ("get_ai_provider", {"provider_id": 1}),
        ("create_ai_provider", {"payload": {"name": "p1"}}),
        ("update_ai_provider", {"provider_id": 1, "payload": {"name": "p2"}}),
        ("toggle_ai_provider", {"provider_id": 1}),
        ("list_ai_usage_logs", {"provider_id": 1, "status": "success"}),
        ("list_prompt_templates", {}),
        ("create_prompt_template", {"payload": {"name": "tpl"}}),
        ("list_prompt_chains", {}),
        ("prompt_chat", {"payload": {"messages": [{"role": "user", "content": "hi"}]}}),
        ("generate_prompt_report", {"payload": {"template_id": 1}}),
        ("generate_prompt_signal", {"payload": {"template_id": 1}}),
        ("get_audit_summary", {}),
        ("generate_audit_report", {"payload": {"days": 7}}),
        ("run_audit_validation", {"payload": {"scope": "all"}}),
        ("validate_all_indicators", {}),
        ("update_audit_threshold", {"payload": {"indicator": "cpi", "value": 0.3}}),
        ("publish_event", {"payload": {"event_type": "x"}}),
        ("query_events", {"payload": {"event_type": "x"}}),
        ("get_event_metrics", {}),
        ("get_event_bus_status", {}),
        ("replay_events", {"payload": {"event_ids": [1]}}),
        ("list_decision_quotas", {}),
        ("list_decision_requests", {}),
        ("submit_decision_request", {"payload": {"request_type": "rebalance"}}),
        (
            "submit_batch_decision_request",
            {"payload": {"requests": [{"request_type": "rebalance"}]}},
        ),
        ("get_decision_rhythm_summary", {"payload": {"window_days": 7}}),
        ("reset_decision_quota", {"payload": {"user_id": "u1"}}),
        ("decision_workflow_precheck", {"candidate_id": "cand-1"}),
        ("decision_workflow_get_funnel_context", {"trade_id": "trade-1", "backtest_id": 123}),
        ("list_beta_gate_configs", {}),
        ("create_beta_gate_config", {"payload": {"name": "cfg1"}}),
        ("test_beta_gate", {"payload": {"config_id": "cfg1"}}),
        ("compare_beta_gate_version", {"payload": {"from": "v1", "to": "v2"}}),
        ("rollback_beta_gate_config", {"config_id": "cfg1"}),
        ("list_alpha_triggers", {}),
        ("create_alpha_trigger", {"payload": {"name": "t1"}}),
        ("evaluate_alpha_trigger", {"payload": {"trigger_id": "t1"}}),
        ("check_alpha_trigger_invalidation", {"payload": {"trigger_id": "t1"}}),
        ("generate_alpha_candidate", {"payload": {"symbol": "AAPL"}}),
        ("alpha_trigger_performance", {"payload": {"window_days": 30}}),
        ("get_dashboard_summary_v1", {}),
        (
            "get_dashboard_alpha_decision_chain_v1",
            {"top_n": 10, "max_candidates": 5, "max_pending": 10},
        ),
        (
            "get_dashboard_alpha_candidates",
            {"top_n": 10, "portfolio_id": 135, "pool_mode": "market"},
        ),
        (
            "trigger_dashboard_alpha_refresh",
            {"top_n": 10, "portfolio_id": 135, "pool_mode": "price_covered"},
        ),
        ("get_dashboard_regime_quadrant_v1", {}),
        ("get_dashboard_equity_curve_v1", {}),
        ("get_dashboard_signal_status_v1", {}),
        ("get_dashboard_positions", {}),
        ("get_dashboard_allocation", {}),
        ("list_simulated_accounts", {"status": "active", "limit": 5}),
        ("get_simulated_account", {"account_id": 7}),
        ("delete_simulated_account", {"account_id": 7}),
        ("batch_delete_simulated_accounts", {"account_ids": [7, 8]}),
        (
            "create_simulated_account",
            {"name": "测试账户", "initial_capital": 100000.0, "start_date": "2026-03-21"},
        ),
        (
            "execute_simulated_trade",
            {
                "account_id": 7,
                "asset_code": "510300",
                "side": "buy",
                "quantity": 100.0,
                "price": 4.2,
            },
        ),
        ("get_simulated_positions", {"account_id": 7}),
        ("get_simulated_performance", {"account_id": 7}),
        ("reset_simulated_account", {"account_id": 7, "new_initial_capital": 200000.0}),
        ("close_simulated_position", {"account_id": 7, "asset_code": "510300"}),
        (
            "run_simulated_daily_inspection",
            {"account_id": 7, "strategy_id": 2, "inspection_date": "2026-03-21"},
        ),
        (
            "list_simulated_daily_inspections",
            {"account_id": 7, "limit": 5, "inspection_date": "2026-03-21"},
        ),
        ("asset_multidim_screen", {"payload": {"asset_type": "equity"}}),
        ("get_trading_cost_configs", {"portfolio_id": 1}),
        ("get_asset_current_weight", {}),
        ("asset_pool_screen", {"asset_type": "equity", "payload": {"top_n": 10}}),
        ("asset_pool_summary", {"payload": {"asset_type": "equity"}}),
        ("analyze_sentiment", {"payload": {"text": "hello"}}),
        ("batch_analyze_sentiment", {"payload": {"texts": ["hello", "world"]}}),
        ("get_sentiment_index", {"payload": {"window_days": 7}}),
        ("get_sentiment_recent", {"payload": {"limit": 5}}),
        ("get_sentiment_health", {}),
        ("clear_sentiment_cache", {}),
        ("get_task_monitor_status", {"task_id": "task-1"}),
        ("list_task_monitor_tasks", {}),
        ("get_task_monitor_statistics", {}),
        ("get_task_monitor_dashboard", {}),
        ("get_task_monitor_celery_health", {}),
        ("list_filters", {}),
        ("get_filter", {"filter_id": 1}),
        ("create_filter", {"payload": {"name": "f1"}}),
        ("update_filter", {"filter_id": 1, "payload": {"name": "f2"}}),
        ("delete_filter", {"filter_id": 1}),
        ("get_filter_health", {}),
        ("list_rotation_regimes", {}),
        ("list_rotation_templates", {}),
        ("list_rotation_asset_master", {}),
        ("get_rotation_asset", {"asset_code": "510300"}),
        ("create_rotation_asset", {"code": "510300", "name": "沪深300ETF", "category": "equity"}),
        (
            "update_rotation_asset",
            {"asset_code": "510300", "payload": {"name": "沪深300ETF增强"}, "partial": True},
        ),
        ("delete_rotation_asset", {"asset_code": "510300"}),
        ("import_default_rotation_assets", {}),
        ("export_rotation_assets", {"export_format": "csv"}),
        ("list_account_rotation_configs", {}),
        ("get_account_rotation_config", {"config_id": 2}),
        ("get_account_rotation_config", {"account_id": 308}),
        (
            "create_account_rotation_config",
            {
                "account_id": 308,
                "risk_tolerance": "moderate",
                "is_enabled": True,
                "regime_allocations": {"Overheat": {"510300": 1.0}},
            },
        ),
        (
            "update_account_rotation_config",
            {"config_id": 2, "payload": {"is_enabled": False}, "partial": True},
        ),
        ("delete_account_rotation_config", {"config_id": 2}),
        ("apply_rotation_template_to_account_config", {"config_id": 2, "template_key": "moderate"}),
        (
            "get_alpha_stock_scores",
            {"universe": "csi300", "trade_date": "2026-03-10", "top_n": 10, "user_id": 12},
        ),
        (
            "upload_alpha_scores",
            {
                "universe_id": "csi300",
                "asof_date": "2026-03-08",
                "intended_trade_date": "2026-03-10",
                "scores": [{"code": "000001.SZ", "score": 0.9, "rank": 1}],
                "scope": "user",
            },
        ),
        ("get_pulse_current", {}),
        ("get_pulse_history", {"limit": 5}),
        ("get_regime_navigator", {}),
        ("get_action_recommendation", {}),
        ("explain_pulse_dimensions", {}),
    ],
)
def test_extended_mcp_tools_can_execute(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict
):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    _patch_extended_tool_modules(monkeypatch)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None


def test_decision_workflow_funnel_context_exposes_freshness_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    _patch_extended_tool_modules(monkeypatch)

    result = asyncio.run(
        server.call_tool(
            "decision_workflow_get_funnel_context",
            {"trade_id": "trade-1", "backtest_id": 123},
        )
    )
    rendered = str(result)
    assert "rotation_data_source" in rendered
    assert "rotation_is_stale" in rendered
    assert "rotation_signal_date" in rendered
    assert "step3_status" in rendered
    assert "step3_data_source" in rendered
    assert "step3_signal_date" in rendered


def test_dashboard_alpha_candidates_contract_exposes_async_status(monkeypatch: pytest.MonkeyPatch):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    _patch_extended_tool_modules(monkeypatch)

    result = asyncio.run(
        server.call_tool(
            "get_dashboard_alpha_candidates",
            {"top_n": 10, "portfolio_id": 135},
        )
    )
    rendered = str(result)
    assert "recommendation_ready" in rendered
    assert "must_not_treat_as_recommendation" in rendered
    assert "async_refresh_queued" in rendered
    assert "hardcoded_fallback_used" in rendered


def test_dashboard_alpha_tools_accept_pool_mode(monkeypatch: pytest.MonkeyPatch):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    _patch_extended_tool_modules(monkeypatch)

    result = asyncio.run(
        server.call_tool(
            "get_dashboard_alpha_candidates",
            {"top_n": 10, "portfolio_id": 135, "pool_mode": "market"},
        )
    )
    rendered = str(result)
    assert "market" in rendered

    refresh_result = asyncio.run(
        server.call_tool(
            "trigger_dashboard_alpha_refresh",
            {"top_n": 10, "portfolio_id": 135, "pool_mode": "price_covered"},
        )
    )
    refresh_rendered = str(refresh_result)
    assert "price_covered" in refresh_rendered
