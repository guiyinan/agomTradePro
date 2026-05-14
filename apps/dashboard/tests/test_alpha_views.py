import json
import logging
from datetime import date
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory

from apps.dashboard.interface import alpha_stock_views, views
from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskStatus


@pytest.mark.django_db
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
    monkeypatch.setattr(
        views,
        "_get_dashboard_alpha_refresh_celery_health",
        lambda: {"available": True, "active_workers": ["worker@local"], "reason": "healthy"},
    )

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)
    cache.delete(
        views._build_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date.today(),
            top_n=12,
            raw_universe_id="csi300",
            resolved_pool=None,
        )
    )

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["task_id"] == "task-123"
    assert captured["universe_id"] == "csi300"
    assert captured["top_n"] == 12


@pytest.mark.django_db
def test_alpha_refresh_htmx_records_pending_task_immediately(monkeypatch):
    class FakeTask:
        id = "task-123"

    class FakeDelayWrapper:
        @staticmethod
        def delay(universe_id: str, intended_trade_date: str, top_n: int):
            return FakeTask()

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 12, "universe_id": "csi300"},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeDelayWrapper)
    monkeypatch.setattr(
        views,
        "_get_dashboard_alpha_refresh_celery_health",
        lambda: {"available": True, "active_workers": ["worker@local"], "reason": "healthy"},
    )

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)
    cache.delete(
        views._build_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date.today(),
            top_n=12,
            raw_universe_id="csi300",
            resolved_pool=None,
        )
    )

    assert response.status_code == 200
    assert payload["success"] is True

    record = get_task_record_repository().get_by_task_id("task-123")
    assert record is not None
    assert record.status == TaskStatus.PENDING
    assert record.task_name == "apps.alpha.application.tasks.qlib_predict_scores"
    assert record.args == ("csi300", date.today().isoformat(), 12)
    assert record.kwargs == {}


@pytest.mark.django_db
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
    monkeypatch.setattr(
        views,
        "_get_dashboard_alpha_refresh_celery_health",
        lambda: {"available": True, "active_workers": ["worker@local"], "reason": "healthy"},
    )

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)
    cache.delete(
        views._build_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date.today(),
            top_n=10,
            raw_universe_id="csi300",
            resolved_pool=SimpleNamespace(scope=SimpleNamespace(scope_hash="scope-9")),
        )
    )

    assert response.status_code == 200
    assert payload["success"] is True
    assert captured["pool_mode"] == "price_covered"
    assert payload["pool_mode"] == "price_covered"
    assert payload["alpha_scope"] == "portfolio"
    assert payload["must_not_use_for_decision"] is True


def test_alpha_refresh_htmx_sync_portfolio_scope_runs_inline_task(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTaskResult:
        def get(self, propagate=False):
            captured["propagate"] = propagate
            return {
                "status": "success",
                "scope_hash": "scope-9",
                "stock_count": 12,
            }

        def failed(self):
            return False

    class FakeTask:
        @staticmethod
        def apply(args=None, kwargs=None):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return FakeTaskResult()

    class FakeResolver:
        def resolve(self, *, user_id: int, portfolio_id=None, trade_date=None, pool_mode=None):
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                scope=SimpleNamespace(
                    universe_id="portfolio-9-scope",
                    scope_hash="scope-9",
                    pool_mode=pool_mode,
                    to_dict=lambda: {
                        "pool_mode": pool_mode,
                        "portfolio_id": portfolio_id,
                        "instrument_codes": ["000001.SZ"],
                        "trade_date": trade_date.isoformat(),
                    },
                ),
            )

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 10, "portfolio_id": 9, "pool_mode": "price_covered", "sync": "1"},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)
    monkeypatch.setattr(views, "PortfolioAlphaPoolResolver", FakeResolver)

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)
    cache.delete(
        views._build_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date.today(),
            top_n=10,
            raw_universe_id="csi300",
            resolved_pool=SimpleNamespace(scope=SimpleNamespace(scope_hash="scope-9")),
        )
    )

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["sync"] is True
    assert payload["scope_hash"] == "scope-9"
    assert captured["args"][0] == "portfolio-9-scope"
    assert captured["kwargs"]["scope_payload"]["portfolio_id"] == 9
    assert captured["kwargs"]["scope_payload"]["pool_mode"] == "price_covered"
    assert captured["propagate"] is False


def test_alpha_refresh_htmx_falls_back_to_sync_when_no_celery_worker(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTaskResult:
        def get(self, propagate=False):
            captured["propagate"] = propagate
            return {
                "status": "success",
                "stock_count": 12,
            }

        def failed(self):
            return False

    class FakeTask:
        @staticmethod
        def apply(args=None, kwargs=None):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return FakeTaskResult()

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 10, "universe_id": "csi300", "alpha_scope": "general"},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeTask)
    monkeypatch.setattr(
        views,
        "_get_dashboard_alpha_refresh_celery_health",
        lambda: {"available": False, "active_workers": [], "reason": "no_active_workers"},
    )

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)
    cache.delete(
        views._build_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=date.today(),
            top_n=10,
            raw_universe_id="csi300",
            resolved_pool=None,
        )
    )

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["sync"] is True
    assert payload["sync_reason"] == "no_active_workers"
    assert "Celery worker" in payload["message"]
    assert captured["args"][0] == "csi300"
    assert captured["propagate"] is False


def test_alpha_refresh_htmx_rejects_duplicate_async_request(monkeypatch):
    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 12, "universe_id": "csi300"},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    lock_key = views._build_alpha_refresh_lock_key(
        alpha_scope="portfolio",
        target_date=date.today(),
        top_n=12,
        raw_universe_id="csi300",
        resolved_pool=None,
    )
    cache.set(lock_key, "task-duplicate", timeout=60)

    class FakeAsyncResult:
        state = "PENDING"

        def ready(self):
            return False

    monkeypatch.setattr(views, "AsyncResult", lambda task_id: FakeAsyncResult())

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)

    cache.delete(lock_key)

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["task_id"] == "task-duplicate"
    assert payload["refresh_status"] == "running"


def test_alpha_refresh_htmx_rejects_duplicate_sync_request(monkeypatch):
    class FakeResolver:
        def resolve(self, *, user_id: int, portfolio_id=None, trade_date=None, pool_mode=None):
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                scope=SimpleNamespace(
                    universe_id="portfolio-9-scope",
                    scope_hash="scope-9",
                    pool_mode=pool_mode,
                    to_dict=lambda: {
                        "pool_mode": pool_mode,
                        "portfolio_id": portfolio_id,
                        "instrument_codes": ["000001.SZ"],
                        "trade_date": trade_date.isoformat(),
                    },
                ),
            )

    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 10, "portfolio_id": 9, "pool_mode": "price_covered", "sync": "1"},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    lock_key = views._build_alpha_refresh_lock_key(
        alpha_scope="portfolio",
        target_date=date.today(),
        top_n=10,
        raw_universe_id="csi300",
        resolved_pool=SimpleNamespace(scope=SimpleNamespace(scope_hash="scope-9")),
    )
    cache.set(lock_key, "__sync__", timeout=60)
    monkeypatch.setattr(views, "PortfolioAlphaPoolResolver", FakeResolver)

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)

    cache.delete(lock_key)

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["sync"] is True
    assert payload["task_state"] == "RUNNING"


def test_alpha_refresh_portfolio_scope_requires_portfolio_id():
    request = RequestFactory().post(
        "/api/dashboard/alpha/refresh/",
        {"top_n": 10, "alpha_scope": "portfolio", "pool_mode": "price_covered"},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    response = views.alpha_refresh_htmx(request)
    payload = json.loads(response.content)

    assert response.status_code == 400
    assert payload["success"] is False
    assert "portfolio_id" in payload["error"]


def test_alpha_stocks_htmx_passes_request_user_to_query(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
            captured["top_n"] = top_n
            captured["user"] = user
            captured["portfolio_id"] = portfolio_id
            captured["pool_mode"] = pool_mode
            captured["alpha_scope"] = alpha_scope
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
                exit_watchlist=[
                    {
                        "account_id": 21,
                        "account_name": "模拟一号",
                        "asset_code": "000001.SZ",
                        "asset_name": "平安银行",
                        "shares": 500,
                        "market_value": 6200,
                        "decision_side_label": "统一推荐 SELL",
                        "exit_action": "SELL",
                        "exit_action_label": "立即退出",
                        "exit_source": "decision_rhythm.recommendation",
                        "exit_reason_text": "Alpha 衰减",
                        "invalidation_summary": "若政策闸门升至 L2 则退出。",
                        "source_signal_ids": ["101"],
                    }
                ],
                exit_watch_summary={
                    "total": 1,
                    "urgent_count": 0,
                    "sell_count": 1,
                    "reduce_count": 0,
                    "hold_count": 0,
                },
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
    assert captured["alpha_scope"] == "portfolio"
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["meta"]["uses_cached_data"] is True
    assert payload["data"]["pool"]["pool_size"] == 3200
    assert payload["data"]["history_run_id"] == 12
    assert payload["data"]["top_candidates"][0]["stage"] == "top_ranked"
    assert payload["data"]["exit_watchlist"][0]["asset_code"] == "000001.SZ"
    assert payload["data"]["exit_watch_summary"]["sell_count"] == 1


def test_alpha_stocks_htmx_json_includes_readiness_contract(monkeypatch):
    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
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
                    }
                ],
                meta={
                    "status": "available",
                    "source": "cache",
                    "recommendation_ready": False,
                    "must_not_use_for_decision": True,
                    "readiness_status": "blocked_broader_scope_cache",
                    "blocked_reason": "当前结果来自 broader-scope cache 映射。",
                    "scope_verification_status": "derived_from_broader_cache",
                    "freshness_status": "fresh",
                    "result_age_days": 0,
                    "derived_from_broader_cache": True,
                    "latest_available_qlib_result": False,
                    "scope_hash": "scope-123",
                    "poll_after_ms": 5000,
                },
                pool={"label": "账户驱动 Alpha 池", "pool_size": 3200},
                actionable_candidates=[],
                exit_watchlist=[],
                exit_watch_summary={},
                pending_requests=[],
                recent_runs=[],
                history_run_id=8,
            )

    request = RequestFactory().get("/api/dashboard/alpha/stocks/", {"format": "json", "top_n": 1})
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)
    contract = payload["data"]["contract"]

    assert response.status_code == 200
    assert contract["recommendation_ready"] is False
    assert contract["must_not_treat_as_recommendation"] is True
    assert contract["readiness_status"] == "blocked_broader_scope_cache"
    assert contract["scope_verification_status"] == "derived_from_broader_cache"
    assert contract["freshness_status"] == "fresh"
    assert contract["blocked_reason"] == "当前结果来自 broader-scope cache 映射。"
    assert contract["verified_scope_hash"] == ""


def test_alpha_stocks_htmx_general_scope_is_research_only(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
            captured["alpha_scope"] = alpha_scope
            captured["portfolio_id"] = portfolio_id
            return SimpleNamespace(
                top_candidates=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "alpha_score": 0.91,
                        "rank": 1,
                        "stage": "top_ranked",
                        "stage_label": "Alpha Top 候选/排名",
                        "source": "cache",
                    }
                ],
                meta={
                    "alpha_scope": "general",
                    "status": "available",
                    "source": "cache",
                    "recommendation_ready": False,
                    "must_not_use_for_decision": True,
                    "readiness_status": "research_only",
                    "blocked_reason": "通用 Alpha 仅用于研究排名。",
                    "scope_verification_status": "general_universe",
                },
                pool={"alpha_scope": "general", "label": "通用 Alpha 研究池", "pool_size": 1},
                actionable_candidates=[],
                pending_requests=[],
                recent_runs=[],
                history_run_id=None,
            )

    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "top_n": 1, "alpha_scope": "general", "portfolio_id": 9},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)
    contract = payload["data"]["contract"]

    assert response.status_code == 200
    assert captured["alpha_scope"] == "general"
    assert captured["portfolio_id"] is None
    assert payload["data"]["alpha_scope"] == "general"
    assert payload["data"]["actionable_candidates"] == []
    assert contract["must_not_use_for_decision"] is True
    assert contract["readiness_status"] == "research_only"


def test_alpha_stocks_htmx_json_contract_exposes_trade_date_adjustment(monkeypatch):
    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
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
                    }
                ],
                meta={
                    "status": "available",
                    "source": "cache",
                    "recommendation_ready": False,
                    "must_not_use_for_decision": True,
                    "readiness_status": "blocked_trade_date_adjusted",
                    "blocked_reason": "请求交易日 2026-04-21 的 Qlib 日线尚未落地。",
                    "scope_verification_status": "verified",
                    "freshness_status": "trade_date_adjusted",
                    "result_age_days": 1,
                    "is_stale": True,
                    "trade_date_adjusted": True,
                    "derived_from_broader_cache": False,
                    "latest_available_qlib_result": True,
                    "scope_hash": "scope-123",
                    "verified_scope_hash": "scope-123",
                    "verified_asof_date": "2026-04-20",
                    "poll_after_ms": 5000,
                },
                pool={"label": "账户驱动 Alpha 池", "pool_size": 3200},
                actionable_candidates=[],
                pending_requests=[],
                recent_runs=[],
                history_run_id=8,
            )

    request = RequestFactory().get("/api/dashboard/alpha/stocks/", {"format": "json", "top_n": 1})
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)
    contract = payload["data"]["contract"]

    assert response.status_code == 200
    assert contract["recommendation_ready"] is False
    assert contract["must_not_use_for_decision"] is True
    assert contract["readiness_status"] == "blocked_trade_date_adjusted"
    assert contract["scope_verification_status"] == "verified"
    assert contract["freshness_status"] == "trade_date_adjusted"
    assert contract["trade_date_adjusted"] is True
    assert contract["verified_scope_hash"] == "scope-123"
    assert contract["verified_asof_date"] == "2026-04-20"


def test_alpha_stocks_htmx_renders_compact_scrollable_table(monkeypatch):
    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"top_n": 1},
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    class FakeQuery:
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
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
    assert "立即推理刷新" in content


def test_alpha_stocks_partial_renders_inline_refresh_button():
    content = render_to_string(
        "dashboard/partials/alpha_stocks_table.html",
        {
            "alpha_meta": {
                "requested_trade_date": "2026-04-30",
            },
            "alpha_pool": {
                "label": "账户驱动 Alpha 池",
                "selection_reason": "按当前账户池输出排序。",
                "pool_size": 12,
                "market": "CN",
                "portfolio_name": "默认组合",
                "pool_mode": "price_covered",
            },
            "alpha_stocks": [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "alpha_score": 0.91,
                    "rank": 1,
                    "stage": "top_ranked",
                    "stage_label": "Alpha Top 候选/排名",
                    "source": "qlib",
                    "confidence": 0.88,
                    "asof_date": "2026-04-30",
                    "recommendation_basis": {},
                    "buy_reasons": [],
                    "no_buy_reasons": [],
                }
            ],
            "alpha_actionable_candidates": [],
            "alpha_pending_requests": [],
            "alpha_recent_runs": [],
            "selected_portfolio_id": 9,
            "selected_alpha_pool_mode": "price_covered",
            "alpha_pool_mode_choices": [],
            "alpha_scope": "portfolio",
            "top_n": 12,
        },
    )

    assert "刷新首页推荐" in content
    assert "triggerAlphaRealtimeRefresh(12, this)" in content


def test_alpha_stocks_partial_renders_exit_watchlist():
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")
    content = render_to_string(
        "dashboard/partials/alpha_stocks_table.html",
        {
            "alpha_meta": {
                "requested_trade_date": "2026-04-30",
            },
            "alpha_pool": {
                "label": "账户驱动 Alpha 池",
                "selection_reason": "按当前账户池输出排序。",
                "pool_size": 12,
                "market": "CN",
                "portfolio_name": "默认组合",
                "pool_mode": "price_covered",
            },
            "alpha_stocks": [],
            "alpha_actionable_candidates": [],
            "alpha_exit_watchlist": [
                {
                    "account_name": "模拟一号",
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "account_id": 21,
                    "is_selected": True,
                    "account_detail_url": "/simulated-trading/my-accounts/21/",
                    "shares": 500,
                    "market_value": 6200,
                    "decision_side_label": "统一推荐 SELL",
                    "exit_action": "SELL",
                    "exit_action_label": "立即退出",
                    "priority_label": "本轮评估",
                    "exit_source": "decision_rhythm.recommendation",
                    "exit_reason_text": "Alpha 衰减且综合分跌入 SELL 区间。",
                    "stop_loss_price": "10.50",
                    "target_price_low": "12.80",
                    "target_price_high": "13.60",
                    "contract_status_label": "已绑定退出契约",
                    "reduce_quantity": None,
                    "invalidation_summary": "若政策闸门升至 L2 且 Alpha 评分继续走弱，则退出。",
                    "source_signal_ids": ["101"],
                    "recommendation_detail_url": "/api/decision/workspace/recommendations/?recommendation_id=urec_101",
                    "transition_plan_detail_url": "/api/decision/workspace/plans/plan_101/",
                    "decision_workspace_url": "/decision/workspace/?security_code=000001.SZ&step=5&account_id=21&action=SELL&source=dashboard-exit",
                    "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                    "user_action_label": "已采纳",
                }
            ],
            "alpha_exit_watch_summary": {
                "total": 1,
                "urgent_count": 0,
                "sell_count": 1,
                "reduce_count": 0,
                "hold_count": 0,
            },
            "alpha_pending_requests": [],
            "alpha_recent_runs": [],
            "selected_portfolio_id": 9,
            "selected_alpha_pool_mode": "price_covered",
            "alpha_pool_mode_choices": [],
            "alpha_scope": "portfolio",
        },
        request=request,
    )

    assert "持仓退出监控" in content
    assert "立即退出" in content
    assert "decision_rhythm.recommendation" in content
    assert "止损 10.50" in content
    assert "来源信号：101" in content
    assert "SELL 1" in content
    assert "本轮评估" in content
    assert "/api/dashboard/alpha/exit-panel/" in content
    assert "hx-trigger=\"load\"" in content
    assert "alpha-list-item alpha-list-item-exit alpha-list-item-exit-sell is-selected" in content
    assert "处理状态 已采纳" in content
    assert "/simulated-trading/my-accounts/21/" in content
    assert "/api/decision/workspace/recommendations/?recommendation_id=urec_101" in content
    assert "/api/decision/workspace/plans/plan_101/" in content
    assert "/decision/workspace/?security_code=000001.SZ&amp;step=5&amp;account_id=21&amp;action=SELL&amp;source=dashboard-exit" in content
    assert "security_code=000001.SZ" in content
    assert "account_id=21" in content
    assert "step=5" in content
    assert "进入决策工作台" in content


def test_alpha_exit_panel_htmx_renders_recommendation_and_plan_detail(monkeypatch):
    request = RequestFactory().get(
        "/api/dashboard/alpha/exit-panel/",
        {
            "asset_code": "000001.SZ",
            "account_id": 21,
            "top_n": 10,
            "alpha_scope": "portfolio",
        },
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(
        views,
        "_get_alpha_stock_scores_payload",
        lambda **kwargs: {
            "exit_watchlist": [
                {
                    "account_id": 21,
                    "account_name": "模拟一号",
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "shares": 500,
                    "market_value": 6200,
                    "exit_action": "SELL",
                    "exit_action_label": "立即退出",
                    "priority_label": "立即处理",
                    "exit_source": "decision_rhythm.transition_plan",
                    "exit_reason_text": "调仓计划建议 EXIT",
                    "stop_loss_price": "10.50",
                    "target_price_low": "12.80",
                    "target_price_high": "13.60",
                    "contract_status_label": "已绑定退出契约",
                    "contract_ready": True,
                    "account_detail_url": "/simulated-trading/my-accounts/21/",
                    "recommendation_detail_url": "/api/decision/workspace/recommendations/?recommendation_id=urec_101",
                    "transition_plan_detail_url": "/api/decision/workspace/plans/plan_101/",
                    "decision_workspace_url": "/decision/workspace/",
                    "recommendation_snapshot": {
                        "recommendation_id": "urec_101",
                        "side": "SELL",
                        "status": "approved",
                        "user_action": "adopted",
                        "confidence": 0.81,
                        "composite_score": -0.22,
                        "alpha_model_score": 0.31,
                        "human_rationale": "Alpha 衰减且综合分跌入 SELL 区间。",
                        "reason_codes": ["ALPHA_DECAY", "POLICY_TIGHTEN"],
                        "stop_loss_price": "10.50",
                    },
                    "transition_plan_snapshot": {
                        "plan_id": "plan_101",
                        "action": "EXIT",
                        "current_qty": 500,
                        "target_qty": 0,
                        "delta_qty": -500,
                        "price_band_low": "12.60",
                        "price_band_high": "13.20",
                        "stop_loss_price": "10.50",
                        "invalidation_description": "政策闸门升至 L2 且综合分继续转弱。",
                        "notes": ["减掉全部持仓", "等待下一轮候选"],
                        "is_ready_for_approval": True,
                    },
                    "signal_contract_snapshot": {
                        "signal_id": 101,
                        "invalidation_description": "若政策闸门升至 L2 则退出。",
                        "conditions": ["政策闸门升至 L2", "Alpha 评分继续走弱"],
                    },
                }
            ]
        },
    )

    response = alpha_stock_views.alpha_exit_panel_htmx(request)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "退出契约详情" in content
    assert "统一推荐建议" in content
    assert "调仓计划" in content
    assert "ALPHA_DECAY" in content
    assert "减掉全部持仓" in content
    assert "政策闸门升至 L2" in content
    assert "先建议，再执行" in content
    assert "查看账户持仓" in content
    assert "推荐明细 API" in content
    assert "调仓计划 API" in content


def test_action_recommendation_partial_blocks_unreliable_pulse(monkeypatch):
    request = RequestFactory().get(
        "/api/dashboard/action-recommendation/",
        HTTP_HX_REQUEST="true",
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    blocked_action = RegimeActionRecommendation(
        asset_weights={},
        risk_budget_pct=0.0,
        position_limit_pct=0.0,
        recommended_sectors=[],
        benefiting_styles=[],
        hedge_recommendation=None,
        reasoning="Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
        regime_contribution="Recovery 导航仪仍可读取，但 Pulse 数据未达到决策级可靠性。",
        pulse_contribution="Pulse 数据不可靠，联合行动建议已阻断。",
        generated_at=date(2026, 4, 21),
        confidence=0.4,
        must_not_use_for_decision=True,
        blocked_reason="Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
        blocked_code="pulse_unreliable",
        pulse_observed_at=date(2026, 4, 20),
        pulse_is_reliable=False,
        stale_indicator_codes=["CN_PMI", "000300.SH"],
    )
    monkeypatch.setattr(
        views,
        "_load_phase1_macro_components",
        lambda as_of_date=None: (None, None, blocked_action),
    )

    response = views.action_recommendation_htmx(request)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "行动建议已阻断" in content
    assert "CN_PMI, 000300.SH" in content


def test_build_alpha_factor_panel_uses_user_scoped_scores(monkeypatch):
    captured: dict[str, object] = {}
    user = SimpleNamespace(is_authenticated=True, username="admin")

    def fake_get_alpha_stock_scores_payload(
        top_n: int = 10,
        user=None,
        portfolio_id=None,
        pool_mode=None,
        alpha_scope=None,
    ):
        captured["top_n"] = top_n
        captured["user"] = user
        captured["portfolio_id"] = portfolio_id
        captured["pool_mode"] = pool_mode
        captured["alpha_scope"] = alpha_scope
        return {
            "items": [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "score": 0.91,
                    "rank": 1,
                    "source": "cache",
                    "confidence": 0.88,
                    "factors": {"quality": 0.4},
                    "asof_date": "2026-03-10",
                    "recommendation_basis": {
                        "factor_basis": ["quality=0.400"],
                        "scope_hash": "scope-123",
                        "freshness_status": "fresh",
                    },
                    "blocked_reason": "仅研究",
                    "must_not_use_for_decision": True,
                }
            ],
            "meta": {
                "alpha_scope": "portfolio",
                "blocked_reason": "仅研究",
                "must_not_use_for_decision": True,
            },
            "pool": {"scope_hash": "scope-123"},
            "actionable_candidates": [],
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": None,
        }

    monkeypatch.setattr(views, "_get_alpha_stock_scores_payload", fake_get_alpha_stock_scores_payload)

    panel = views._build_alpha_factor_panel(
        stock_code="000001.SZ",
        top_n=5,
        user=user,
    )

    assert captured["user"] is user
    assert captured["top_n"] == 10
    assert captured["pool_mode"] is None
    assert captured["alpha_scope"] == "portfolio"
    assert panel["stock"]["code"] == "000001.SZ"
    assert panel["factor_count"] == 1
    assert panel["recommendation_basis"]["scope_hash"] == "scope-123"
    assert panel["factor_basis"] == ["quality=0.400"]


def test_dashboard_macro_components_do_not_refresh_stale_pulse(monkeypatch):
    captured: dict[str, object] = {}

    class FakeNavigatorUseCase:
        def execute(self, as_of_date=None):
            captured["navigator_as_of_date"] = as_of_date
            return SimpleNamespace(regime_name="Recovery", confidence=0.8)

    class FakePulseUseCase:
        def execute(self, *args, **kwargs):
            captured["pulse_kwargs"] = kwargs
            return None

    class FakeActionUseCase:
        def execute(self, as_of_date=None, *, refresh_pulse_if_stale=True):
            captured["action_as_of_date"] = as_of_date
            captured["action_refresh_pulse_if_stale"] = refresh_pulse_if_stale
            return None

    monkeypatch.setattr(
        "apps.dashboard.application.interface_services.load_phase1_macro_components",
        lambda **kwargs: SimpleNamespace(
            navigator=FakeNavigatorUseCase().execute(kwargs.get("as_of_date")),
            pulse=FakePulseUseCase().execute(
                as_of_date=kwargs.get("as_of_date"),
                refresh_if_stale=kwargs.get("refresh_if_stale", False),
            ),
            action=FakeActionUseCase().execute(
                kwargs.get("as_of_date"),
                refresh_pulse_if_stale=kwargs.get("refresh_if_stale", False),
            ),
        ),
    )

    views._load_phase1_macro_components(as_of_date=date(2026, 4, 24))

    assert captured["navigator_as_of_date"] == date(2026, 4, 24)
    assert captured["pulse_kwargs"]["as_of_date"] == date(2026, 4, 24)
    assert captured["pulse_kwargs"]["refresh_if_stale"] is False
    assert captured["action_as_of_date"] == date(2026, 4, 24)
    assert captured["action_refresh_pulse_if_stale"] is False


def test_initial_alpha_factor_panel_skips_provider_lookup(monkeypatch):
    class FailingAlphaService:
        def __init__(self):
            raise AssertionError("initial dashboard render should not query alpha providers")

    monkeypatch.setattr("apps.alpha.application.services.AlphaService", FailingAlphaService)

    panel = views._build_alpha_factor_panel(
        stock_code="000001.SZ",
        scores=[
            {
                "code": "000001.SZ",
                "name": "平安银行",
                "source": "qlib",
                "factors": {},
                "recommendation_basis": {},
            }
        ],
        load_provider_factors=False,
    )

    assert panel["provider"] == "qlib"
    assert panel["factor_count"] == 0
    assert "Qlib" in panel["empty_reason"]


def test_alpha_factor_panel_renders_score_explanation_contract():
    content = render_to_string(
        "dashboard/partials/alpha_factor_panel.html",
        {
            "stock": {
                "code": "000001.SZ",
                "name": "平安银行",
                "score": 0.91,
                "rank": 1,
                "confidence": 0.88,
                "asof_date": "2026-04-21",
                "blocked_reason": "当前结果来自 broader-scope cache 映射。",
            },
            "stock_code": "000001.SZ",
            "provider": "cache",
            "alpha_scope": "portfolio",
            "alpha_meta": {
                "blocked_reason": "当前结果来自 broader-scope cache 映射。",
                "scope_verification_status": "derived_from_broader_cache",
                "freshness_status": "fresh",
                "must_not_use_for_decision": True,
            },
            "alpha_pool": {"scope_hash": "scope-123", "universe_id": "portfolio-366-scope"},
            "recommendation_basis": {
                "provider_source": "qlib",
                "universe_id": "portfolio-366-scope",
                "scope_hash": "scope-123",
                "pool_mode": "price_covered",
                "requested_trade_date": "2026-04-21",
                "effective_asof_date": "2026-04-21",
                "freshness_status": "fresh",
                "scope_verification_status": "derived_from_broader_cache",
                "derived_from_broader_cache": True,
                "must_not_use_for_decision": True,
                "blocked_reason": "当前结果来自 broader-scope cache 映射。",
            },
            "factor_basis": ["momentum=0.910"],
            "buy_reasons": [{"text": "Alpha 排名第 1"}],
            "no_buy_reasons": [{"text": "当前结果来自 broader-scope cache 映射。"}],
            "risk_snapshot": {"policy_gate_level": "P1", "regime_name": "Recovery"},
            "factor_origin": "score_payload",
            "factors": [{"name": "momentum", "value": 0.91, "bar_width": 91, "direction": "positive"}],
            "factor_count": 1,
            "empty_reason": "",
        },
    )

    assert "Alpha 分值解释" in content
    assert "计算链路" in content
    assert "portfolio-366-scope" in content
    assert "数据可靠性" in content
    assert "derived_from_broader_cache" in content
    assert "仅研究，不可用于决策" in content
    assert "momentum=0.910" in content


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
        def execute(self, top_n: int, user=None, portfolio_id=None, pool_mode=None, alpha_scope=None):
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
    monkeypatch.setattr(views, "_get_dashboard_portfolio_options", lambda user_id: [])
    monkeypatch.setattr(views, "_get_dashboard_accounts", lambda user: [])
    monkeypatch.setattr(views, "_get_dashboard_valuation_repair_config_summary", lambda: None)
    monkeypatch.setattr(views, "_build_regime_status_context", lambda navigator, pulse, action: {})
    monkeypatch.setattr(views, "_build_pulse_card_context", lambda pulse: {})
    monkeypatch.setattr(views, "_build_action_recommendation_context", lambda action: {})
    monkeypatch.setattr(views, "_build_attention_items_context", lambda data, navigator, pulse: {})
    monkeypatch.setattr(views, "_build_browser_notification_context", lambda navigator, pulse: {})
    monkeypatch.setattr(views, "get_alpha_visualization_query", lambda: FakeAlphaQuery())
    monkeypatch.setattr(views, "get_alpha_homepage_query", lambda: FakeHomepageQuery())
    monkeypatch.setattr(views, "get_decision_plane_query", lambda: FakeDecisionQuery())
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


def test_dashboard_view_logs_timing_breakdown(monkeypatch, caplog):
    request = RequestFactory().get(
        "/dashboard/",
        {
            "portfolio_id": "21",
            "alpha_scope": "portfolio",
            "pool_mode": "price_covered",
            "exit_asset_code": "000001.SZ",
            "exit_account_id": "9",
        },
    )
    request.user = SimpleNamespace(id=7, username="admin", is_authenticated=True)

    dashboard_data = SimpleNamespace(
        username="admin",
        positions=[{"asset_code": "000001.SZ"}],
        invested_value=100000.0,
    )
    decision_plane_data = SimpleNamespace(
        actionable_candidates=[{"asset_code": "000001.SZ"}],
        pending_requests=[{"asset_code": "000002.SZ"}],
    )
    alpha_payload = {
        "items": [{"code": "000001.SZ"}],
        "meta": {},
        "pool": {"portfolio_id": 21},
        "actionable_candidates": [{"asset_code": "000001.SZ"}],
        "pending_requests": [{"asset_code": "000002.SZ"}],
        "exit_watchlist": [],
        "exit_watch_summary": {},
        "recent_runs": [],
        "history_run_id": None,
    }

    monkeypatch.setattr(views, "_build_dashboard_data", lambda user_id: dashboard_data)
    monkeypatch.setattr(views, "_ensure_dashboard_positions", lambda data, user_id: data)
    monkeypatch.setattr(views, "_load_phase1_macro_components", lambda: (None, None, None))
    monkeypatch.setattr(views, "_get_dashboard_portfolio_options", lambda user_id: [{"id": 21}])
    monkeypatch.setattr(
        views,
        "_get_decision_plane_data",
        lambda max_candidates, max_pending: decision_plane_data,
    )
    monkeypatch.setattr(views, "_get_alpha_metrics_data", lambda ic_days=30: {"provider_status": {}})
    monkeypatch.setattr(
        views,
        "_get_alpha_stock_scores_payload",
        lambda top_n, user, portfolio_id, pool_mode, alpha_scope: alpha_payload,
    )
    monkeypatch.setattr(views, "_get_dashboard_accounts", lambda user: [{"id": 9}, {"id": 10}])
    monkeypatch.setattr(
        views,
        "_get_dashboard_valuation_repair_config_summary",
        lambda: {"enabled": True},
    )
    monkeypatch.setattr(
        views,
        "_build_dashboard_page_context",
        lambda **kwargs: {"ok": True, "alpha_stock_scores": kwargs["alpha_payload"]["items"]},
    )
    monkeypatch.setattr(views, "render", lambda request, template_name, context: HttpResponse("ok"))

    with caplog.at_level(logging.INFO):
        response = views.dashboard_view(request)

    assert response.status_code == 200
    records = [record for record in caplog.records if record.message == "Dashboard page request completed"]
    assert records

    record = records[-1]
    assert record.user_id == 7
    assert record.portfolio_id == 21
    assert record.alpha_scope == "portfolio"
    assert record.pool_mode == "price_covered"
    assert record.exit_asset_code == "000001.SZ"
    assert record.exit_account_id == 9
    assert record.position_count == 1
    assert record.investment_account_count == 2
    assert record.alpha_candidate_count == 1
    assert record.alpha_actionable_count == 1
    assert record.alpha_pending_count == 1
    assert record.workflow_actionable_count == 1
    assert record.workflow_pending_count == 1
    assert record.duration_ms >= 0
    assert "build_dashboard_data" in record.step_durations_ms
    assert "alpha_payload" in record.step_durations_ms
    assert "render" in record.step_durations_ms


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
            "alpha_exit_watchlist": [],
            "alpha_exit_watch_summary": {},
            "alpha_exit_entry_watchlist": [],
            "alpha_exit_entry_watch_summary": {},
            "alpha_exit_entry_hidden_count": 0,
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
                    "decision_workspace_url": "/decision/workspace/?source=dashboard-workflow&security_code=000001.SZ",
                    "decision_workspace_primary_url": "/decision/workspace/?source=dashboard-workflow&security_code=000001.SZ&step=4",
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
            "alpha_exit_watchlist": [],
            "alpha_exit_watch_summary": {},
            "alpha_exit_entry_watchlist": [],
            "alpha_exit_entry_watch_summary": {},
            "alpha_exit_entry_hidden_count": 0,
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
                    "decision_workspace_url": "/decision/workspace/?source=dashboard-alpha&security_code=000001.SZ",
                    "decision_workspace_primary_url": "/decision/workspace/?source=dashboard-alpha&security_code=000001.SZ&step=4",
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
    assert "不会重排成 1-5" in content
    assert "查看完整排名" in content
    assert "000001.SZ" in content
    assert "平安银行" in content
    assert 'href="/equity/detail/000001.SZ/"' in content
    assert "Alpha 排名第 1" in content
    assert "暂无通过触发器和风控约束的可行动候选" in content


def test_alpha_ranking_page_renders_full_ranking_entry(monkeypatch):
    request = RequestFactory().get(
        "/dashboard/alpha/ranking/",
        {"alpha_scope": "portfolio", "portfolio_id": 9, "pool_mode": "price_covered", "top_n": 200},
    )
    request.user = SimpleNamespace(id=7, is_authenticated=True, username="admin")

    monkeypatch.setattr(
        views,
        "_get_dashboard_portfolio_options",
        lambda user_id: [{"id": 9, "name": "主组合"}],
    )
    monkeypatch.setattr(
        views,
        "_get_alpha_stock_scores_payload",
        lambda top_n, user, portfolio_id, pool_mode, alpha_scope: {
            "items": [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "rank": 8,
                    "alpha_score": 0.91,
                    "confidence": 0.88,
                    "stage_label": "Alpha Top 候选",
                    "source": "cache",
                    "buy_reason_summary": "来自更大缓存裁剪后的保序结果",
                    "invalidation_summary": "跌出 Top 10",
                    "asof_date": "2026-04-16",
                }
            ],
            "meta": {
                "source": "cache",
                "effective_asof_date": "2026-04-16",
            },
            "pool": {
                "label": "账户驱动 Alpha 池",
                "pool_size": 320,
                "portfolio_id": 9,
                "pool_mode": "price_covered",
            },
            "actionable_candidates": [],
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": 12,
        },
    )

    response = alpha_stock_views.alpha_ranking_page(request)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Alpha 完整排名" in content
    assert "不会为了展示而重排成 1-3" in content
    assert "当前已加载 1 条，股票池规模约 320" in content
    assert "000001.SZ" in content
    assert "#8" in content
    assert "打开 JSON" in content


def test_main_workflow_panel_renders_exit_chain_entry_links():
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
            "actionable_candidates": [],
            "valuation_repair_config_summary": None,
            "pending_requests": [],
            "pending_count": 0,
            "alpha_decision_chain_overview": {
                "top_ranked_count": 0,
                "top10_actionable_count": 0,
                "top10_pending_count": 0,
                "top10_rank_only_count": 0,
                "actionable_outside_top10_count": 0,
                "pending_outside_top10_count": 0,
            },
            "alpha_exit_watchlist": [
                {
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "account_id": 21,
                    "account_name": "模拟一号",
                    "exit_action": "SELL",
                    "exit_action_label": "立即退出",
                    "exit_source": "decision_rhythm.recommendation",
                    "decision_side_label": "统一推荐 SELL",
                    "priority_label": "立即处理",
                    "stop_loss_price": "10.50",
                    "contract_status_label": "已绑定退出契约",
                    "exit_reason_text": "Alpha 衰减且综合分跌入 SELL 区间。",
                    "decision_workspace_url": "/decision/workspace/",
                    "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                }
            ],
            "alpha_exit_watch_summary": {
                "total": 1,
                "urgent_count": 1,
                "sell_count": 1,
                "reduce_count": 0,
                "hold_count": 0,
            },
            "selected_portfolio_id": 9,
            "selected_alpha_scope": "portfolio",
        },
        request=request,
    )

    assert "退出待办" in content
    assert "查看右侧详情" in content
    assert "不会离开当前页" in content
    assert "立即退出" in content
    assert "/dashboard/?alpha_scope=portfolio&amp;portfolio_id=9&amp;exit_asset_code=000001.SZ&amp;exit_account_id=21#alpha-exit-detail" in content


def test_dashboard_exit_entry_panel_context_hides_processed_items():
    context = views._build_dashboard_exit_entry_panel_context(
        [
            {
                "asset_code": "000001.SZ",
                "exit_action": "SELL",
                "priority_rank": 0,
                "recommendation_snapshot": {"user_action": "PENDING"},
            },
            {
                "asset_code": "000002.SZ",
                "exit_action": "SELL",
                "priority_rank": 0,
                "recommendation_snapshot": {"user_action": "ADOPTED"},
            },
            {
                "asset_code": "000003.SZ",
                "exit_action": "REDUCE",
                "priority_rank": 1,
                "recommendation_snapshot": {"user_action": "IGNORED"},
            },
        ]
    )

    assert [item["asset_code"] for item in context["items"]] == ["000001.SZ"]
    assert context["summary"] == {
        "total": 1,
        "urgent_count": 1,
        "sell_count": 1,
        "reduce_count": 0,
        "hold_count": 0,
    }
    assert context["hidden_processed_count"] == 2


def test_build_dashboard_exit_detail_url_uses_shared_anchor():
    url = views._build_dashboard_exit_detail_url(
        asset_code="000001.SZ",
        account_id=21,
        alpha_scope="portfolio",
        portfolio_id=9,
    )

    assert url == "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail"


def test_build_decision_workspace_url_uses_canonical_query_order():
    url = views._build_decision_workspace_url(
        security_code="000001.SZ",
        source="dashboard-workflow",
        step=4,
        account_id=21,
        action="watch",
    )

    assert (
        url
        == "/decision/workspace/?source=dashboard-workflow&security_code=000001.SZ&step=4&account_id=21&action=WATCH"
    )


def test_annotate_decision_workspace_navigation_accepts_model_instances():
    request_model = DecisionRequestModel(
        request_id="req-000001",
        asset_code="000001.SZ",
        asset_class="equity",
        direction="BUY",
        execution_status="PENDING",
    )

    annotated = views._annotate_decision_workspace_navigation(
        [request_model],
        source="dashboard-pending",
        security_code_key="asset_code",
        view_step=5,
        primary_step=5,
    )

    assert annotated[0]["request_id"] == "req-000001"
    assert annotated[0]["asset_code"] == "000001.SZ"
    assert (
        annotated[0]["decision_workspace_primary_url"]
        == "/decision/workspace/?source=dashboard-pending&security_code=000001.SZ&step=5"
    )


def test_dashboard_view_accepts_pending_request_models(monkeypatch):
    request = RequestFactory().get("/dashboard/")
    request.user = SimpleNamespace(is_authenticated=True, username="admin", id=1)

    dashboard_data = SimpleNamespace(
        display_name="Admin",
        current_regime="Recovery",
        regime_date=None,
        regime_confidence=0.82,
        growth_momentum_z=0.4,
        inflation_momentum_z=-0.1,
        regime_distribution={},
        regime_data_health=True,
        regime_warnings=[],
        pmi_value=50.1,
        cpi_value=1.2,
        current_policy_level="P1",
        total_assets=0,
        initial_capital=0,
        total_return=0,
        total_return_pct=0,
        cash_balance=0,
        invested_value=0,
        invested_ratio=0,
        positions=[],
        position_count=0,
        regime_match_score=0,
        regime_recommendations=[],
        active_signals=[],
        signal_stats={},
        asset_allocation=[],
        ai_insights=[],
        allocation_advice=[],
        allocation_data={},
        performance_data=[],
    )

    pending_request = DecisionRequestModel(
        request_id="req-500",
        asset_code="000001.SZ",
        asset_class="equity",
        direction="BUY",
        execution_status="PENDING",
    )
    pending_request.asset_name = "平安银行"

    rendered: dict[str, object] = {}

    monkeypatch.setattr(views, "_build_dashboard_data", lambda user_id: dashboard_data)
    monkeypatch.setattr(views, "_ensure_dashboard_positions", lambda data, user_id: data)
    monkeypatch.setattr(views, "_load_phase1_macro_components", lambda: (None, None, None))
    monkeypatch.setattr(views, "_get_dashboard_portfolio_options", lambda user_id: [])
    monkeypatch.setattr(views, "_get_dashboard_accounts", lambda user: [])
    monkeypatch.setattr(views, "_get_dashboard_valuation_repair_config_summary", lambda: None)
    monkeypatch.setattr(views, "_build_regime_status_context", lambda navigator, pulse, action: {})
    monkeypatch.setattr(views, "_build_pulse_card_context", lambda pulse: {})
    monkeypatch.setattr(views, "_build_action_recommendation_context", lambda action: {})
    monkeypatch.setattr(views, "_build_attention_items_context", lambda data, navigator, pulse: {})
    monkeypatch.setattr(views, "_build_browser_notification_context", lambda navigator, pulse: {})
    monkeypatch.setattr(
        views,
        "_get_alpha_metrics_data",
        lambda ic_days=30: SimpleNamespace(
            provider_status={},
            coverage_metrics={},
            ic_trends=[],
        ),
    )
    monkeypatch.setattr(
        views,
        "_get_alpha_stock_scores_payload",
        lambda **kwargs: {
            "items": [],
            "meta": {},
            "actionable_candidates": [],
            "pending_requests": [],
            "exit_watchlist": [],
            "exit_watch_summary": {},
            "pool": {},
            "recent_runs": [],
            "history_run_id": None,
        },
    )
    monkeypatch.setattr(
        views,
        "_get_decision_plane_data",
        lambda max_candidates=5, max_pending=10: SimpleNamespace(
            beta_gate_visible_classes="equity",
            alpha_watch_count=0,
            alpha_candidate_count=0,
            alpha_actionable_count=0,
            quota_total=10,
            quota_used=0,
            quota_remaining=10,
            quota_usage_percent=0.0,
            actionable_candidates=[],
            pending_requests=[pending_request],
        ),
    )
    monkeypatch.setattr(
        views,
        "render",
        lambda request, template_name, context: rendered.setdefault("context", context) or context,
    )

    views.dashboard_view(request)

    assert rendered["context"]["pending_count"] == 1
    assert rendered["context"]["pending_requests"][0]["request_id"] == "req-500"
    assert rendered["context"]["pending_requests"][0]["asset_name"] == "平安银行"
    assert (
        rendered["context"]["pending_requests"][0]["decision_workspace_primary_url"]
        == "/decision/workspace/?source=dashboard-pending&security_code=000001.SZ&step=5"
    )


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
            "alpha_exit_watchlist": [],
            "alpha_exit_watch_summary": {},
            "alpha_exit_entry_watchlist": [],
            "alpha_exit_entry_watch_summary": {},
            "alpha_exit_entry_hidden_count": 0,
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


def test_main_workflow_panel_exit_entry_uses_right_panel_detail_language():
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
            "alpha_exit_watchlist": [],
            "alpha_exit_watch_summary": {},
            "alpha_exit_entry_watchlist": [
                {
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "account_id": 21,
                    "account_name": "模拟一号",
                    "exit_action": "SELL",
                    "exit_action_label": "立即退出",
                    "priority_label": "立即处理",
                    "exit_source": "decision_rhythm.recommendation",
                    "decision_side_label": "统一推荐 SELL",
                    "contract_status_label": "契约完整",
                    "exit_reason_text": "Alpha 衰减且综合分跌入 SELL 区间。",
                    "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                    "decision_workspace_url": "/decision/workspace/?source=dashboard-exit&security_code=000001.SZ&step=5&account_id=21&action=SELL",
                }
            ],
            "alpha_exit_entry_watch_summary": {
                "total": 1,
                "urgent_count": 1,
                "sell_count": 1,
                "reduce_count": 0,
                "hold_count": 0,
            },
            "alpha_exit_entry_hidden_count": 0,
            "alpha_stock_scores": [],
            "alpha_actionable_candidates": [],
            "actionable_candidates": [],
            "valuation_repair_config_summary": None,
            "pending_requests": [],
            "pending_count": 0,
            "alpha_decision_chain_overview": {
                "top_ranked_count": 0,
                "top10_actionable_count": 0,
                "top10_pending_count": 0,
                "top10_rank_only_count": 0,
                "actionable_outside_top10_count": 0,
                "pending_outside_top10_count": 0,
            },
        },
        request=request,
    )

    assert "退出待办" in content
    assert "先在右侧核对退出契约与调仓计划" in content
    assert "查看右侧详情" in content
    assert "不会离开当前页" in content
    assert "打开退出详情" not in content


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
            "current_exit_watchlist": [
                {
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "account_id": 21,
                    "account_name": "模拟一号",
                    "is_selected": True,
                    "exit_action": "SELL",
                    "exit_action_label": "立即退出",
                    "priority_label": "立即处理",
                    "exit_source": "decision_rhythm.recommendation",
                    "decision_side_label": "统一推荐 SELL",
                    "exit_reason_text": "Alpha 衰减且综合分跌入 SELL 区间。",
                    "recommendation_detail_url": "/api/decision/workspace/recommendations/?recommendation_id=urec_101",
                    "transition_plan_detail_url": "/api/decision/workspace/plans/plan_101/",
                    "decision_workspace_url": "/decision/workspace/",
                    "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                }
            ],
            "current_exit_watch_summary": {
                "total": 1,
                "urgent_count": 1,
                "sell_count": 1,
                "reduce_count": 0,
                "hold_count": 0,
            },
            "current_exit_portfolio_id": 9,
            "current_exit_alpha_scope": "portfolio",
            "current_exit_dashboard_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9#alpha-exit-detail",
        },
        request=request,
    )

    assert "查看详情" in content
    assert "打开 JSON" in content
    assert "复制 JSON" in content
    assert "loadAlphaHistoryDetail" in content
    assert "/api/dashboard/alpha/history/5/" in content
    assert "当前持仓退出链路" in content
    assert "在 Dashboard 右侧查看" in content
    assert "/dashboard/?alpha_scope=portfolio&amp;portfolio_id=9&amp;exit_asset_code=000001.SZ&amp;exit_account_id=21#alpha-exit-detail" in content


def test_decision_workspace_template_renders_exit_chain_sidebar():
    request = RequestFactory().get("/decision/workspace/?account_id=21&security_code=000001.SZ&step=5")
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    content = render_to_string(
        "decision/workspace.html",
        {
            "workspace_exit_watch_summary": {
                "total": 1,
                "urgent_count": 1,
                "sell_count": 1,
                "reduce_count": 0,
                "hold_count": 0,
            },
            "workspace_selected_exit_item": {
                "asset_code": "000001.SZ",
                "asset_name": "平安银行",
                "account_id": 21,
                "account_name": "模拟一号",
                "exit_action": "SELL",
                "exit_action_label": "立即退出",
                "decision_side_label": "统一推荐 SELL",
                "contract_status_label": "已绑定退出契约",
                "exit_reason_text": "Alpha 衰减且综合分跌入 SELL 区间。",
                "decision_workspace_url": "/decision/workspace/?security_code=000001.SZ&step=5&account_id=21&action=SELL&source=dashboard-exit",
                "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                "transition_plan_detail_url": "/api/decision/workspace/plans/plan_101/",
            },
            "workspace_exit_watchlist": [
                {
                    "asset_code": "000001.SZ",
                    "asset_name": "平安银行",
                    "account_id": 21,
                    "account_name": "模拟一号",
                    "exit_action": "SELL",
                    "priority_label": "立即处理",
                    "exit_source": "decision_rhythm.recommendation",
                    "invalidation_summary": "若政策闸门升至 L2 则退出。",
                    "decision_workspace_url": "/decision/workspace/?security_code=000001.SZ&step=5&account_id=21&action=SELL&source=dashboard-exit",
                    "dashboard_detail_url": "/dashboard/?alpha_scope=portfolio&portfolio_id=9&exit_asset_code=000001.SZ&exit_account_id=21#alpha-exit-detail",
                    "is_selected": True,
                }
            ],
        },
        request=request,
    )

    assert "退出链路" in content
    assert "统一退出建议、调仓计划与信号契约" in content
    assert "在 Workspace 中定位" in content
    assert "回到 Dashboard 右侧详情" in content
    assert "/decision/workspace/?security_code=000001.SZ&amp;step=5&amp;account_id=21&amp;action=SELL&amp;source=dashboard-exit" in content
    assert "/dashboard/?alpha_scope=portfolio&amp;portfolio_id=9&amp;exit_asset_code=000001.SZ&amp;exit_account_id=21#alpha-exit-detail" in content


def test_dashboard_api_root_exposes_docs_and_mcp_entries():
    from apps.dashboard.interface.api_urls import dashboard_api_root

    request = RequestFactory().get("/api/dashboard/")
    response = dashboard_api_root(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["endpoints"]["ai_capability"] == "/api/ai-capability/"
    assert payload["endpoints"]["documentation_portal"] == "/docs/"
    assert payload["endpoints"]["mcp_tools_settings"] == "/settings/mcp-tools/"


def test_global_api_root_exposes_ai_capability_and_mcp_entries():
    from core.urls import api_root_view

    request = RequestFactory().get("/api/")
    response = api_root_view(request)
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["endpoints"]["ai-capability"] == "/api/ai-capability/"
    assert payload["endpoints"]["documentation-portal"] == "/docs/"
    assert payload["endpoints"]["mcp-tools-settings"] == "/settings/mcp-tools/"
