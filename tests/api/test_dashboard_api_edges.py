import pytest
from django.contrib.auth import get_user_model

from apps.dashboard.infrastructure.models import (
    AlphaRecommendationRunModel,
    AlphaRecommendationSnapshotModel,
)
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.fund.infrastructure.models import FundHoldingModel


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="dashboard_api_user",
        password="testpass123",
        email="dashboard@example.com",
    )


@pytest.mark.django_db
def test_dashboard_api_root_contract(client):
    response = client.get("/api/dashboard/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["allocation"] == "/api/dashboard/allocation/"
    assert payload["endpoints"]["alpha_stocks"] == "/api/dashboard/alpha/stocks/"
    assert (
        payload["endpoints"]["v1_alpha_decision_chain"]
        == "/api/dashboard/v1/alpha-decision-chain/"
    )


@pytest.mark.django_db
def test_dashboard_allocation_rejects_invalid_account_id(client, auth_user):
    client.force_login(auth_user)

    response = client.get("/api/dashboard/allocation/?account_id=bad-id")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "account_id" in payload["error"]


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

    response = client.get("/api/dashboard/alpha/stocks/?format=json&top_n=1")

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
def test_dashboard_alpha_history_detail_backfills_asset_master_from_legacy_holding(
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

    response = client.get(f"/api/dashboard/alpha/history/{run.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["snapshots"][0]["name"] == "紫金矿业"
    assert AssetMasterModel.objects.filter(code="601899.SH", name="紫金矿业").exists()
