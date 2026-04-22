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


def test_alpha_stocks_contract_respects_backend_readiness_metadata() -> None:
    module = DashboardModule(
        _FakeClient(
            get_payload={
                "success": True,
                "data": {
                    "top_candidates": [{"stock_code": "000001.SZ"}],
                    "actionable_candidates": [],
                    "pending_requests": [],
                    "meta": {
                        "recommendation_ready": False,
                        "must_not_use_for_decision": True,
                        "readiness_status": "blocked_broader_scope_cache",
                        "blocked_reason": "当前结果来自 broader-scope cache 映射。",
                        "scope_verification_status": "derived_from_broader_cache",
                        "freshness_status": "fresh",
                        "result_age_days": 0,
                        "latest_available_qlib_result": False,
                        "derived_from_broader_cache": True,
                        "scope_hash": "scope-1",
                    },
                },
            }
        )
    )

    result = module.alpha_stocks()
    contract = result["contract"]

    assert contract["recommendation_ready"] is False
    assert contract["must_not_treat_as_recommendation"] is True
    assert contract["readiness_status"] == "blocked_broader_scope_cache"
    assert contract["scope_verification_status"] == "derived_from_broader_cache"
    assert contract["freshness_status"] == "fresh"
    assert contract["blocked_reason"] == "当前结果来自 broader-scope cache 映射。"
    assert contract["derived_from_broader_cache"] is True


def test_alpha_stocks_contract_exposes_trade_date_adjustment_and_scope_trace() -> None:
    module = DashboardModule(
        _FakeClient(
            get_payload={
                "success": True,
                "data": {
                    "top_candidates": [{"stock_code": "000001.SZ"}],
                    "actionable_candidates": [],
                    "pending_requests": [],
                    "meta": {
                        "recommendation_ready": False,
                        "must_not_use_for_decision": True,
                        "readiness_status": "blocked_trade_date_adjusted",
                        "blocked_reason": "请求交易日 2026-04-21 的 Qlib 日线尚未落地。",
                        "scope_verification_status": "verified",
                        "freshness_status": "trade_date_adjusted",
                        "result_age_days": 1,
                        "is_stale": True,
                        "latest_available_qlib_result": True,
                        "derived_from_broader_cache": False,
                        "trade_date_adjusted": True,
                        "scope_hash": "scope-1",
                        "effective_asof_date": "2026-04-20",
                    },
                },
            }
        )
    )

    result = module.alpha_stocks()
    contract = result["contract"]

    assert contract["recommendation_ready"] is False
    assert contract["must_not_use_for_decision"] is True
    assert contract["readiness_status"] == "blocked_trade_date_adjusted"
    assert contract["scope_verification_status"] == "verified"
    assert contract["freshness_status"] == "trade_date_adjusted"
    assert contract["trade_date_adjusted"] is True
    assert contract["verified_scope_hash"] == "scope-1"
    assert contract["verified_asof_date"] == "2026-04-20"


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
    assert contract["readiness_status"] == "refresh_queued"
