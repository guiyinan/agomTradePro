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
            list_usage_logs=lambda provider_id=None, status=None: [{"provider_id": provider_id, "status": status}],
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
            positions=lambda: {"positions": []},
            allocation=lambda: {"allocation": []},
        )
        self.asset_analysis = SimpleNamespace(
            multidim_screen=lambda payload: {"screen": True, "payload": payload},
            get_weight_configs=lambda: {"weights": []},
            get_current_weight=lambda: {"weight": {}},
            screen_asset_pool=lambda asset_type, payload=None: {"asset_type": asset_type, "payload": payload},
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


def _patch_extended_tool_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    module_names = [
        "agomsaaf_mcp.tools.ai_provider_tools",
        "agomsaaf_mcp.tools.prompt_tools",
        "agomsaaf_mcp.tools.audit_tools",
        "agomsaaf_mcp.tools.events_tools",
        "agomsaaf_mcp.tools.decision_rhythm_tools",
        "agomsaaf_mcp.tools.beta_gate_tools",
        "agomsaaf_mcp.tools.alpha_trigger_tools",
        "agomsaaf_mcp.tools.dashboard_tools",
        "agomsaaf_mcp.tools.asset_analysis_tools",
        "agomsaaf_mcp.tools.sentiment_tools",
        "agomsaaf_mcp.tools.task_monitor_tools",
        "agomsaaf_mcp.tools.filter_tools",
    ]
    for module_name in module_names:
        mod = importlib.import_module(module_name)
        monkeypatch.setattr(mod, "AgomSAAFClient", _FakeClient)


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
        ("submit_batch_decision_request", {"payload": {"requests": [{"request_type": "rebalance"}]}}),
        ("get_decision_rhythm_summary", {"payload": {"window_days": 7}}),
        ("reset_decision_quota", {"payload": {"user_id": "u1"}}),
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
        ("get_dashboard_regime_quadrant_v1", {}),
        ("get_dashboard_equity_curve_v1", {}),
        ("get_dashboard_signal_status_v1", {}),
        ("get_dashboard_positions", {}),
        ("get_dashboard_allocation", {}),
        ("asset_multidim_screen", {"payload": {"asset_type": "equity"}}),
        ("get_asset_weight_configs", {}),
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
    ],
)
def test_extended_mcp_tools_can_execute(monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict):
    try:
        from agomsaaf_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    _patch_extended_tool_modules(monkeypatch)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
