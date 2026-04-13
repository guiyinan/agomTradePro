import json
from types import SimpleNamespace

from django.test import RequestFactory
from django.template.loader import render_to_string

from apps.dashboard.interface import views


def test_alpha_stocks_htmx_passes_request_user_to_query(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def execute(
            self,
            top_n: int,
            ic_days: int,
            max_candidates: int = 5,
            max_pending: int = 10,
            user=None,
        ):
            captured["top_n"] = top_n
            captured["ic_days"] = ic_days
            captured["max_candidates"] = max_candidates
            captured["max_pending"] = max_pending
            captured["user"] = user
            return SimpleNamespace(
                top_stocks=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "score": 0.91,
                        "rank": 1,
                        "workflow_stage": "top_ranked",
                        "workflow_stage_label": "仅在 Alpha Top 排名",
                    }
                ],
                overview={
                    "top_ranked_count": 1,
                    "top10_actionable_count": 0,
                    "top10_pending_count": 0,
                    "top10_rank_only_count": 1,
                    "actionable_conversion_pct": 0.0,
                    "pending_conversion_pct": 0.0,
                },
            )

    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "top_n": 1},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_decision_chain_query", lambda: FakeQuery())
    monkeypatch.setattr(
        views,
        "_get_decision_plane_data",
        lambda max_candidates=5, max_pending=10: SimpleNamespace(
            actionable_candidates=[],
            pending_requests=[],
            alpha_actionable_count=0,
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_alpha_visualization_data",
        lambda top_n, ic_days, user=None: SimpleNamespace(
            stock_scores_meta={
                "status": "degraded",
                "source": "cache",
                "uses_cached_data": True,
                "warning_message": "当前展示的是历史缓存评分。",
            }
        ),
    )

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)

    assert captured["user"] is request.user
    assert captured["top_n"] == 1
    assert captured["ic_days"] == 30
    assert captured["max_candidates"] == 5
    assert captured["max_pending"] == 10
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["meta"]["uses_cached_data"] is True
    assert payload["data"]["overview"]["top_ranked_count"] == 1


def test_alpha_stocks_htmx_renders_compact_scrollable_table(monkeypatch):
    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"top_n": 1},
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr(
        views,
        "_get_alpha_decision_chain_data",
        lambda top_n, ic_days, max_candidates, max_pending, user=None, alpha_visualization_data=None, decision_plane_data=None: SimpleNamespace(
            top_stocks=[
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "score": 0.91,
                    "rank": 1,
                    "source": "cache",
                    "confidence": 0.88,
                    "asof_date": "2026-04-12",
                    "workflow_stage": "actionable",
                    "workflow_stage_label": "可行动候选",
                    "is_actionable": True,
                    "is_pending": False,
                }
            ],
            overview={
                "top_ranked_count": 1,
                "actionable_count": 1,
                "pending_count": 0,
                "top10_actionable_count": 1,
                "top10_pending_count": 0,
                "top10_rank_only_count": 0,
                "actionable_conversion_pct": 100.0,
                "pending_conversion_pct": 0.0,
            },
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_decision_plane_data",
        lambda max_candidates=5, max_pending=10: SimpleNamespace(
            actionable_candidates=[],
            pending_requests=[],
            alpha_actionable_count=0,
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_alpha_visualization_data",
        lambda top_n, ic_days, user=None: SimpleNamespace(stock_scores_meta={}),
    )

    response = views.alpha_stocks_htmx(request)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "alpha-stocks-table-wrap" in content
    assert "min-width: 1120px;" in content
    assert "Alpha 决策链" in content
    assert "可行动候选" in content


def test_build_alpha_factor_panel_uses_user_scoped_scores(monkeypatch):
    captured: dict[str, object] = {}
    user = SimpleNamespace(is_authenticated=True, username="admin")

    def fake_get_alpha_stock_scores(top_n: int = 10, user=None):
        captured["top_n"] = top_n
        captured["user"] = user
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
    assert panel["stock"]["code"] == "000001.SZ"
    assert panel["factor_count"] == 1


def test_dashboard_view_reuses_single_alpha_and_decision_query_execution(monkeypatch):
    captured: dict[str, int] = {
        "alpha_calls": 0,
        "decision_calls": 0,
        "chain_calls": 0,
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
        def execute(self, top_n: int, ic_days: int, user=None):
            captured["alpha_calls"] += 1
            return SimpleNamespace(
                stock_scores=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "score": 0.91,
                        "rank": 1,
                        "source": "cache",
                        "confidence": 0.88,
                        "factors": {"quality": 0.4},
                        "asof_date": "2026-04-12",
                    }
                ],
                stock_scores_meta={},
                provider_status={"providers": {"cache": {"status": "available"}}, "metrics": {}},
                coverage_metrics={"coverage_ratio": 1.0, "total_requests": 1, "cache_hit_rate": 1.0},
                ic_trends=[],
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
                actionable_candidates=[],
                pending_requests=[],
            )

    class FakeChainQuery:
        def execute(
            self,
            top_n: int,
            ic_days: int,
            max_candidates: int = 5,
            max_pending: int = 10,
            user=None,
        ):
            captured["chain_calls"] += 1
            return SimpleNamespace(
                overview={
                    "top_ranked_count": 1,
                    "actionable_count": 1,
                    "pending_count": 0,
                    "top10_actionable_count": 1,
                    "top10_pending_count": 0,
                    "top10_rank_only_count": 0,
                    "actionable_conversion_pct": 100.0,
                    "pending_conversion_pct": 0.0,
                },
                top_stocks=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "score": 0.91,
                        "rank": 1,
                        "source": "cache",
                        "confidence": 0.88,
                        "factors": {"quality": 0.4},
                        "asof_date": "2026-04-12",
                        "workflow_stage": "actionable",
                        "workflow_stage_label": "可行动候选",
                    }
                ],
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
    monkeypatch.setattr(views, "get_decision_plane_query", lambda: FakeDecisionQuery())
    monkeypatch.setattr(views, "get_alpha_decision_chain_query", lambda: FakeChainQuery())
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

    assert captured["alpha_calls"] == 1
    assert captured["decision_calls"] == 1
    assert captured["chain_calls"] == 1
    assert rendered["context"]["alpha_stock_scores"][0]["name"] == "平安银行"
    assert rendered["context"]["alpha_decision_chain_overview"]["top10_actionable_count"] == 1
    assert rendered["context"]["actionable_candidates"][0]["origin_stage_label"] == "当前 Top 10 第 #1"
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
