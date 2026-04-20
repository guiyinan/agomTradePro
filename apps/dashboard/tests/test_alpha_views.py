import json
from types import SimpleNamespace

from django.test import RequestFactory
from django.template.loader import render_to_string

from apps.dashboard.interface import views


def test_alpha_refresh_htmx_triggers_qlib_task(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTask:
        id = "task-123"

    class FakeDelayWrapper:
        @staticmethod
        def delay(universe_id: str, intended_trade_date: str, top_n: int):
            captured["universe_id"] = universe_id
            captured["intended_trade_date"] = intended_trade_date
            captured["top_n"] = top_n
            return FakeTask()

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 12, "universe_id": "csi300"},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeDelayWrapper)

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["task_id"] == "task-123"
    assert captured["universe_id"] == "csi300"
    assert captured["top_n"] == 12


def test_alpha_refresh_htmx_passes_pool_mode_to_resolver(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTask:
        id = "task-456"

    class FakeApplyAsyncWrapper:
        @staticmethod
        def delay(universe_id: str, intended_trade_date: str, top_n: int, scope_payload=None):
            captured["universe_id"] = universe_id
            captured["scope_payload"] = scope_payload
            return FakeTask()

    class FakeResolver:
        def resolve(self, *, user_id: int, portfolio_id=None, trade_date=None, pool_mode=None):
            captured["pool_mode"] = pool_mode
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                scope=SimpleNamespace(
                    universe_id="portfolio-9-scope",
                    scope_hash="scope-9",
                    pool_mode=pool_mode,
                    to_dict=lambda: {"pool_mode": pool_mode, "instrument_codes": ["000001.SZ"]},
                ),
            )

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 10, "portfolio_id": 9, "pool_mode": "price_covered"},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeApplyAsyncWrapper)
    monkeypatch.setattr(views, "PortfolioAlphaPoolResolver", FakeResolver)

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["success"] is True
    assert captured["pool_mode"] == "price_covered"
    assert payload["pool_mode"] == "price_covered"


def test_alpha_stocks_htmx_passes_request_user_to_query(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None):
            captured["top_n"] = top_n
            captured["user"] = user
            captured["portfolio_id"] = portfolio_id
            captured["pool_mode"] = pool_mode
            return SimpleNamespace(
                top_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "alpha_score": 0.91,
                        "rank": 1,
                        "stage": "top_ranked",
                        "stage_label": "仅排名",
                        "source": "cache",
                        "buy_reasons": [],
                        "no_buy_reasons": [],
                    }
                ],
                meta={
                    "status": "degraded",
                    "source": "cache",
                    "uses_cached_data": True,
                    "warning_message": "当前展示的是历史缓存评分。",
                },
                pool={
                    "label": "账户驱动 Alpha 池",
                    "pool_size": 3200,
                    "pool_mode": "market",
                    "selection_reason": "按当前激活组合所属市场生成候选池。",
                },
                actionable_candidates=[],
                pending_requests=[],
                recent_runs=[],
                history_run_id=12,
            )

    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "top_n": 1, "portfolio_id": 9, "pool_mode": "market"},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)

    assert captured["user"] is request.user
    assert captured["top_n"] == 1
    assert captured["portfolio_id"] == 9
    assert captured["pool_mode"] == "market"
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["meta"]["uses_cached_data"] is True
    assert payload["data"]["pool"]["pool_size"] == 3200
    assert payload["data"]["history_run_id"] == 12
    assert payload["data"]["top_candidates"][0]["stage"] == "top_ranked"


def test_alpha_stocks_htmx_renders_compact_scrollable_table(monkeypatch):
    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"top_n": 1},
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None):
            return SimpleNamespace(
                top_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "alpha_score": 0.91,
                        "rank": 1,
                        "source": "cache",
                        "confidence": 0.88,
                        "asof_date": "2026-04-12",
                        "stage": "actionable",
                        "stage_label": "可行动候选",
                        "gate_status": "passed",
                        "suggested_position_pct": 12.0,
                        "recommendation_basis": {
                            "provider_source": "qlib",
                            "scope_hash": "scope-123",
                            "scope_label": "账户驱动 Alpha 池",
                            "asof_date": "2026-04-12",
                            "effective_asof_date": "2026-04-12",
                            "factor_basis": ["momentum=0.910", "quality=0.800"],
                        },
                        "buy_reasons": [{"text": "Alpha 排名第 1，当前评分领先。"}],
                        "no_buy_reasons": [{"text": "暂无阻断项。"}],
                        "invalidation_summary": "若评分跌出前 10 且风控闸门转阻断则失效。",
                    }
                ],
                meta={
                    "uses_cached_data": True,
                    "requested_trade_date": "2026-04-16",
                    "effective_asof_date": "2026-04-14",
                    "cache_reason": "Qlib 实时结果未就绪，回退到最近可用缓存。",
                },
                pool={
                    "label": "账户驱动 Alpha 池",
                    "pool_size": 3200,
                    "pool_mode": "price_covered",
                    "market": "CN",
                    "portfolio_name": "默认组合",
                    "selection_reason": "按当前激活组合所属市场生成候选池。",
                },
                actionable_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "suggested_position_pct": 12.0,
                        "suggested_quantity": 100,
                        "gate_status": "passed",
                    }
                ],
                pending_requests=[
                    {
                        "request_id": "req-123",
                        "code": "600519.SH",
                        "name": "贵州茅台",
                        "stage_label": "待执行队列",
                        "suggested_quantity": 100,
                        "suggested_notional": 50000,
                        "reason_summary": "mcp smoke",
                        "risk_snapshot": {"execution_status": "PENDING"},
                        "no_buy_reasons": [{"text": "当前已在待执行队列中。"}],
                    }
                ],
                recent_runs=[{"id": 8, "trade_date": "2026-04-16", "source": "cache"}],
                history_run_id=8,
            )

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Alpha Top 候选/排名" in content
    assert "可行动候选" in content
    assert "待执行队列" in content
    assert "最近推荐记录" in content
    assert "调用缓存原因" in content
    assert "账户驱动 Alpha 池" in content
    assert "推荐依据" in content
    assert "momentum=0.910" in content
    assert "丢弃待执行" in content
    assert "discardAlphaPendingRequest" in content
    assert "req\\u002D123" in content
    assert "mcp smoke" in content
    assert "股票池模式" in content


def test_alpha_stocks_empty_state_renders_refresh_cta():
    content = render_to_string(
        "dashboard/partials/alpha_stocks_table.html",
        {
            "alpha_meta": {
                "no_recommendation_reason": "当前账户池暂无真实 Alpha 推理结果。",
                "requested_trade_date": "2026-04-19",
            },
            "alpha_pool": {},
            "alpha_stocks": [],
            "alpha_actionable_candidates": [],
            "alpha_pending_requests": [],
            "alpha_recent_runs": [],
            "selected_portfolio_id": None,
            "selected_alpha_pool_mode": "strict_valuation",
            "alpha_pool_mode_choices": [],
        },
    )

    assert "暂无可信 Alpha 候选数据" in content
    assert "触发实时推理" in content
    assert "triggerAlphaRealtimeRefresh(10)" in content


def test_build_alpha_factor_panel_uses_user_scoped_scores(monkeypatch):
    captured: dict[str, object] = {}
    user = SimpleNamespace(is_authenticated=True, username="admin")

    def fake_get_alpha_stock_scores(top_n: int = 10, user=None, pool_mode=None):
        captured["top_n"] = top_n
        captured["user"] = user
        captured["pool_mode"] = pool_mode
        return [
            {
                "code": "000001.SZ",
                "name": "平安银行",
                "score": 0.91,
                "rank": 1,
                "source": "cache",
                "confidence": 0.88,
                "factors": {"quality": 0.4},
                "asof_date": "2026-03-10",
            }
        ]

    monkeypatch.setattr(views, "_get_alpha_stock_scores", fake_get_alpha_stock_scores)

    panel = views._build_alpha_factor_panel(
        stock_code="000001.SZ",
        top_n=5,
        user=user,
    )

    assert captured["user"] is user
    assert captured["top_n"] == 10
    assert captured["pool_mode"] is None
    assert panel["stock"]["code"] == "000001.SZ"
    assert panel["factor_count"] == 1


def test_alpha_history_list_api_returns_filtered_runs(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def list_history(
            self,
            user_id: int,
            portfolio_id=None,
            stock_code=None,
            stage=None,
            source=None,
            trade_date=None,
        ):
            captured["user_id"] = user_id
            captured["portfolio_id"] = portfolio_id
            captured["stock_code"] = stock_code
            captured["stage"] = stage
            captured["source"] = source
            captured["trade_date"] = trade_date
            return [{"id": 3, "trade_date": "2026-04-16", "source": "cache"}]

    request = RequestFactory().get(
        "/api/dashboard/alpha/history/",
        {
            "portfolio_id": 21,
            "stock_code": "000001.SZ",
            "stage": "actionable",
            "source": "cache",
            "trade_date": "2026-04-16",
        },
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_history_list_api(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"][0]["id"] == 3
    assert captured["user_id"] == 7
    assert captured["portfolio_id"] == 21
    assert captured["stock_code"] == "000001.SZ"
    assert captured["stage"] == "actionable"
    assert captured["source"] == "cache"
    assert str(captured["trade_date"]) == "2026-04-16"


def test_alpha_history_detail_api_returns_snapshot_detail(monkeypatch):
    class FakeQuery:
        def get_history_detail(self, user_id: int, run_id: int):
            assert user_id == 7
            assert run_id == 5
            return {
                "id": 5,
                "trade_date": "2026-04-16",
                "snapshots": [
                    {
                        "stock_code": "000001.SZ",
                        "stage": "actionable",
                        "buy_reasons": [{"text": "Alpha 排名第 1"}],
                    }
                ],
            }

    request = RequestFactory().get("/api/dashboard/alpha/history/5/")
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_history_detail_api(request, run_id=5)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["snapshots"][0]["stock_code"] == "000001.SZ"


def test_dashboard_view_uses_light_alpha_metrics_and_keeps_workflow_candidates(monkeypatch):
    captured: dict[str, int] = {
        "metrics_calls": 0,
        "homepage_calls": 0,
        "decision_calls": 0,
    }
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(id=7, username="admin", is_authenticated=True)

    dashboard_data = SimpleNamespace(
        display_name="Admin",
        username="admin",
        current_regime="Recovery",
        regime_date="2026-04-12",
        regime_confidence=0.82,
        growth_momentum_z=0.2,
        inflation_momentum_z=-0.1,
        regime_distribution={},
        regime_data_health=True,
        regime_warnings=[],
        pmi_value=50.2,
        cpi_value=1.3,
        current_policy_level="P1",
        total_assets=100000.0,
        initial_capital=80000.0,
        total_return=20000.0,
        total_return_pct=25.0,
        cash_balance=20000.0,
        invested_value=80000.0,
        invested_ratio=80.0,
        positions=[],
        position_count=0,
        regime_match_score=0.9,
        regime_recommendations=[],
        active_signals=[],
        signal_stats={},
        asset_allocation={},
        ai_insights=[],
        allocation_advice=None,
        allocation_data={},
        performance_data=[],
    )

    class FakeAlphaQuery:
        def execute_metrics(self, ic_days: int):
            captured["metrics_calls"] += 1
            return SimpleNamespace(
                stock_scores=[],
                stock_scores_meta={},
                provider_status={"providers": {"cache": {"status": "available"}}, "metrics": {}},
                coverage_metrics={
                    "coverage_ratio": 1.0,
                    "total_requests": 1,
                    "cache_hit_rate": 1.0,
                },
                ic_trends=[],
                ic_trends_meta={},
            )

    class FakeHomepageQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None):
            captured["homepage_calls"] += 1
            return SimpleNamespace(
                top_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "alpha_score": 0.91,
                        "rank": 1,
                        "source": "cache",
                        "confidence": 0.88,
                        "factors": {"quality": 0.4},
                        "asof_date": "2026-04-12",
                        "stage": "actionable",
                        "stage_label": "可行动候选",
                    }
                ],
                meta={},
                pool={"portfolio_id": 21, "portfolio_name": "默认组合"},
                actionable_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "suggested_position_pct": 12.0,
                        "suggested_quantity": 100,
                        "buy_reason_summary": "Alpha 排名第 1",
                    }
                ],
                pending_requests=[],
                recent_runs=[],
                history_run_id=5,
            )

    class FakeDecisionQuery:
        def execute(self, max_candidates: int, max_pending: int):
            captured["decision_calls"] += 1
            return SimpleNamespace(
                beta_gate_visible_classes="equity",
                alpha_watch_count=1,
                alpha_candidate_count=2,
                alpha_actionable_count=3,
                quota_total=10,
                quota_used=2,
                quota_remaining=8,
                quota_usage_percent=20.0,
                actionable_candidates=[
                    {
                        "candidate_id": "cand-1",
                        "asset_code": "000001.SZ",
                        "asset_name": "平安银行",
                        "direction": "LONG",
                        "confidence": 0.88,
                        "asset_class": "equity",
                        "valuation_repair": None,
                        "is_in_top10": True,
                        "current_top_rank": 1,
                        "origin_stage_label": "当前 Top 10 第 #1",
                        "chain_stage": "actionable",
                        "chain_stage_label": "可行动候选",
                    }
                ],
                pending_requests=[],
            )

    rendered: dict[str, object] = {}

    monkeypatch.setattr(views, "_build_dashboard_data", lambda user_id: dashboard_data)
    monkeypatch.setattr(views, "_ensure_dashboard_positions", lambda data, user_id: data)
    monkeypatch.setattr(views, "_load_phase1_macro_components", lambda: (None, None, None))
    monkeypatch.setattr(views, "_get_dashboard_accounts", lambda user: [])
    monkeypatch.setattr(views, "_build_regime_status_context", lambda navigator, pulse, action: {})
    monkeypatch.setattr(views, "_build_pulse_card_context", lambda pulse: {})
    monkeypatch.setattr(views, "_build_action_recommendation_context", lambda action: {})
    monkeypatch.setattr(views, "_build_attention_items_context", lambda data, navigator, pulse: {})
    monkeypatch.setattr(views, "_build_browser_notification_context", lambda navigator, pulse: {})
    monkeypatch.setattr(views, "get_alpha_visualization_query", lambda: FakeAlphaQuery())
    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeHomepageQuery())
    monkeypatch.setattr(views, "get_decision_plane_query", lambda: FakeDecisionQuery())
    monkeypatch.setattr(
        "apps.equity.application.config.get_valuation_repair_config_summary",
        lambda use_cache=False: None,
        raising=False,
    )
    monkeypatch.setattr(
        views,
        "render",
        lambda request, template_name, context: rendered.setdefault("context", context) or context,
    )

    views.dashboard_view(request)

    assert captured["metrics_calls"] == 1
    assert captured["homepage_calls"] == 1
    assert captured["decision_calls"] == 1
    assert rendered["context"]["alpha_stock_scores"][0]["name"] == "平安银行"
    assert rendered["context"]["alpha_decision_chain_overview"]["top10_actionable_count"] == 1
    assert (
        rendered["context"]["actionable_candidates"][0]["origin_stage_label"] == "当前 Top 10 第 #1"
    )
    assert rendered["context"]["alpha_actionable_candidates"][0]["code"] == "000001.SZ"
    assert rendered["context"]["quota_remaining"] == 8


def test_main_workflow_panel_renders_candidate_asset_name():
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    content = render_to_string(
        "dashboard/main_workflow_panel.html",
        {
            "current_regime": "Recovery",
            "policy_level": "P1",
            "action_weights": None,
            "action_sectors": None,
            "alpha_actionable_count": 1,
            "actionable_candidates": [
                {
                    "candidate_id": "cand-1",
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "direction": "LONG",
                    "confidence": 0.91,
                    "asset_class": "equity",
                    "valuation_repair": None,
                    "is_in_top10": True,
                    "current_top_rank": 1,
                    "origin_stage_label": "当前 Top 10 第 #1",
                    "chain_stage_label": "可行动候选",
                }
            ],
            "valuation_repair_config_summary": None,
            "pending_requests": [],
            "pending_count": 0,
            "alpha_decision_chain_overview": {
                "top_ranked_count": 10,
                "top10_actionable_count": 1,
                "top10_pending_count": 0,
                "top10_rank_only_count": 9,
                "actionable_outside_top10_count": 0,
                "pending_outside_top10_count": 0,
            },
        },
        request=request,
    )

    assert "000001.SZ" in content
    assert "平安银行" in content
    assert "当前 Top 10 第 #1" in content


def test_main_workflow_panel_renders_alpha_recommendations_without_actionable_candidates():
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    content = render_to_string(
        "dashboard/main_workflow_panel.html",
        {
            "current_regime": "Recovery",
            "policy_level": "P1",
            "action_weights": None,
            "action_sectors": None,
            "alpha_actionable_count": 0,
            "alpha_stock_scores": [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "rank": 1,
                    "alpha_score": 0.91,
                    "confidence": 0.88,
                    "stage_label": "Alpha Top 候选",
                    "source": "cache",
                    "buy_reason_summary": "Alpha 排名第 1",
                    "invalidation_summary": "跌出 Top 10",
                    "asof_date": "2026-04-16",
                }
            ],
            "actionable_candidates": [],
            "valuation_repair_config_summary": None,
            "pending_requests": [],
            "pending_count": 0,
            "alpha_decision_chain_overview": {
                "top_ranked_count": 1,
                "top10_actionable_count": 0,
                "top10_pending_count": 0,
                "top10_rank_only_count": 1,
                "actionable_outside_top10_count": 0,
                "pending_outside_top10_count": 0,
            },
        },
        request=request,
    )

    assert "Alpha 推荐资产" in content
    assert "000001.SZ" in content
    assert "平安银行" in content
    assert "Alpha 排名第 1" in content
    assert "暂无通过触发器和风控约束的可行动候选" in content


def test_main_workflow_panel_does_not_use_pending_assets_as_alpha_recommendations():
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    content = render_to_string(
        "dashboard/main_workflow_panel.html",
        {
            "current_regime": "Recovery",
            "policy_level": "P1",
            "action_weights": None,
            "action_sectors": None,
            "alpha_actionable_count": 0,
            "alpha_stock_scores": [],
            "alpha_actionable_candidates": [],
            "alpha_pending_requests": [
                {
                    "request_id": "req-510300",
                    "code": "510300",
                    "name": "沪深300ETF",
                    "stage_label": "待执行队列",
                    "suggested_quantity": 100,
                    "suggested_notional": 50000,
                    "reason_summary": "mcp smoke",
                    "no_buy_reasons": [{"text": "当前已在待执行队列中。"}],
                }
            ],
            "actionable_candidates": [],
            "valuation_repair_config_summary": None,
            "pending_requests": [],
            "pending_count": 0,
            "alpha_decision_chain_overview": {
                "top_ranked_count": 0,
                "top10_actionable_count": 0,
                "top10_pending_count": 1,
                "top10_rank_only_count": 0,
                "actionable_outside_top10_count": 0,
                "pending_outside_top10_count": 1,
            },
        },
        request=request,
    )

    assert "Alpha 推荐资产" in content
    assert "暂无可信 Alpha 推荐资产" in content
    assert "系统不会用硬编码股票池" in content
    assert "510300" not in content
    assert "沪深300ETF" not in content
    assert "mcp smoke" not in content


def test_alpha_history_page_template_renders_detail_controls():
    request = RequestFactory().get("/dashboard/alpha/history/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    content = render_to_string(
        "dashboard/alpha_history.html",
        {
            "history_runs": [
                {
                    "id": 5,
                    "trade_date": "2026-04-16",
                    "scope_label": "账户驱动 Alpha 池",
                    "source": "cache",
                    "provider_source": "qlib",
                    "uses_cached_data": True,
                    "effective_asof_date": "2026-04-15",
                    "cache_reason": "Qlib 实时结果未就绪。",
                }
            ],
        },
        request=request,
    )

    assert "查看详情" in content
    assert "打开 JSON" in content
    assert "复制 JSON" in content
    assert "loadAlphaHistoryDetail" in content
    assert "/api/dashboard/alpha/history/5/" in content
