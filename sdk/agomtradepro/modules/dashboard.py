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
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "format": "json",
            "top_n": top_n,
        }
        if portfolio_id is not None:
            params["portfolio_id"] = portfolio_id
        if pool_mode:
            params["pool_mode"] = pool_mode
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
        refresh_status = str(meta.get("refresh_status") or "")
        async_task_id = str(meta.get("async_task_id") or "")
        hardcoded_fallback_used = bool(meta.get("hardcoded_fallback_used", False))
        no_recommendation_reason = str(meta.get("no_recommendation_reason") or "")
        recommendation_ready = bool(top_candidates) and not hardcoded_fallback_used
        if no_recommendation_reason:
            recommendation_ready = False
        async_refresh_queued = DashboardModule._is_async_refresh_active(
            refresh_status=refresh_status,
            async_task_id=async_task_id,
        )

        contract = {
            "recommendation_ready": recommendation_ready,
            "must_not_treat_as_recommendation": not recommendation_ready,
            "async_refresh_queued": async_refresh_queued,
            "refresh_status": refresh_status,
            "async_task_id": async_task_id,
            "poll_after_ms": DashboardModule._safe_int(meta.get("poll_after_ms"), default=5000),
            "hardcoded_fallback_used": hardcoded_fallback_used,
            "no_recommendation_reason": no_recommendation_reason,
            "top_candidate_count": len(top_candidates) if isinstance(top_candidates, list) else 0,
            "pending_request_count": (
                len(pending_requests) if isinstance(pending_requests, list) else 0
            ),
            "source": str(meta.get("source") or ""),
            "status": str(meta.get("status") or ""),
            "scope_hash": str(meta.get("scope_hash") or ""),
        }
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"top_n": top_n}
        if portfolio_id is not None:
            payload["portfolio_id"] = portfolio_id
        if pool_mode:
            payload["pool_mode"] = pool_mode
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
        poll_after_ms = (
            data.get("poll_after_ms")
            if isinstance(data, dict) and data.get("poll_after_ms") is not None
            else payload.get("poll_after_ms")
        )
        contract = {
            "recommendation_ready": False,
            "must_not_treat_as_recommendation": True,
            "async_refresh_queued": DashboardModule._is_async_refresh_active(
                refresh_status=refresh_status,
                async_task_id=async_task_id,
            ),
            "refresh_status": refresh_status,
            "async_task_id": async_task_id,
            "poll_after_ms": DashboardModule._safe_int(poll_after_ms, default=5000),
            "hardcoded_fallback_used": False,
            "no_recommendation_reason": "Refresh only queues scoped Alpha inference; call alpha_stocks after completion.",
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
