from datetime import date
from types import SimpleNamespace

import pytest

from apps.dashboard.application.queries import (
    AlphaDecisionChainQuery,
    AlphaVisualizationQuery,
    DecisionPlaneQuery,
)
from apps.equity.infrastructure.models import StockInfoModel


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
        ):
            captured["user"] = user
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


def test_decision_plane_query_attach_asset_names_supports_exchange_suffix(monkeypatch):
    query = DecisionPlaneQuery()
    items = [
        SimpleNamespace(asset_code="000001.SZ", asset_name=""),
        SimpleNamespace(asset_code="510300.SH"),
        SimpleNamespace(asset_code="159915.SZ", asset_name="创业板ETF"),
    ]

    monkeypatch.setattr(
        "shared.infrastructure.asset_name_resolver.resolve_asset_names",
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
