from datetime import date
from types import SimpleNamespace

import pytest

from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel, AlphaTriggerModel
from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery
from apps.dashboard.application.queries import (
    AlphaDecisionChainQuery,
    AlphaVisualizationQuery,
    DecisionPlaneQuery,
)
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.equity.infrastructure.models import StockInfoModel
from apps.rotation.infrastructure.models import AssetClassModel


def test_alpha_visualization_query_passes_user_to_alpha_service(monkeypatch):
    captured: dict[str, object] = {}
    query = AlphaVisualizationQuery()
    user = SimpleNamespace(id=182, is_authenticated=True, username="admin")

    class FakeAlphaService:
        def get_stock_scores(
            self,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user=None,
            provider_filter=None,
        ):
            captured["user"] = user
            captured["provider_filter"] = provider_filter
            return SimpleNamespace(
                success=True,
                source="cache",
                status="degraded",
                staleness_days=20,
                metadata={
                    "uses_cached_data": True,
                    "is_degraded": True,
                    "reliability_notice": {
                        "title": "Alpha 当前使用历史缓存",
                        "message": "当前展示的是历史缓存评分。",
                        "level": "warning",
                        "code": "historical_cache_result",
                    },
                },
                scores=[
                    SimpleNamespace(
                        code="000001.SZ",
                        score=0.91234,
                        rank=1,
                        source="cache",
                        confidence=0.88,
                        factors={"quality": 0.4},
                        asof_date=date(2026, 3, 10),
                    )
                ],
            )

    monkeypatch.setattr("apps.alpha.application.services.AlphaService", FakeAlphaService)
    monkeypatch.setattr(
        query,
        "_resolve_security_names",
        lambda codes: {"000001.SZ": "平安银行"},
    )
    monkeypatch.setattr(query, "_get_provider_status", lambda: {})
    monkeypatch.setattr(query, "_get_coverage_metrics", lambda: {})
    monkeypatch.setattr(query, "_get_ic_trends", lambda days: [])

    data = query.execute(top_n=1, ic_days=5, user=user)

    assert captured["user"] is user
    assert captured["provider_filter"] == "qlib"
    assert data.stock_scores == [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "score": 0.9123,
            "rank": 1,
            "source": "cache",
            "confidence": 0.88,
            "factors": {"quality": 0.4},
            "asof_date": "2026-03-10",
        }
    ]
    assert data.stock_scores_meta["source"] == "cache"
    assert data.stock_scores_meta["uses_cached_data"] is True


def test_alpha_visualization_query_uses_dashboard_fast_path_providers(monkeypatch):
    calls: list[str] = []
    query = AlphaVisualizationQuery()

    class FakeAlphaService:
        def get_stock_scores(
            self,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user=None,
            provider_filter=None,
        ):
            calls.append(provider_filter)
            if provider_filter == "qlib":
                return SimpleNamespace(
                    success=False,
                    source="qlib",
                    status="degraded",
                    error_message="缓存缺失，已触发异步推理任务",
                    metadata={"async_task_triggered": True},
                    scores=[],
                )
            if provider_filter == "cache":
                return SimpleNamespace(
                    success=True,
                    source="cache",
                    status="available",
                    staleness_days=0,
                    metadata={
                        "cache_date": "2026-03-10",
                        "asof_date": "2026-03-10",
                        "created_at": "2026-03-10T09:30:00+08:00",
                    },
                    scores=[
                        SimpleNamespace(
                            code="000001.SZ",
                            score=0.91234,
                            rank=1,
                            source="cache",
                            confidence=0.88,
                            factors={"quality": 0.4},
                            asof_date=date(2026, 3, 10),
                        )
                    ],
                )
            raise AssertionError("dashboard fast path should stop after first successful provider")

    monkeypatch.setattr("apps.alpha.application.services.AlphaService", FakeAlphaService)
    monkeypatch.setattr(
        query,
        "_resolve_security_names",
        lambda codes: {"000001.SZ": "平安银行"},
    )
    monkeypatch.setattr(query, "_get_provider_status", lambda: {})
    monkeypatch.setattr(query, "_get_coverage_metrics", lambda: {})
    monkeypatch.setattr(query, "_get_ic_trends", lambda days: [])

    data = query.execute(top_n=1, ic_days=5, user=None)

    assert calls == ["qlib", "cache"]
    assert data.stock_scores[0]["source"] == "cache"
    assert data.stock_scores_meta["uses_cached_data"] is True
    assert data.stock_scores_meta["fallback_from"] == "qlib"
    assert data.stock_scores_meta["refresh_triggered"] is True
    assert "异步推理任务" in data.stock_scores_meta["fallback_reason"]


def test_alpha_homepage_query_uses_cache_first_for_initial_page():
    calls: list[str] = []
    query = object.__new__(AlphaHomepageQuery)

    class FakeAlphaService:
        def get_stock_scores(
            self,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user=None,
            provider_filter=None,
            pool_scope=None,
        ):
            calls.append(provider_filter)
            return SimpleNamespace(
                success=True,
                scores=[SimpleNamespace(code="000001.SZ")],
                source=provider_filter,
                status="available",
                metadata={},
            )

    query.alpha_service = FakeAlphaService()
    result = query._fetch_alpha_result(
        user=SimpleNamespace(id=7, is_authenticated=True),
        scope=SimpleNamespace(universe_id="portfolio-cn"),
        trade_date=date(2026, 4, 18),
        top_n=10,
    )

    assert result.success is True
    assert calls == ["cache"]


def test_alpha_homepage_query_does_not_use_hardcoded_market_fallback_when_scope_cache_missing():
    calls: list[tuple[str, str, bool]] = []
    query = object.__new__(AlphaHomepageQuery)

    class FakeAlphaService:
        def get_stock_scores(
            self,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user=None,
            provider_filter=None,
            pool_scope=None,
        ):
            calls.append((provider_filter, universe_id, pool_scope is not None))
            if provider_filter == "cache" and pool_scope is not None:
                return SimpleNamespace(
                    success=False,
                    scores=[],
                    source="cache",
                    status="unavailable",
                    metadata={},
                    error_message="scope cache missing",
                )
            raise AssertionError("homepage must not query hardcoded market fallback providers")

    query.alpha_service = FakeAlphaService()
    query._trigger_async_inference_if_needed = lambda **kwargs: {
        "refresh_triggered": True,
        "refresh_status": "queued",
        "async_task_id": "task-scope-1",
        "poll_after_ms": 5000,
        "message": "账户池暂无可信 Alpha cache，已自动触发后台 Qlib 推理。",
    }
    scope = SimpleNamespace(
        universe_id="portfolio-7-deadbeef",
        market="CN",
        display_label="默认组合 · CN A-share 可交易池",
        scope_hash="deadbeef",
    )

    result = query._fetch_alpha_result(
        user=SimpleNamespace(id=7, is_authenticated=True),
        scope=scope,
        trade_date=date(2026, 4, 18),
        top_n=10,
    )

    assert result.success is False
    assert calls == [("cache", "portfolio-7-deadbeef", True)]
    assert result.status == "unavailable"
    assert result.metadata["hardcoded_fallback_used"] is False
    assert result.metadata["refresh_triggered"] is True
    assert result.metadata["refresh_status"] == "queued"
    assert result.metadata["async_task_id"] == "task-scope-1"
    assert result.metadata["no_recommendation_reason"]
    assert "硬编码" in result.metadata["no_recommendation_reason"]
    meta = query._build_meta(alpha_result=result, scope=scope)
    assert meta["hardcoded_fallback_used"] is False
    assert meta["refresh_triggered"] is True
    assert meta["refresh_status"] == "queued"
    assert meta["async_task_id"] == "task-scope-1"
    assert meta["no_recommendation_reason"] == result.metadata["no_recommendation_reason"]


def test_alpha_homepage_auto_trigger_uses_scope_payload(monkeypatch):
    captured: dict[str, object] = {}
    query = object.__new__(AlphaHomepageQuery)

    class FakeCache:
        @staticmethod
        def add(key, value, timeout=None):
            captured["cache_key"] = key
            captured["cache_timeout"] = timeout
            return True

    class FakeTask:
        id = "task-auto-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(universe_id, intended_trade_date, top_n, scope_payload=None):
            captured["universe_id"] = universe_id
            captured["intended_trade_date"] = intended_trade_date
            captured["top_n"] = top_n
            captured["scope_payload"] = scope_payload
            return FakeTask()

    scope = SimpleNamespace(
        universe_id="portfolio-7-deadbeef",
        scope_hash="deadbeef",
        to_dict=lambda: {
            "universe_id": "portfolio-7-deadbeef",
            "scope_hash": "deadbeef",
            "instrument_codes": ["000001.SZ"],
        },
    )
    monkeypatch.setattr("django.core.cache.cache", FakeCache)
    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", FakeDelayWrapper)

    status = query._trigger_async_inference_if_needed(
        user=SimpleNamespace(id=7, is_authenticated=True),
        scope=scope,
        trade_date=date(2026, 4, 18),
        top_n=10,
    )

    assert status["refresh_triggered"] is True
    assert status["refresh_status"] == "queued"
    assert status["async_task_id"] == "task-auto-1"
    assert captured["universe_id"] == "portfolio-7-deadbeef"
    assert captured["intended_trade_date"] == "2026-04-18"
    assert captured["top_n"] == 10
    assert captured["scope_payload"]["scope_hash"] == "deadbeef"
    assert "csi300" not in str(captured)


def test_alpha_homepage_query_triggers_scoped_refresh_when_using_broader_cache():
    query = object.__new__(AlphaHomepageQuery)

    class FakeAlphaService:
        def get_stock_scores(
            self,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user=None,
            provider_filter=None,
            pool_scope=None,
        ):
            return SimpleNamespace(
                success=True,
                scores=[SimpleNamespace(code="000001.SZ")],
                source="cache",
                status="available",
                metadata={
                    "derived_from_broader_cache": True,
                    "provider_source": "qlib",
                },
            )

    query.alpha_service = FakeAlphaService()
    query._trigger_async_inference_if_needed = lambda **kwargs: {
        "refresh_triggered": True,
        "refresh_status": "queued",
        "async_task_id": "task-scope-2",
        "poll_after_ms": 5000,
        "message": "已触发 scoped Qlib 推理。",
    }

    result = query._fetch_alpha_result(
        user=SimpleNamespace(id=7, is_authenticated=True),
        scope=SimpleNamespace(universe_id="portfolio-7-deadbeef"),
        trade_date=date(2026, 4, 18),
        top_n=10,
    )

    assert result.success is True
    assert result.metadata["refresh_triggered"] is True
    assert result.metadata["refresh_status"] == "queued"
    assert result.metadata["async_task_id"] == "task-scope-2"


def test_alpha_homepage_meta_marks_broader_cache_as_not_ready():
    query = object.__new__(AlphaHomepageQuery)
    scope = SimpleNamespace(
        scope_hash="deadbeef",
        display_label="默认组合 · CN A-share 可交易池",
        pool_mode="market",
        pool_size=3200,
        to_dict=lambda: {"scope_hash": "deadbeef"},
    )
    result = SimpleNamespace(
        success=True,
        scores=[SimpleNamespace(code="000001.SZ")],
        source="cache",
        status="available",
        staleness_days=0,
        metadata={
            "provider_source": "qlib",
            "requested_trade_date": "2026-04-21",
            "effective_asof_date": "2026-04-21",
            "derived_from_broader_cache": True,
            "latest_available_qlib_result": False,
        },
    )

    meta = query._build_meta(alpha_result=result, scope=scope)

    assert meta["recommendation_ready"] is False
    assert meta["must_not_use_for_decision"] is True
    assert meta["scope_verification_status"] == "derived_from_broader_cache"
    assert meta["readiness_status"] == "blocked_broader_scope_cache"
    assert "broader-scope cache" in meta["blocked_reason"]


def test_alpha_homepage_meta_marks_general_scope_as_research_only():
    query = object.__new__(AlphaHomepageQuery)
    scope = SimpleNamespace(
        scope_hash="general-scope",
        display_label="通用 Alpha 研究池",
        pool_mode="general",
        pool_size=1,
        universe_id="csi300",
        to_dict=lambda: {"scope_hash": "general-scope", "universe_id": "csi300"},
    )
    alpha_result = SimpleNamespace(
        success=True,
        source="cache",
        status="available",
        staleness_days=0,
        scores=[SimpleNamespace(code="000001.SZ")],
        metadata={
            "alpha_scope": "general",
            "research_only": True,
            "requested_trade_date": "2026-04-21",
            "effective_asof_date": "2026-04-21",
            "latest_available_qlib_result": True,
        },
    )

    meta = query._build_meta(alpha_result=alpha_result, scope=scope)

    assert meta["alpha_scope"] == "general"
    assert meta["recommendation_ready"] is False
    assert meta["must_not_use_for_decision"] is True
    assert meta["scope_verification_status"] == "general_universe"
    assert meta["readiness_status"] == "research_only"


def test_alpha_homepage_meta_marks_trade_date_adjusted_cache_as_traceable_not_ready():
    query = object.__new__(AlphaHomepageQuery)
    scope = SimpleNamespace(
        scope_hash="deadbeef",
        display_label="默认组合 · CN A-share 可交易池",
        pool_mode="market",
        pool_size=3200,
        to_dict=lambda: {"scope_hash": "deadbeef"},
    )
    result = SimpleNamespace(
        success=True,
        scores=[SimpleNamespace(code="000001.SZ")],
        source="cache",
        status="available",
        staleness_days=None,
        metadata={
            "provider_source": "qlib",
            "requested_trade_date": "2026-04-21",
            "effective_asof_date": "2026-04-20",
            "trade_date_adjusted": True,
            "latest_available_qlib_result": True,
            "reliability_notice": {
                "message": "请求交易日 2026-04-21 的 Qlib 日线尚未落地。",
            },
        },
    )

    meta = query._build_meta(alpha_result=result, scope=scope)

    assert meta["recommendation_ready"] is False
    assert meta["must_not_use_for_decision"] is True
    assert meta["scope_verification_status"] == "verified"
    assert meta["freshness_status"] == "trade_date_adjusted"
    assert meta["readiness_status"] == "blocked_trade_date_adjusted"
    assert meta["result_age_days"] == 1
    assert meta["is_stale"] is True
    assert meta["trade_date_adjusted"] is True
    assert meta["verified_scope_hash"] == "deadbeef"
    assert meta["verified_asof_date"] == "2026-04-20"


def test_alpha_homepage_candidate_is_not_actionable_when_readiness_is_blocked():
    query = object.__new__(AlphaHomepageQuery)

    class FakeDecisionEngine:
        @staticmethod
        def evaluate(**kwargs):
            return "allow", ["ALLOW"], "允许观察", {}

    class FakeSizingEngine:
        @staticmethod
        def calculate(**kwargs):
            return 10000.0, 100.0, None, None, "sizing ok"

    class FakeRiskGate:
        @staticmethod
        def check(**kwargs):
            return True, [], [], {"liquidity": "ok"}

    query.decision_engine = FakeDecisionEngine()
    query.sizing_engine = FakeSizingEngine()
    query.risk_gate = FakeRiskGate()

    item = query._build_candidate_item(
        score=SimpleNamespace(
            code="000001.SZ",
            score=0.91,
            rank=1,
            source="qlib",
            confidence=0.82,
            factors={"momentum": 0.9},
            asof_date=date(2026, 4, 21),
        ),
        stock_context={"name": "平安银行", "close": 10.0, "volume": 1000000},
        actionable_candidate=None,
        pending_request=None,
        sizing_context=SimpleNamespace(
            multiplier_result=SimpleNamespace(multiplier=1.0),
            regime_name="Recovery",
            regime_confidence=0.8,
            pulse_composite=0.2,
            pulse_warning=False,
        ),
        portfolio_snapshot=SimpleNamespace(total_value=100000.0),
        position_map={},
        policy_state={"gate_level": "L1"},
        meta={
            "provider_source": "qlib",
            "scope_hash": "scope-1",
            "scope_label": "账户驱动 Alpha 池",
            "requested_trade_date": "2026-04-21",
            "effective_asof_date": "2026-04-21",
            "recommendation_ready": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "当前结果来自 broader-scope cache 映射。",
            "scope_verification_status": "derived_from_broader_cache",
            "freshness_status": "fresh",
            "result_age_days": 0,
            "verified_scope_hash": "",
            "verified_asof_date": None,
            "latest_available_qlib_result": False,
            "derived_from_broader_cache": True,
        },
    )

    assert item["stage"] == "top_ranked"
    assert item["recommendation_ready"] is False
    assert item["must_not_use_for_decision"] is True
    assert item["blocked_reason"] == "当前结果来自 broader-scope cache 映射。"
    assert item["recommendation_basis"]["scope_verification_status"] == "derived_from_broader_cache"
    assert item["no_buy_reasons"][0]["code"] == "ALPHA_RELIABILITY_BLOCK"


def test_alpha_homepage_factor_basis_is_explicit_and_data_driven():
    query = object.__new__(AlphaHomepageQuery)

    assert query._build_factor_basis({"momentum": 0.91234, "quality": "0.7", "note": "qlib"}) == [
        "momentum=0.912",
        "quality=0.700",
        "note=qlib",
    ]


def test_alpha_homepage_pending_request_includes_cancel_identity():
    query = object.__new__(AlphaHomepageQuery)

    item = query._serialize_pending_request(
        request_model=SimpleNamespace(
            request_id="req-123",
            asset_code="600519",
            execution_status="PENDING",
            reason="mcp smoke",
            position_pct=0,
            notional=10000,
            quantity=100,
            id=9,
        ),
        stock_context={"name": "贵州茅台"},
    )

    assert item["request_id"] == "req-123"
    assert item["reason_summary"] == "mcp smoke"
    assert item["risk_snapshot"]["execution_status"] == "PENDING"
    assert item["name"] == "贵州茅台"


def test_alpha_metrics_query_uses_lightweight_provider_registry(monkeypatch):
    query = AlphaVisualizationQuery()

    class FakeAlphaService:
        def get_provider_registry_status(self):
            return {
                "qlib": {
                    "priority": 1,
                    "status": "registered",
                    "max_staleness_days": 3,
                }
            }

        def get_provider_status(self):
            raise AssertionError("homepage metrics must not run provider health checks")

    monkeypatch.setattr("apps.alpha.application.services.AlphaService", FakeAlphaService)
    monkeypatch.setattr(query, "_get_ic_trends", lambda days: [])
    monkeypatch.setattr(query, "_get_coverage_metrics", lambda: {})

    data = query.execute_metrics(ic_days=5)

    assert data.provider_status["data_source"] == "registry"
    assert data.provider_status["providers"]["qlib"]["status"] == "registered"


def test_dashboard_ai_insights_default_to_local_rules(monkeypatch):
    use_case = object.__new__(GetDashboardDataUseCase)
    captured: dict[str, object] = {}

    def fake_fallback(current_regime, snapshot, match_analysis, active_signals, policy_level=None):
        captured["fallback"] = True
        captured["policy_level"] = policy_level
        return ["本地规则建议"]

    monkeypatch.setattr(use_case, "_enhanced_fallback_insights", fake_fallback)

    result = use_case._generate_ai_insights(
        current_regime="Recovery",
        snapshot=SimpleNamespace(
            total_value=100000,
            total_return_pct=1.2,
            positions=[],
            get_invested_ratio=lambda: 0.5,
        ),
        match_analysis=SimpleNamespace(total_match_score=80, hostile_assets=[]),
        active_signals=[],
        policy_level="P0",
    )

    assert result == ["本地规则建议"]
    assert captured == {"fallback": True, "policy_level": "P0"}


@pytest.mark.django_db
def test_resolve_security_names_matches_stock_info_without_exchange_suffix():
    StockInfoModel.objects.create(
        stock_code="000001",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
    )

    query = AlphaVisualizationQuery()

    assert query._resolve_security_names(["000001.SZ"]) == {
        "000001.SZ": "平安银行",
    }


@pytest.mark.django_db
def test_resolve_security_names_matches_rotation_assets_for_etf_codes():
    AssetClassModel.objects.create(
        code="510300",
        name="沪深300ETF",
        category="equity",
        description="跟踪沪深300指数",
        currency="CNY",
        is_active=True,
    )

    query = AlphaVisualizationQuery()

    assert query._resolve_security_names(["510300.SH"]) == {
        "510300.SH": "沪深300ETF",
    }


def test_decision_plane_query_attach_asset_names_supports_exchange_suffix(monkeypatch):
    query = DecisionPlaneQuery()
    items = [
        SimpleNamespace(asset_code="000001.SZ", asset_name=""),
        SimpleNamespace(asset_code="510300.SH"),
        SimpleNamespace(asset_code="159915.SZ", asset_name="创业板ETF"),
    ]

    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda codes: {
            "000001": "平安银行",
            "510300.SH": "沪深300ETF",
            "159915.SZ": "不应覆盖已有名称",
        },
    )

    enriched = query._attach_asset_names(items)

    assert enriched[0].asset_name == "平安银行"
    assert enriched[1].asset_name == "沪深300ETF"
    assert enriched[2].asset_name == "创业板ETF"


@pytest.mark.django_db
def test_decision_plane_query_skips_manual_override_candidates():
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
    )
    StockInfoModel.objects.create(
        stock_code="600519.SH",
        name="贵州茅台",
        sector="食品饮料",
        market="SH",
        list_date=date(2001, 8, 27),
    )

    AlphaTriggerModel.objects.create(
        trigger_id="trigger-auto-1",
        trigger_type=AlphaTriggerModel.MOMENTUM_SIGNAL,
        asset_code="000001.SZ",
        asset_class="equity",
        confidence=0.82,
        status=AlphaTriggerModel.TRIGGERED,
    )
    AlphaTriggerModel.objects.create(
        trigger_id="trigger-manual-1",
        trigger_type=AlphaTriggerModel.MANUAL_OVERRIDE,
        asset_code="600519.SH",
        asset_class="equity",
        confidence=0.95,
        status=AlphaTriggerModel.TRIGGERED,
    )
    AlphaCandidateModel.objects.create(
        candidate_id="cand-auto-1",
        trigger_id="trigger-auto-1",
        asset_code="000001.SZ",
        asset_class="equity",
        confidence=0.82,
        status=AlphaCandidateModel.ACTIONABLE,
    )
    AlphaCandidateModel.objects.create(
        candidate_id="cand-manual-1",
        trigger_id="trigger-manual-1",
        asset_code="600519.SH",
        asset_class="equity",
        confidence=0.95,
        status=AlphaCandidateModel.ACTIONABLE,
    )

    query = DecisionPlaneQuery()

    items = query._get_actionable_candidates(max_count=None)

    assert [item.asset_code for item in items] == ["000001.SZ"]
    assert items[0].asset_name == "平安银行"


def test_alpha_decision_chain_query_builds_unified_chain_relationship():
    query = AlphaDecisionChainQuery()

    alpha_visualization_data = SimpleNamespace(
        stock_scores=[
            {
                "code": "000001.SZ",
                "name": "平安银行",
                "score": 0.91,
                "rank": 1,
                "source": "cache",
                "confidence": 0.88,
                "asof_date": "2026-04-12",
            },
            {
                "code": "600519.SH",
                "name": "贵州茅台",
                "score": 0.89,
                "rank": 2,
                "source": "cache",
                "confidence": 0.84,
                "asof_date": "2026-04-12",
            },
            {
                "code": "300750.SZ",
                "name": "宁德时代",
                "score": 0.85,
                "rank": 3,
                "source": "cache",
                "confidence": 0.81,
                "asof_date": "2026-04-12",
            },
        ],
        stock_scores_meta={
            "requested_trade_date": "2026-04-12",
            "effective_asof_date": "2026-04-11",
        },
    )
    decision_plane_data = SimpleNamespace(
        alpha_actionable_count=2,
        actionable_candidates=[
            SimpleNamespace(
                candidate_id="cand-1",
                asset_code="000001",
                asset_name="平安银行",
                direction="LONG",
                confidence=0.91,
                asset_class="equity",
                valuation_repair=None,
            ),
            SimpleNamespace(
                candidate_id="cand-2",
                asset_code="002594.SZ",
                asset_name="比亚迪",
                direction="LONG",
                confidence=0.87,
                asset_class="equity",
                valuation_repair=None,
            ),
        ],
        pending_requests=[
            SimpleNamespace(
                request_id="req-1",
                asset_code="600519",
                asset_name="贵州茅台",
                direction="BUY",
                execution_status="PENDING",
            )
        ],
    )
    data = query.build(
        alpha_visualization_data=alpha_visualization_data,
        decision_plane_data=decision_plane_data,
    )

    assert data.top_stocks[0]["workflow_stage"] == "actionable"
    assert data.top_stocks[1]["workflow_stage"] == "pending"
    assert data.top_stocks[2]["workflow_stage"] == "top_ranked"
    assert data.overview == {
        "top_ranked_count": 3,
        "actionable_count": 2,
        "actionable_total_count": 2,
        "pending_count": 1,
        "top10_actionable_count": 1,
        "top10_pending_count": 1,
        "top10_rank_only_count": 1,
        "actionable_outside_top10_count": 1,
        "pending_outside_top10_count": 0,
        "actionable_conversion_pct": 33.3,
        "pending_conversion_pct": 33.3,
        "requested_trade_date": "2026-04-12",
        "effective_asof_date": "2026-04-11",
    }
    assert data.actionable_candidates[0]["is_in_top10"] is True
    assert data.actionable_candidates[0]["current_top_rank"] == 1
    assert data.actionable_candidates[1]["is_in_top10"] is False
    assert data.actionable_candidates[1]["origin_stage_label"] == "当前不在 Top 10"
    assert data.pending_requests[0]["is_in_top10"] is True
    assert data.pending_requests[0]["current_top_rank"] == 2
