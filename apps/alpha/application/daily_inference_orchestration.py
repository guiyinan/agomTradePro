"""Application orchestration for scheduled Alpha inference entrypoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from apps.alpha.application import task_outcome_contracts as _outcomes
from apps.alpha.domain.entities import AlphaPoolScope, normalize_stock_code

logger = logging.getLogger(__name__)

RefreshRuntime = Callable[..., dict[str, Any]]
QueuePrediction = Callable[..., Any]
RepositoryFactory = Callable[[], Any]
TradeDateResolver = Callable[[], date]
CacheFreshnessChecker = Callable[[Any | None, date], bool]


def run_daily_inference(
    *,
    universe_id: str,
    top_n: int,
    refresh_data: bool,
    refresh_universes: str | list[str] | tuple[str, ...] | None,
    lookback_days: int,
    trade_date: str | None,
    resolve_trade_date: TradeDateResolver,
    refresh_runtime_data: RefreshRuntime,
    queue_prediction: QueuePrediction,
) -> dict[str, Any]:
    """Refresh one universe and queue its prediction task."""

    trade_date_obj = date.fromisoformat(trade_date) if trade_date else resolve_trade_date()
    refresh_result: dict[str, Any] = {"status": "skipped", "reason": "refresh_disabled"}
    if refresh_data:
        try:
            refresh_result = refresh_runtime_data(
                target_date=trade_date_obj,
                universes=refresh_universes or universe_id,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            logger.error("Qlib 每日数据刷新失败，继续尝试推理: %s", exc, exc_info=True)
            refresh_result = {"status": "failed", "error": str(exc)}

    normalized_trade_date = trade_date_obj.isoformat()
    try:
        result = queue_prediction(universe_id, normalized_trade_date, top_n)
    except Exception as exc:
        logger.error(
            "Qlib daily inference queue failed: error_type=%s",
            exc.__class__.__name__,
        )
        return {
            "status": "error",
            "reason": "prediction_queue_failed",
            "universe_id": universe_id,
            "trade_date": normalized_trade_date,
            "top_n": top_n,
            "refresh_result": refresh_result,
            **_outcomes.daily_inference_outcome(
                refresh_data=refresh_data,
                refresh_status=refresh_result.get("status"),
                queue_succeeded=False,
            ),
        }
    return {
        "status": "queued",
        "task_id": result.id,
        "universe_id": universe_id,
        "trade_date": normalized_trade_date,
        "top_n": top_n,
        "refresh_result": refresh_result,
        **_outcomes.daily_inference_outcome(
            refresh_data=refresh_data,
            refresh_status=refresh_result.get("status"),
            queue_succeeded=True,
        ),
    }


def run_scoped_inference(
    *,
    top_n: int,
    portfolio_limit: int,
    pool_mode: str,
    refresh_data: bool,
    lookback_days: int,
    trade_date: str | None,
    only_missing: bool,
    resolve_trade_date: TradeDateResolver,
    get_active_model: Callable[[], Any],
    get_score_cache_repository: RepositoryFactory,
    get_pool_repository: RepositoryFactory,
    cache_is_fresh: CacheFreshnessChecker,
    refresh_runtime_for_codes: RefreshRuntime,
    queue_prediction: QueuePrediction,
) -> dict[str, Any]:
    """Resolve active portfolio scopes, refresh missing data, and queue predictions."""

    from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver

    target_trade_date = date.fromisoformat(trade_date) if trade_date else resolve_trade_date()
    active_model = get_active_model()
    if active_model is None:
        return {
            "status": "skipped",
            "reason": "no_active_model",
            "trade_date": target_trade_date.isoformat(),
            **_outcomes.refresh_summary_outcome(status="blocked", requested=1),
        }

    cache_repository = get_score_cache_repository()
    portfolio_refs = get_pool_repository().list_active_portfolio_refs(limit=portfolio_limit)
    resolver = PortfolioAlphaPoolResolver()

    resolved_scopes: list[tuple[dict[str, Any], AlphaPoolScope]] = []
    scoped_codes: set[str] = set()
    seen_scope_keys: set[tuple[str, str | None]] = set()
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    fresh_cache_count = 0
    failed_count = 0
    for ref in portfolio_refs:
        try:
            resolved = resolver.resolve(
                user_id=int(ref["user_id"]),
                portfolio_id=int(ref["portfolio_id"]),
                trade_date=target_trade_date,
                pool_mode=pool_mode,
            )
            if resolved.scope.pool_size == 0:
                skipped.append({"portfolio_id": ref["portfolio_id"], "reason": "empty_scope"})
                continue
            scope_key = (resolved.scope.universe_id, resolved.scope.scope_hash)
            if scope_key in seen_scope_keys:
                skipped.append(
                    {
                        "portfolio_id": ref["portfolio_id"],
                        "reason": "duplicate_scope",
                        "scope_hash": resolved.scope.scope_hash,
                    }
                )
                continue
            seen_scope_keys.add(scope_key)
            if only_missing:
                existing_cache = cache_repository.get_qlib_cache_for_trade_date(
                    universe_id=resolved.scope.universe_id,
                    trade_date=target_trade_date,
                    model_artifact_hash=getattr(active_model, "artifact_hash", None),
                    scope_hash=resolved.scope.scope_hash,
                )
                if existing_cache is not None and cache_is_fresh(existing_cache, target_trade_date):
                    fresh_cache_count += 1
                    skipped.append(
                        {
                            "portfolio_id": ref["portfolio_id"],
                            "reason": "fresh_cache_exists",
                            "scope_hash": resolved.scope.scope_hash,
                            "asof_date": existing_cache.asof_date.isoformat(),
                        }
                    )
                    continue
            resolved_scopes.append((ref, resolved.scope))
            scoped_codes.update(
                normalized
                for normalized in (
                    normalize_stock_code(code)
                    for code in getattr(resolved.scope, "instrument_codes", ()) or ()
                )
                if normalized
            )
        except Exception as exc:
            failed_count += 1
            logger.error(
                "Qlib scoped inference resolve failed: portfolio_id=%s, error=%s",
                ref.get("portfolio_id"),
                exc,
                exc_info=True,
            )
            skipped.append({"portfolio_id": ref.get("portfolio_id"), "reason": str(exc)})

    refresh_result: dict[str, Any] = {"status": "skipped", "reason": "refresh_disabled"}
    refresh_requested = bool(refresh_data and scoped_codes and resolved_scopes)
    if refresh_requested:
        try:
            refresh_result = refresh_runtime_for_codes(
                target_date=target_trade_date,
                stock_codes=scoped_codes,
                universe_id="scoped_portfolios",
                lookback_days=lookback_days,
            )
        except Exception as exc:
            failed_count += 1
            logger.error(
                "Qlib scoped data refresh failed, continue queueing inference: %s",
                exc,
                exc_info=True,
            )
            refresh_result = {
                "status": "failed",
                "error": str(exc),
                "stock_count": len(scoped_codes),
            }

    for ref, scope in resolved_scopes:
        try:
            task = queue_prediction(
                scope.universe_id,
                target_trade_date.isoformat(),
                top_n,
                scope_payload=scope.to_dict(),
            )
            queued.append(
                {
                    "portfolio_id": ref["portfolio_id"],
                    "user_id": ref["user_id"],
                    "scope_hash": scope.scope_hash,
                    "universe_id": scope.universe_id,
                    "pool_size": scope.pool_size,
                    "task_id": task.id,
                }
            )
        except Exception as exc:
            failed_count += 1
            logger.error(
                "Qlib scoped inference queue failed: portfolio_id=%s, error=%s",
                ref.get("portfolio_id"),
                exc,
                exc_info=True,
            )
            skipped.append({"portfolio_id": ref.get("portfolio_id"), "reason": str(exc)})

    status = "queued" if queued else "skipped"
    reason = None
    if status == "skipped":
        if fresh_cache_count and not resolved_scopes:
            reason = "all_scopes_fresh"
        elif not resolved_scopes:
            reason = "no_scopes_to_queue"

    requested_count = len(portfolio_refs) + (1 if refresh_requested else 0)
    return {
        "status": status,
        "reason": reason,
        "trade_date": target_trade_date.isoformat(),
        "top_n": top_n,
        "portfolio_count": len(portfolio_refs),
        "scope_count": len(seen_scope_keys),
        "scoped_stock_count": len(scoped_codes),
        "refresh_result": refresh_result,
        "queued_count": len(queued),
        "fresh_cache_count": fresh_cache_count,
        "skipped_count": len(skipped),
        "queued": queued,
        "skipped": skipped,
        "failed_count": failed_count,
        **_outcomes.scoped_work_outcome(
            requested=requested_count,
            failed=failed_count,
            stored=len(queued),
            no_work=not queued,
        ),
    }


__all__ = ["run_daily_inference", "run_scoped_inference"]
