"""Dashboard Alpha SDK contract tests."""

from typing import Any

from agomtradepro.modules.dashboard import DashboardModule


class _FakeClient:
    def __init__(
        self, get_payload: dict[str, Any] | None = None, post_payload: dict[str, Any] | None = None
    ) -> None:
        self.get_payload = get_payload or {}
        self.post_payload = post_payload or {}
        self.last_get: tuple[str, dict[str, Any] | None] | None = None
        self.last_post: tuple[str, dict[str, Any] | None] | None = None

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_get = (path, params)
        return self.get_payload

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_post = (path, data or json)
        return self.post_payload


def test_alpha_stocks_contract_marks_missing_cache_as_async_not_recommendation() -> None:
    fake_client = _FakeClient(
        get_payload={
            "success": True,
            "data": {
                "top_candidates": [],
                "pending_requests": [{"id": 1, "stock_code": "600519.SH"}],
                "meta": {
                    "refresh_status": "queued",
                    "async_task_id": "task-1",
                    "poll_after_ms": 5000,
                    "hardcoded_fallback_used": False,
                    "no_recommendation_reason": "No account-scope Alpha cache.",
                    "source": "none",
                    "status": "unavailable",
                    "scope_hash": "scope-1",
                },
            },
        }
    )
    module = DashboardModule(fake_client)

    result = module.alpha_stocks(top_n=10, portfolio_id=135, pool_mode="market")
    contract = result["contract"]

    assert fake_client.last_get == (
        "/api/dashboard/alpha/stocks/",
        {"format": "json", "top_n": 10, "portfolio_id": 135, "pool_mode": "market"},
    )
    assert contract["recommendation_ready"] is False
    assert contract["must_not_treat_as_recommendation"] is True
    assert contract["async_refresh_queued"] is True
    assert contract["hardcoded_fallback_used"] is False
    assert contract["top_candidate_count"] == 0
    assert contract["pending_request_count"] == 1
    assert contract["async_task_id"] == "task-1"
    assert result["data"]["contract"] == contract


def test_alpha_stocks_contract_marks_real_scoped_scores_as_recommendation_ready() -> None:
    module = DashboardModule(
        _FakeClient(
            get_payload={
                "success": True,
                "data": {
                    "top_candidates": [
                        {
                            "stock_code": "000001.SZ",
                            "recommendation_basis": {
                                "provider": "cache",
                                "source": "qlib",
                                "score": 0.91,
                                "confidence": 0.82,
                            },
                        }
                    ],
                    "pending_requests": [],
                    "meta": {
                        "refresh_status": "available",
                        "hardcoded_fallback_used": False,
                        "source": "cache",
                        "status": "available",
                        "scope_hash": "scope-1",
                    },
                },
            }
        )
    )

    result = module.alpha_stocks()
    contract = result["contract"]

    assert contract["recommendation_ready"] is True
    assert contract["must_not_treat_as_recommendation"] is False
    assert contract["top_candidate_count"] == 1
    assert contract["hardcoded_fallback_used"] is False


def test_alpha_refresh_contract_is_explicitly_async_and_not_a_recommendation() -> None:
    fake_client = _FakeClient(
        post_payload={
            "success": True,
            "task_id": "task-refresh-1",
            "refresh_status": "queued",
            "poll_after_ms": 5000,
        }
    )
    module = DashboardModule(fake_client)

    result = module.alpha_refresh(top_n=20, portfolio_id=135, pool_mode="price_covered")
    contract = result["contract"]

    assert fake_client.last_post == (
        "/api/dashboard/alpha/refresh/",
        {"top_n": 20, "portfolio_id": 135, "pool_mode": "price_covered"},
    )
    assert contract["recommendation_ready"] is False
    assert contract["must_not_treat_as_recommendation"] is True
    assert contract["async_refresh_queued"] is True
    assert contract["async_task_id"] == "task-refresh-1"
    assert contract["hardcoded_fallback_used"] is False
