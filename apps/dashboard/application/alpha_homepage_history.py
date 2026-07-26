"""History queries, serialization, and persistence for the Dashboard Alpha homepage."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol, cast

from django.utils import timezone as django_timezone

from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from apps.dashboard.application.repository_provider import (
    AlphaRecommendationHistoryRepository,
    DashboardAlphaContextRepository,
)

logger = logging.getLogger(__name__)


class AlphaHistoryRunView(Protocol):
    """Read-only history-run shape used by list serialization."""

    id: int
    portfolio_id: int | None
    portfolio_name: str
    trade_date: date
    scope_label: str
    source: str
    provider_source: str
    uses_cached_data: bool
    effective_asof_date: date | None
    cache_reason: str
    meta: object


def _parse_optional_history_date(value: object) -> tuple[date | None, bool]:
    """Parse an optional ISO date and report malformed metadata."""

    if value in (None, ""):
        return None, False
    if isinstance(value, date):
        return value, False
    if not isinstance(value, str):
        return None, True
    try:
        return date.fromisoformat(value), False
    except ValueError:
        return None, True


class AlphaHistoryMixin:
    """Private behavior shard for AlphaHomepageQuery."""

    history_repo: AlphaRecommendationHistoryRepository
    context_repo: DashboardAlphaContextRepository

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
        run_snapshots = list(run.snapshots.all())
        snapshot_codes = [
            str(snapshot.stock_code or "").strip().upper() for snapshot in run_snapshots
        ]
        stock_context = self.context_repo.load_stock_context(snapshot_codes, persist_names=False)
        snapshots: list[dict[str, Any]] = []
        for snapshot in run_snapshots:
            snapshot_code = str(snapshot.stock_code or "").strip().upper()
            fallback_name = str(
                (stock_context.get(snapshot_code) or {}).get("name") or snapshot_code
            ).strip()
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
        scope: AlphaPoolScope,
        alpha_result: AlphaResult,
        meta: dict[str, Any],
        snapshots: list[dict[str, Any]],
    ) -> int | None:
        try:
            requested_trade_date, requested_date_invalid = _parse_optional_history_date(
                meta.get("requested_trade_date")
            )
            effective_asof_date, effective_date_invalid = _parse_optional_history_date(
                meta.get("effective_asof_date")
            )
            persisted_meta = dict(alpha_result.metadata)
            invalid_date_fields = [
                field_name
                for field_name, is_invalid in (
                    ("requested_trade_date", requested_date_invalid),
                    ("effective_asof_date", effective_date_invalid),
                )
                if is_invalid
            ]
            if invalid_date_fields:
                persisted_meta["history_parse_warnings"] = invalid_date_fields
            run = self.history_repo.upsert_run(
                user_id=user_id,
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
                trade_date=django_timezone.localdate(),
                scope_hash=scope.scope_hash,
                scope_label=scope.display_label,
                scope_metadata=scope.to_dict(),
                model_hash=str(meta.get("model_hash") or ""),
                source=str(meta.get("source") or "none"),
                provider_source=str(meta.get("provider_source") or ""),
                requested_trade_date=requested_trade_date,
                effective_asof_date=effective_asof_date,
                uses_cached_data=bool(meta.get("uses_cached_data", False)),
                cache_reason=str(meta.get("cache_reason") or ""),
                fallback_reason=str(meta.get("fallback_reason") or ""),
                meta=persisted_meta,
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
            run_id = run.id
            return run_id if isinstance(run_id, int) and not isinstance(run_id, bool) else None
        except Exception as exc:
            logger.warning(
                "Failed to persist alpha homepage history (error_type=%s)",
                type(exc).__name__,
            )
            return None

    def _serialize_recent_runs(self, runs: Iterable[object]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for raw_run in runs:
            run = cast(AlphaHistoryRunView, raw_run)
            cache_reason = str(run.cache_reason or "")
            meta = dict(run.meta) if isinstance(run.meta, dict) else {}
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
