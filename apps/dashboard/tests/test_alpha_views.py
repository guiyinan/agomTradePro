import json
from types import SimpleNamespace

from django.test import RequestFactory

from apps.dashboard.interface import views


def test_alpha_stocks_htmx_passes_request_user_to_query(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def execute(self, top_n: int, ic_days: int, user=None):
            captured["top_n"] = top_n
            captured["ic_days"] = ic_days
            captured["user"] = user
            return SimpleNamespace(
                stock_scores=[
                    {
                        "code": "000001.SZ",
                        "name": "平安银行",
                        "score": 0.91,
                        "rank": 1,
                    }
                ],
                stock_scores_meta={
                    "status": "degraded",
                    "source": "cache",
                    "uses_cached_data": True,
                    "warning_message": "当前展示的是历史缓存评分。",
                },
            )

    request = RequestFactory().get(
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "top_n": 1},
    )
    request.user = SimpleNamespace(is_authenticated=True, username="admin")

    monkeypatch.setattr(views, "get_alpha_visualization_query", lambda: FakeQuery())

    response = views.alpha_stocks_htmx(request)
    payload = json.loads(response.content)

    assert captured["user"] is request.user
    assert captured["top_n"] == 1
    assert captured["ic_days"] == 30
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["meta"]["uses_cached_data"] is True


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
