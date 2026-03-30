from datetime import date
from types import SimpleNamespace

from apps.dashboard.application.queries import AlphaVisualizationQuery


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
