"""AgomTradePro SDK - Dashboard 模块。"""

from typing import Any

from .base import BaseModule


class DashboardModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/dashboard")

    def position_detail(self, asset_code: str) -> dict[str, Any]:
        return self._get(f"position/{asset_code}/")

    def positions(self) -> dict[str, Any]:
        return self._get("positions/")

    def allocation(self) -> dict[str, Any]:
        return self._get("allocation/")

    def performance(self) -> dict[str, Any]:
        return self._get("performance/")

    def summary_v1(self) -> dict[str, Any]:
        return self._get("v1/summary/")

    def regime_quadrant_v1(self) -> dict[str, Any]:
        return self._get("v1/regime-quadrant/")

    def equity_curve_v1(self) -> dict[str, Any]:
        return self._get("v1/equity-curve/")

    def signal_status_v1(self) -> dict[str, Any]:
        return self._get("v1/signal-status/")

    def alpha_decision_chain_v1(
        self,
        top_n: int = 10,
        max_candidates: int = 5,
        max_pending: int = 10,
    ) -> dict[str, Any]:
        return self._get(
            "v1/alpha-decision-chain/",
            params={
                "top_n": top_n,
                "max_candidates": max_candidates,
                "max_pending": max_pending,
            },
        )

    def alpha_stocks(
        self,
        top_n: int = 10,
        portfolio_id: int | None = None,
        pool_mode: str | None = None,
        alpha_scope: str | None = None,
    ) -> dict[str, Any]:
        """Read Dashboard Alpha results for either the general or portfolio scope."""
        params: dict[str, Any] = {
            "format": "json",
            "top_n": top_n,
        }
        if portfolio_id is not None:
            params["portfolio_id"] = portfolio_id
        if pool_mode:
            params["pool_mode"] = pool_mode
        if alpha_scope:
            params["alpha_scope"] = alpha_scope
        payload = self._get("alpha/stocks/", params=params)
        return self._with_alpha_candidate_contract(payload)

    @staticmethod
    def _with_alpha_candidate_contract(payload: dict[str, Any]) -> dict[str, Any]:
        """Attach a stable MCP/SDK contract summary without dropping raw API fields."""
        if not isinstance(payload, dict):
            return payload

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            return payload

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        top_candidates = data.get("top_candidates") or data.get("items") or []
        pending_requests = data.get("pending_requests") or []
        actionable_candidates = data.get("actionable_candidates") or []
        existing_contract = data.get("contract") if isinstance(data.get("contract"), dict) else {}
        alpha_scope = str(
            meta.get("alpha_scope")
            or data.get("alpha_scope")
            or payload.get("alpha_scope")
            or "portfolio"
        )
        refresh_status = str(meta.get("refresh_status") or "")
        async_task_id = str(meta.get("async_task_id") or "")
        hardcoded_fallback_used = bool(meta.get("hardcoded_fallback_used", False))
        no_recommendation_reason = str(meta.get("no_recommendation_reason") or "")
        scope_verification_status = str(meta.get("scope_verification_status") or "")
        verified_scope_hash = str(meta.get("verified_scope_hash") or "")
        if not verified_scope_hash and scope_verification_status == "verified":
            verified_scope_hash = str(meta.get("scope_hash") or "")
        verified_asof_date = meta.get("verified_asof_date")
        if verified_asof_date in (None, "") and scope_verification_status == "verified":
            verified_asof_date = meta.get("effective_asof_date")
        if "recommendation_ready" in meta:
            recommendation_ready = bool(meta.get("recommendation_ready"))
        elif existing_contract:
            recommendation_ready = bool(existing_contract.get("recommendation_ready", False))
        else:
            recommendation_ready = bool(top_candidates) and not hardcoded_fallback_used
            if no_recommendation_reason:
                recommendation_ready = False
        if alpha_scope == "general":
            recommendation_ready = False
            if not no_recommendation_reason:
                no_recommendation_reason = "General Alpha is research-only and must not be used for decisions."
        async_refresh_queued = DashboardModule._is_async_refresh_active(
            refresh_status=refresh_status,
            async_task_id=async_task_id,
        )

        contract = {
            "alpha_scope": alpha_scope,
            "recommendation_ready": recommendation_ready,
            "must_not_treat_as_recommendation": not recommendation_ready,
            "must_not_use_for_decision": not recommendation_ready,
            "readiness_status": str(meta.get("readiness_status") or ""),
            "blocked_reason": str(meta.get("blocked_reason") or no_recommendation_reason),
            "async_refresh_queued": async_refresh_queued,
            "refresh_status": refresh_status,
            "async_task_id": async_task_id,
            "poll_after_ms": DashboardModule._safe_int(meta.get("poll_after_ms"), default=5000),
            "hardcoded_fallback_used": hardcoded_fallback_used,
            "no_recommendation_reason": no_recommendation_reason,
            "top_candidate_count": len(top_candidates) if isinstance(top_candidates, list) else 0,
            "actionable_candidate_count": (
                len(actionable_candidates) if isinstance(actionable_candidates, list) else 0
            ),
            "pending_request_count": (
                len(pending_requests) if isinstance(pending_requests, list) else 0
            ),
            "source": str(meta.get("source") or ""),
            "status": str(meta.get("status") or ""),
            "scope_hash": str(meta.get("scope_hash") or ""),
            "scope_verification_status": scope_verification_status,
            "freshness_status": str(meta.get("freshness_status") or ""),
            "result_age_days": meta.get("result_age_days"),
            "is_stale": bool(meta.get("is_stale", False)),
            "latest_available_qlib_result": bool(meta.get("latest_available_qlib_result", False)),
            "derived_from_broader_cache": bool(meta.get("derived_from_broader_cache", False)),
            "trade_date_adjusted": bool(meta.get("trade_date_adjusted", False)),
            "verified_scope_hash": verified_scope_hash,
            "verified_asof_date": verified_asof_date,
        }
        if existing_contract:
            contract = {**contract, **existing_contract}
        payload["contract"] = contract
        if payload.get("data") is data:
            data["contract"] = contract
        return payload

    def alpha_history(
        self,
        portfolio_id: int | None = None,
        trade_date: str | None = None,
        stock_code: str | None = None,
        stage: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if portfolio_id is not None:
            params["portfolio_id"] = portfolio_id
        if trade_date:
            params["trade_date"] = trade_date
        if stock_code:
            params["stock_code"] = stock_code
        if stage:
            params["stage"] = stage
        if source:
            params["source"] = source
        return self._get("alpha/history/", params=params)

    def alpha_history_detail(self, run_id: int) -> dict[str, Any]:
        return self._get(f"alpha/history/{run_id}/")

    def alpha_refresh(
        self,
        top_n: int = 10,
        portfolio_id: int | None = None,
        pool_mode: str | None = None,
        alpha_scope: str | None = None,
    ) -> dict[str, Any]:
        """Queue Dashboard Alpha recomputation for the requested scope."""
        payload: dict[str, Any] = {"top_n": top_n}
        if portfolio_id is not None:
            payload["portfolio_id"] = portfolio_id
        if pool_mode:
            payload["pool_mode"] = pool_mode
        if alpha_scope:
            payload["alpha_scope"] = alpha_scope
        response = self._post("alpha/refresh/", data=payload)
        return self._with_alpha_refresh_contract(response)

    @staticmethod
    def _with_alpha_refresh_contract(payload: dict[str, Any]) -> dict[str, Any]:
        """Attach async refresh semantics for SDK/MCP callers."""
        if not isinstance(payload, dict):
            return payload

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        async_task_id = str(
            payload.get("task_id")
            or payload.get("async_task_id")
            or (data.get("task_id") if isinstance(data, dict) else "")
            or (data.get("async_task_id") if isinstance(data, dict) else "")
            or ""
        )
        refresh_status = str(
            payload.get("refresh_status")
            or payload.get("status")
            or (data.get("refresh_status") if isinstance(data, dict) else "")
            or (data.get("status") if isinstance(data, dict) else "")
            or "queued"
        )
        alpha_scope = str(
            payload.get("alpha_scope")
            or (data.get("alpha_scope") if isinstance(data, dict) else "")
            or "portfolio"
        )
        poll_after_ms = (
            data.get("poll_after_ms")
            if isinstance(data, dict) and data.get("poll_after_ms") is not None
            else payload.get("poll_after_ms")
        )
        if alpha_scope == "general":
            refresh_blocked_reason = (
                "Refresh only queues general Alpha research ranking; it must remain research-only."
            )
        else:
            refresh_blocked_reason = (
                "Refresh only queues scoped Alpha inference; call alpha_stocks after completion."
            )
        contract = {
            "alpha_scope": alpha_scope,
            "recommendation_ready": False,
            "must_not_treat_as_recommendation": True,
            "must_not_use_for_decision": True,
            "readiness_status": "refresh_queued",
            "blocked_reason": refresh_blocked_reason,
            "async_refresh_queued": DashboardModule._is_async_refresh_active(
                refresh_status=refresh_status,
                async_task_id=async_task_id,
            ),
            "refresh_status": refresh_status,
            "async_task_id": async_task_id,
            "poll_after_ms": DashboardModule._safe_int(poll_after_ms, default=5000),
            "hardcoded_fallback_used": False,
            "no_recommendation_reason": refresh_blocked_reason,
            "scope_verification_status": "pending_refresh",
            "freshness_status": "pending_refresh",
            "result_age_days": None,
            "is_stale": False,
            "latest_available_qlib_result": False,
            "derived_from_broader_cache": False,
            "trade_date_adjusted": False,
            "verified_scope_hash": "",
            "verified_asof_date": None,
        }
        payload["contract"] = contract
        if isinstance(data, dict) and payload.get("data") is data:
            data["contract"] = contract
        return payload

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_async_refresh_active(refresh_status: str, async_task_id: str) -> bool:
        status = refresh_status.lower()
        if status in {"queued", "recently_queued", "pending", "running", "started"}:
            return True
        if status in {"failed", "skipped", "available", "completed", "success", "done"}:
            return False
        return bool(async_task_id)

    def alpha_provider_status(self) -> dict[str, Any]:
        return self._get("alpha/provider-status/")

    def alpha_coverage(self) -> dict[str, Any]:
        return self._get("alpha/coverage/")

    def alpha_ic_trends(self) -> dict[str, Any]:
        return self._get("alpha/ic-trends/")
