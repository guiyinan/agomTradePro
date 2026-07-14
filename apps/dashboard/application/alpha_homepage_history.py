"""History queries, serialization, and persistence for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.utils import timezone as django_timezone

logger = logging.getLogger(__name__)


class AlphaHistoryMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    def list_history(
        self,
        *,
        user_id: int,
        portfolio_id: int | None = None,
        stock_code: str | None = None,
        stage: str | None = None,
        source: str | None = None,
        trade_date: date | None = None,
    ) -> list[dict[str, Any]]:
        runs = self.history_repo.filter_runs(
            user_id=user_id,
            portfolio_id=portfolio_id,
            stock_code=stock_code,
            stage=stage,
            source=source,
            trade_date=trade_date,
        )
        return self._serialize_recent_runs(runs)

    def get_history_detail(self, *, user_id: int, run_id: int) -> dict[str, Any] | None:
        run = self.history_repo.get_run_detail(user_id=user_id, run_id=run_id)
        if run is None:
            return None
        snapshot_codes = [
            str(snapshot.stock_code or "").strip().upper() for snapshot in run.snapshots.all()
        ]
        stock_context = self.context_repo.load_stock_context(snapshot_codes, persist_names=False)
        snapshots = []
        for snapshot in run.snapshots.all():
            snapshot_code = str(snapshot.stock_code or "").strip().upper()
            fallback_name = (stock_context.get(snapshot_code) or {}).get("name") or snapshot_code
            stock_name = str(snapshot.stock_name or "").strip() or fallback_name
            if stock_name.upper() == snapshot_code:
                stock_name = fallback_name
            snapshots.append(
                {
                    "code": snapshot_code,
                    "name": stock_name,
                    "stage": snapshot.stage,
                    "gate_status": snapshot.gate_status,
                    "rank": snapshot.rank,
                    "alpha_score": snapshot.alpha_score,
                    "confidence": snapshot.confidence,
                    "source": snapshot.source,
                    "buy_reasons": snapshot.buy_reasons,
                    "no_buy_reasons": snapshot.no_buy_reasons,
                    "invalidation_rule": snapshot.invalidation_rule,
                    "risk_snapshot": snapshot.risk_snapshot,
                    "suggested_position_pct": snapshot.suggested_position_pct,
                    "suggested_notional": snapshot.suggested_notional,
                    "suggested_quantity": snapshot.suggested_quantity,
                    "extra_payload": snapshot.extra_payload,
                }
            )
        return {
            "id": run.id,
            "portfolio_id": run.portfolio_id,
            "portfolio_name": run.portfolio_name,
            "trade_date": run.trade_date.isoformat(),
            "scope_label": run.scope_label,
            "source": run.source,
            "provider_source": run.provider_source,
            "uses_cached_data": run.uses_cached_data,
            "cache_reason": run.cache_reason,
            "fallback_reason": run.fallback_reason,
            "requested_trade_date": (
                run.requested_trade_date.isoformat() if run.requested_trade_date else None
            ),
            "effective_asof_date": (
                run.effective_asof_date.isoformat() if run.effective_asof_date else None
            ),
            "meta": run.meta,
            "snapshots": snapshots,
        }

    def _persist_history(
        self,
        *,
        user_id: int,
        portfolio_id: int | None,
        portfolio_name: str,
        scope,
        alpha_result,
        meta: dict[str, Any],
        snapshots: list[dict[str, Any]],
    ) -> int | None:
        try:
            run = self.history_repo.upsert_run(
                user_id=user_id,
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
                trade_date=django_timezone.localdate(),
                scope_hash=scope.scope_hash,
                scope_label=scope.display_label,
                scope_metadata=scope.to_dict(),
                model_hash=meta.get("model_hash", ""),
                source=meta.get("source", "none"),
                provider_source=meta.get("provider_source", ""),
                requested_trade_date=(
                    date.fromisoformat(meta["requested_trade_date"])
                    if meta.get("requested_trade_date")
                    else None
                ),
                effective_asof_date=(
                    date.fromisoformat(meta["effective_asof_date"])
                    if meta.get("effective_asof_date")
                    else None
                ),
                uses_cached_data=bool(meta.get("uses_cached_data", False)),
                cache_reason=str(meta.get("cache_reason") or ""),
                fallback_reason=str(meta.get("fallback_reason") or ""),
                meta=dict(getattr(alpha_result, "metadata", {}) or {}),
            )
            self.history_repo.replace_snapshots(
                run=run,
                snapshots=[
                    {
                        "stock_code": item["code"],
                        "stock_name": item.get("name", ""),
                        "stage": item.get("stage", "top_ranked"),
                        "gate_status": item.get("gate_status", "blocked"),
                        "rank": item.get("rank", 0),
                        "alpha_score": item.get("alpha_score", 0.0),
                        "confidence": item.get("confidence", 0.0),
                        "source": item.get("source", ""),
                        "buy_reasons": item.get("buy_reasons", []),
                        "no_buy_reasons": item.get("no_buy_reasons", []),
                        "invalidation_rule": item.get("invalidation_rule", {}),
                        "risk_snapshot": item.get("risk_snapshot", {}),
                        "suggested_position_pct": item.get("suggested_position_pct", 0.0),
                        "suggested_notional": item.get("suggested_notional", 0.0),
                        "suggested_quantity": item.get("suggested_quantity", 0.0),
                        "source_candidate_id": item.get("source_candidate_id"),
                        "source_recommendation_id": item.get("source_recommendation_id"),
                        "extra_payload": item.get("extra_payload", {}),
                    }
                    for item in snapshots
                ],
            )
            return run.id
        except Exception as exc:
            logger.warning("Failed to persist alpha homepage history: %s", exc, exc_info=True)
            return None

    def _serialize_recent_runs(self, runs) -> list[dict[str, Any]]:
        payload = []
        for run in runs:
            cache_reason = str(run.cache_reason or "")
            meta = dict(getattr(run, "meta", {}) or {})
            legacy_hardcoded_fallback = (
                meta.get("fallback_mode") == "homepage_market_cache_fallback"
                or "csi300 全局缓存" in cache_reason
                or "全局缓存排名" in cache_reason
            )
            payload.append(
                {
                    "id": run.id,
                    "portfolio_id": run.portfolio_id,
                    "portfolio_name": run.portfolio_name,
                    "trade_date": run.trade_date.isoformat(),
                    "scope_label": run.scope_label,
                    "source": run.source,
                    "provider_source": run.provider_source,
                    "uses_cached_data": run.uses_cached_data,
                    "effective_asof_date": (
                        run.effective_asof_date.isoformat() if run.effective_asof_date else None
                    ),
                    "cache_reason": cache_reason,
                    "legacy_hardcoded_fallback": legacy_hardcoded_fallback,
                    "reliability_note": (
                        "旧版硬编码回退记录，仅用于审计回溯，不作为当前推荐依据。"
                        if legacy_hardcoded_fallback
                        else ""
                    ),
                }
            )
        return payload
