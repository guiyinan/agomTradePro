import re
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.dashboard.infrastructure.models import (
    AlphaRecommendationRunModel,
    AlphaRecommendationSnapshotModel,
)
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.fund.infrastructure.models import FundHoldingModel


@pytest.mark.django_db
def test_dashboard_tui_overview_projects_allocation_and_performance_rows(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    monkeypatch.setattr(
        "apps.dashboard.interface.tui_views.build_dashboard_data",
        lambda user_id: SimpleNamespace(
            display_name=f"User {user_id}",
            current_regime="Recovery",
            regime_confidence=0.82,
            total_assets=1_000_000.0,
            total_return=50_000.0,
            total_return_pct=5.0,
            cash_balance=200_000.0,
            invested_value=800_000.0,
            invested_ratio=0.8,
            position_count=3,
            active_signals=[{"id": 1}],
            pending_review_count=2,
            regime_data_health="healthy",
            allocation_data={"股票": 600_000.0, "债券": 200_000.0},
            performance_data=[
                {"date": "2026-07-25", "return_pct": 4.123456789},
            ],
        ),
    )

    response = client.get("/api/dashboard/tui/overview/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["regime_confidence_percent"] == 82.0
    assert payload["summary"]["invested_ratio_percent"] == 80.0
    assert payload["allocation"] == [
        {"asset_class": "股票", "market_value": 600000.0, "weight_percent": 75.0},
        {"asset_class": "债券", "market_value": 200000.0, "weight_percent": 25.0},
    ]
    assert payload["performance"] == [
        {"date": "2026-07-25", "return_pct": 4.123457},
    ]


@pytest.mark.django_db
def test_dashboard_beta_market_summary_exposes_decision_blockers(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    monkeypatch.setattr(
        "apps.dashboard.interface.tui_views.build_beta_market_summary_payload",
        lambda: {
            "beta_conclusion": "暂不判断：关键市场数据未通过校验。",
            "decision_status": "不可用于决策",
            "alpha_usage": "Alpha 仅供研究，暂不形成可执行建议。",
            "must_not_use_for_decision": True,
            "blocked_reason": "Pulse 数据已过期。",
        },
    )

    response = client.get("/api/dashboard/tui/beta-market-summary/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"][0]["decision_status"] == "不可用于决策"
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "Pulse 数据已过期。"


@pytest.mark.django_db
def test_dashboard_allocation_rejects_invalid_account_id(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/allocation/?account_id=bad-id")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "account_id" in payload["error"]


@pytest.mark.django_db
def test_dashboard_allocation_is_user_scoped_json_without_database_writes(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    calls = []
    monkeypatch.setattr(
        "apps.dashboard.interface.views._load_simulated_positions_fallback",
        lambda user_id, account_id=None: calls.append((user_id, account_id))
        or [
            {"asset_class": "equity", "market_value": 600000.0},
            {"asset_class_display": "债券", "market_value": 300000.0},
            {"asset_class": "equity", "market_value": 100000.0},
        ],
    )

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/dashboard/allocation/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "data": {"equity": 700000.0, "债券": 300000.0},
    }
    assert calls == [(auth_user.id, None)]
    mutation_sql = [
        query["sql"]
        for query in queries.captured_queries
        if re.match(
            r"^\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP)\b",
            query["sql"],
            re.IGNORECASE,
        )
    ]
    assert mutation_sql == []


@pytest.mark.django_db
def test_dashboard_positions_data_accepts_api_token(client, auth_user, monkeypatch):
    _, raw_key = UserAccessTokenModel.create_token(
        user=auth_user,
        name="dashboard-uat",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {raw_key}"
    monkeypatch.setattr(
        "apps.dashboard.interface.views._load_simulated_positions_fallback",
        lambda user_id, account_id=None: [],
    )

    response = client.get("/api/dashboard/positions/data/")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json()["data"]["positions"] == []


@pytest.mark.django_db
def test_dashboard_api_returns_401_for_missing_credentials(client):
    response = client.get("/api/dashboard/positions/data/")

    assert response.status_code == 401
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.headers["WWW-Authenticate"].startswith("Token")


@pytest.mark.django_db
def test_dashboard_positions_data_is_user_scoped_json_without_database_writes(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    calls = []
    positions = [
        {
            "account_id": 17,
            "account_name": "Core account",
            "asset_code": "510300.SH",
            "asset_name": "沪深300ETF",
            "asset_class": "etf",
            "market_value": 600000.0,
        }
    ]
    monkeypatch.setattr(
        "apps.dashboard.interface.views._load_simulated_positions_fallback",
        lambda user_id, account_id=None: calls.append((user_id, account_id)) or positions,
    )

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/dashboard/positions/data/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "data": {"positions": positions, "total_count": 1},
    }
    assert calls == [(auth_user.id, None)]
    mutation_sql = [
        query["sql"]
        for query in queries.captured_queries
        if re.match(
            r"^\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP)\b",
            query["sql"],
            re.IGNORECASE,
        )
    ]
    assert mutation_sql == []


@pytest.mark.django_db
def test_dashboard_equity_curve_v1_is_json_and_executes_no_database_writes(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    monkeypatch.setattr(
        "apps.dashboard.interface.views._build_dashboard_data",
        lambda user_id: SimpleNamespace(
            performance_data=[
                {
                    "date": "2026-07-12",
                    "portfolio_value": 1020000.0,
                    "return_pct": 2.0,
                }
            ],
            total_assets=1020000.0,
            total_return_pct=2.0,
        ),
    )

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/dashboard/v1/equity-curve/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "range": "ALL",
        "has_history": True,
        "series": [
            {
                "date": "2026-07-12",
                "portfolio_value": 1020000.0,
                "return_pct": 2.0,
            }
        ],
    }
    mutation_sql = [
        query["sql"]
        for query in queries.captured_queries
        if re.match(
            r"^\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP)\b",
            query["sql"],
            re.IGNORECASE,
        )
    ]
    assert mutation_sql == []


@pytest.mark.django_db
def test_dashboard_alpha_stocks_rejects_invalid_top_n(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/alpha/stocks/?format=json&top_n=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_stocks_contract_includes_equity_screen_metrics(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)

    monkeypatch.setattr(
        "apps.dashboard.interface.views._get_alpha_stock_scores_payload",
        lambda **kwargs: {
            "items": [
                {
                    "code": "000001.SZ",
                    "name": "平安银行",
                    "sector": "银行",
                    "market": "SZ",
                    "roe": 12.3,
                    "debt_ratio": 80.0,
                    "revenue_growth": 15.6,
                    "profit_growth": 18.2,
                    "pe": 5.6,
                    "pb": 0.72,
                    "ps": 1.34,
                    "dividend_yield": 4.5,
                    "report_date": "2026-03-31",
                    "valuation_trade_date": "2026-05-02",
                    "score": 0.913,
                    "alpha_score": 0.913,
                    "rank": 1,
                    "stage": "top_ranked",
                    "stage_label": "Alpha Top 候选/排名",
                    "source": "cache",
                    "confidence": 0.88,
                    "buy_reasons": [],
                    "no_buy_reasons": [],
                }
            ],
            "meta": {
                "status": "available",
                "source": "cache",
                "recommendation_ready": False,
                "must_not_use_for_decision": True,
                "readiness_status": "research_only",
                "blocked_reason": "仅研究。",
                "scope_verification_status": "general_universe",
            },
            "pool": {"label": "账户驱动 Alpha 池", "pool_size": 1, "pool_mode": "market"},
            "actionable_candidates": [],
            "exit_watchlist": [],
            "exit_watch_summary": {},
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": None,
        },
    )

    response = client.get("/api/dashboard/alpha/stocks/?format=json&top_n=1&alpha_scope=general")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    candidate = payload["data"]["top_candidates"][0]

    assert candidate["code"] == "000001.SZ"
    assert candidate["name"] == "平安银行"
    assert candidate["roe"] == 12.3
    assert candidate["pe"] == 5.6
    assert candidate["pb"] == 0.72
    assert candidate["revenue_growth"] == 15.6
    assert candidate["profit_growth"] == 18.2
    assert candidate["report_date"] == "2026-03-31"
    assert candidate["valuation_trade_date"] == "2026-05-02"


@pytest.mark.django_db
def test_dashboard_alpha_decision_chain_rejects_invalid_top_n(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/v1/alpha-decision-chain/?top_n=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_decision_chain_serializes_interface_mapping(
    client,
    auth_user,
    monkeypatch,
):
    client.force_login(auth_user)
    monkeypatch.setattr(
        "apps.dashboard.interface.views._get_alpha_decision_chain_data",
        lambda **kwargs: {
            "overview": {
                "generated_at": "2026-07-24T00:00:00Z",
                "warnings": ["empty_pool"],
                "workflow": {"stage": "screen"},
            },
            "top_stocks": [{"code": "000001.SZ"}],
            "actionable_candidates": [],
            "pending_requests": [],
        },
    )

    response = client.get("/api/dashboard/v1/alpha-decision-chain/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "summary": {
            "generated_at": "2026-07-24T00:00:00Z",
            "warnings": ["empty_pool"],
            "workflow": {"stage": "screen"},
        },
        "top_stocks": [{"code": "000001.SZ"}],
        "actionable_candidates": [],
        "pending_requests": [],
        "alpha_provider_status": {},
        "coverage_metrics": {},
        "ic_trends": [],
        "workflow": {"stage": "screen"},
        "decision_readiness": {},
        "warnings": ["empty_pool"],
        "generated_at": "2026-07-24T00:00:00Z",
    }


@pytest.mark.django_db
def test_dashboard_alpha_ic_trends_rejects_non_positive_days(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/alpha/ic-trends/?days=0")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "days" in payload["error"]


@pytest.mark.django_db
def test_dashboard_alpha_history_detail_fills_missing_snapshot_name_from_data_center(
    client,
    auth_user,
):
    client.force_login(auth_user)
    AssetMasterModel.objects.create(
        code="600519.SH",
        name="贵州茅台",
        short_name="茅台",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    run = AlphaRecommendationRunModel.objects.create(
        user=auth_user,
        portfolio_id=135,
        portfolio_name="测试组合",
        trade_date="2026-04-19",
        scope_hash="scope-001",
        scope_label="默认组合 · CN A-share 可交易池",
        source="cache",
        provider_source="cache",
        uses_cached_data=True,
        cache_reason="legacy snapshot missing name",
        fallback_reason="",
        meta={},
    )
    AlphaRecommendationSnapshotModel.objects.create(
        run=run,
        stock_code="600519.SH",
        stock_name="",
        stage="top_ranked",
        gate_status="pass",
        rank=1,
        alpha_score=0.95,
        confidence=0.91,
        source="cache",
        buy_reasons=[],
        no_buy_reasons=[],
        invalidation_rule={},
        risk_snapshot={},
        suggested_position_pct=10.0,
        suggested_notional=100000.0,
        suggested_quantity=100.0,
        extra_payload={},
    )

    response = client.get(f"/api/dashboard/alpha/history/{run.id}/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["snapshots"][0]["code"] == "600519.SH"
    assert payload["data"]["snapshots"][0]["name"] == "茅台"


@pytest.mark.django_db
def test_dashboard_alpha_history_detail_resolves_legacy_holding_name_without_writing_asset_master(
    client,
    auth_user,
):
    client.force_login(auth_user)
    run = AlphaRecommendationRunModel.objects.create(
        user=auth_user,
        portfolio_id=135,
        portfolio_name="测试组合",
        trade_date="2026-04-19",
        scope_hash="scope-legacy-001",
        scope_label="默认组合 · CN A-share 可交易池",
        source="cache",
        provider_source="cache",
        uses_cached_data=True,
        cache_reason="legacy holding fallback",
        fallback_reason="",
        meta={},
    )
    AlphaRecommendationSnapshotModel.objects.create(
        run=run,
        stock_code="601899.SH",
        stock_name="",
        stage="top_ranked",
        gate_status="pass",
        rank=1,
        alpha_score=0.88,
        confidence=0.83,
        source="cache",
        buy_reasons=[],
        no_buy_reasons=[],
        invalidation_rule={},
        risk_snapshot={},
        suggested_position_pct=8.0,
        suggested_notional=80000.0,
        suggested_quantity=100.0,
        extra_payload={},
    )
    FundHoldingModel.objects.create(
        fund_code="000001",
        report_date="2026-03-31",
        stock_code="601899.SH",
        stock_name="紫金矿业",
    )
    assets_before = list(
        AssetMasterModel.objects.filter(code="601899.SH").values("id", "code", "name")
    )

    response = client.get(f"/api/dashboard/alpha/history/{run.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["snapshots"][0]["name"] == "紫金矿业"
    assert assets_before == list(
        AssetMasterModel.objects.filter(code="601899.SH").values("id", "code", "name")
    )


@pytest.mark.django_db
def test_dashboard_alpha_history_is_user_scoped_and_read_only(client, auth_user):
    other_user = get_user_model().objects.create_user(
        username="dashboard_history_other",
        password="testpass123",
        email="dashboard-history-other@example.com",
    )
    own_run = AlphaRecommendationRunModel.objects.create(
        user=auth_user,
        portfolio_id=135,
        portfolio_name="Own Portfolio",
        trade_date="2026-07-11",
        scope_hash="scope-own",
        scope_label="Own scope",
        source="cache",
        provider_source="cache",
        uses_cached_data=True,
        cache_reason="",
        fallback_reason="",
        meta={},
    )
    other_run = AlphaRecommendationRunModel.objects.create(
        user=other_user,
        portfolio_id=246,
        portfolio_name="Other Portfolio",
        trade_date="2026-07-11",
        scope_hash="scope-other",
        scope_label="Other scope",
        source="cache",
        provider_source="cache",
        uses_cached_data=True,
        cache_reason="",
        fallback_reason="",
        meta={},
    )
    before_counts = {
        "runs": AlphaRecommendationRunModel.objects.count(),
        "snapshots": AlphaRecommendationSnapshotModel.objects.count(),
        "assets": AssetMasterModel.objects.count(),
    }

    client.force_login(auth_user)
    list_response = client.get("/api/dashboard/alpha/history/")
    other_detail_response = client.get(f"/api/dashboard/alpha/history/{other_run.id}/")

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["success"] is True
    assert [item["id"] for item in payload["data"]] == [own_run.id]
    assert other_detail_response.status_code == 404
    assert before_counts == {
        "runs": AlphaRecommendationRunModel.objects.count(),
        "snapshots": AlphaRecommendationSnapshotModel.objects.count(),
        "assets": AssetMasterModel.objects.count(),
    }
