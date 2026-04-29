"""Use cases for Alpha/Qlib operational pages and APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils import timezone

from apps.alpha.application.ops_locks import (
    acquire_dashboard_alpha_refresh_pending_lock,
    acquire_inference_batch_pending_lock,
    acquire_qlib_data_refresh_pending_lock,
    build_dashboard_alpha_refresh_lock_key,
    build_dashboard_alpha_refresh_metadata,
    build_inference_batch_lock_key,
    build_qlib_data_refresh_lock_key,
    promote_dashboard_alpha_refresh_task_lock,
    promote_inference_batch_task_lock,
    promote_qlib_data_refresh_task_lock,
    release_dashboard_alpha_refresh_lock,
    release_inference_batch_lock,
    release_qlib_data_refresh_lock,
    resolve_dashboard_alpha_refresh_lock,
    resolve_inference_batch_lock,
    resolve_qlib_data_refresh_lock,
)
from apps.alpha.application.ops_services import (
    AlphaOpsOverviewQueryService,
    QlibDataOpsOverviewQueryService,
)
from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver
from apps.alpha.application.repository_provider import get_alpha_pool_data_repository
from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus


def _build_conflict_payload(
    *,
    error: str,
    lock_meta: dict[str, Any],
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
        "task_id": lock_meta.get("task_id"),
        "task_state": lock_meta.get("task_state"),
        "lock_mode": lock_meta.get("mode"),
    }
    payload.update(lock_meta)
    if extra_payload:
        payload.update(extra_payload)
    return payload


def _record_pending_task(
    *,
    task_id: str,
    task_name: str,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> None:
    """Persist one queued task so ops pages can show it before worker pickup."""
    RecordTaskExecutionUseCase(repository=get_task_record_repository()).execute(
        TaskExecutionRecord(
            task_id=task_id,
            task_name=task_name,
            status=TaskStatus.PENDING,
            args=args,
            kwargs=kwargs or {},
            started_at=None,
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue=None,
            worker=None,
        )
    )


class GetAlphaInferenceOpsOverviewUseCase:
    """Return overview data for the Alpha inference ops page."""

    def execute(self) -> dict[str, Any]:
        return AlphaOpsOverviewQueryService().build()


class GetQlibDataOpsOverviewUseCase:
    """Return overview data for the Qlib data ops page."""

    def execute(self) -> dict[str, Any]:
        return QlibDataOpsOverviewQueryService().build()


class TriggerGeneralInferenceUseCase:
    """Queue one general Alpha inference task for the ops page."""

    def execute(self, *, trade_date: date, top_n: int, universe_id: str) -> dict[str, Any]:
        from apps.alpha.application.tasks import qlib_predict_scores

        lock_key = build_dashboard_alpha_refresh_lock_key(
            alpha_scope="general",
            target_date=trade_date,
            top_n=top_n,
            raw_universe_id=universe_id,
        )
        metadata = build_dashboard_alpha_refresh_metadata(
            alpha_scope="general",
            target_date=trade_date,
            top_n=top_n,
            universe_id=universe_id,
            portfolio_id=None,
            pool_mode="general",
            scope_hash=None,
        )
        existing = resolve_dashboard_alpha_refresh_lock(lock_key)
        if existing is not None:
            return _build_conflict_payload(
                error="相同 scope/date/top_n 的 Alpha 推理仍在进行中。",
                lock_meta=existing,
            )
        if not acquire_dashboard_alpha_refresh_pending_lock(lock_key, meta=metadata):
            existing = resolve_dashboard_alpha_refresh_lock(lock_key) or metadata
            return _build_conflict_payload(
                error="相同 scope/date/top_n 的 Alpha 推理仍在进行中。",
                lock_meta=existing,
            )
        try:
            task = qlib_predict_scores.delay(universe_id, trade_date.isoformat(), top_n)
            promote_dashboard_alpha_refresh_task_lock(lock_key, task_id=task.id)
            _record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(universe_id, trade_date.isoformat(), top_n),
            )
        except Exception:
            release_dashboard_alpha_refresh_lock(lock_key)
            raise
        return {
            "success": True,
            "task_id": task.id,
            "message": "已投递通用 Alpha 推理任务。",
            **metadata,
        }


class TriggerScopedInferenceUseCase:
    """Queue one scoped Alpha inference task for the ops page."""

    def execute(
        self,
        *,
        actor_user_id: int,
        trade_date: date,
        top_n: int,
        portfolio_id: int,
        pool_mode: str,
    ) -> dict[str, Any]:
        from apps.alpha.application.tasks import qlib_predict_scores

        resolved_pool = PortfolioAlphaPoolResolver().resolve(
            user_id=actor_user_id,
            portfolio_id=portfolio_id,
            trade_date=trade_date,
            pool_mode=pool_mode,
        )
        scope = resolved_pool.scope
        metadata = build_dashboard_alpha_refresh_metadata(
            alpha_scope="portfolio",
            target_date=trade_date,
            top_n=top_n,
            universe_id=scope.universe_id,
            portfolio_id=resolved_pool.portfolio_id,
            pool_mode=scope.pool_mode,
            scope_hash=scope.scope_hash,
        )
        lock_key = build_dashboard_alpha_refresh_lock_key(
            alpha_scope="portfolio",
            target_date=trade_date,
            top_n=top_n,
            raw_universe_id=scope.universe_id,
            scope_hash=scope.scope_hash,
        )
        existing = resolve_dashboard_alpha_refresh_lock(lock_key)
        if existing is not None:
            return _build_conflict_payload(
                error="相同 scope/date/top_n 的 scoped Alpha 推理仍在进行中。",
                lock_meta=existing,
            )
        if not acquire_dashboard_alpha_refresh_pending_lock(lock_key, meta=metadata):
            existing = resolve_dashboard_alpha_refresh_lock(lock_key) or metadata
            return _build_conflict_payload(
                error="相同 scope/date/top_n 的 scoped Alpha 推理仍在进行中。",
                lock_meta=existing,
            )
        try:
            task = qlib_predict_scores.delay(
                scope.universe_id,
                trade_date.isoformat(),
                top_n,
                scope_payload=scope.to_dict(),
            )
            promote_dashboard_alpha_refresh_task_lock(lock_key, task_id=task.id)
            _record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_predict_scores",
                args=(scope.universe_id, trade_date.isoformat(), top_n),
                kwargs={"scope_payload": scope.to_dict()},
            )
        except Exception:
            release_dashboard_alpha_refresh_lock(lock_key)
            raise
        return {
            "success": True,
            "task_id": task.id,
            "message": "已投递账户专属 scoped Alpha 推理任务。",
            **metadata,
            "scope_label": scope.display_label,
        }


class TriggerScopedBatchInferenceUseCase:
    """Queue the daily scoped batch inference task from the ops page."""

    def execute(self, *, top_n: int, pool_mode: str, portfolio_limit: int = 0) -> dict[str, Any]:
        from apps.alpha.application.tasks import qlib_daily_scoped_inference

        trade_date = timezone.localdate()
        metadata = {
            "lock_type": "alpha_inference_batch",
            "mode": "daily_scoped_batch",
            "requested_trade_date": trade_date.isoformat(),
            "top_n": top_n,
            "pool_mode": pool_mode,
            "portfolio_limit": portfolio_limit,
        }
        lock_key = build_inference_batch_lock_key(
            mode="daily_scoped_batch",
            target_date=trade_date,
            top_n=top_n,
            descriptor=f"{pool_mode}:{portfolio_limit}",
        )
        existing = resolve_inference_batch_lock(lock_key)
        if existing is not None:
            return _build_conflict_payload(
                error="同一批量 scoped Alpha 推理任务仍在进行中。",
                lock_meta=existing,
            )
        if not acquire_inference_batch_pending_lock(lock_key, meta=metadata):
            existing = resolve_inference_batch_lock(lock_key) or metadata
            return _build_conflict_payload(
                error="同一批量 scoped Alpha 推理任务仍在进行中。",
                lock_meta=existing,
            )
        try:
            task = qlib_daily_scoped_inference.delay(
                top_n=top_n,
                portfolio_limit=portfolio_limit,
                pool_mode=pool_mode,
            )
            promote_inference_batch_task_lock(lock_key, task_id=task.id)
            _record_pending_task(
                task_id=task.id,
                task_name="alpha.qlib_daily_scoped_inference",
                kwargs={
                    "top_n": top_n,
                    "portfolio_limit": portfolio_limit,
                    "pool_mode": pool_mode,
                },
            )
        except Exception:
            release_inference_batch_lock(lock_key)
            raise
        return {
            "success": True,
            "task_id": task.id,
            "message": "已投递 active portfolios 的批量 scoped Alpha 推理任务。",
            **metadata,
        }


class TriggerQlibUniverseRefreshUseCase:
    """Queue one qlib universe refresh task from the ops page."""

    def execute(
        self,
        *,
        target_date: date,
        lookback_days: int,
        universes: list[str],
    ) -> dict[str, Any]:
        from apps.alpha.application.tasks import qlib_refresh_runtime_data_task

        normalized_universes = [str(item).strip().lower() for item in universes if str(item).strip()]
        descriptor = ",".join(sorted(normalized_universes)) or "csi300"
        metadata = {
            "lock_type": "qlib_data_refresh",
            "mode": "universes",
            "requested_target_date": target_date.isoformat(),
            "lookback_days": lookback_days,
            "universes": normalized_universes or ["csi300"],
        }
        lock_key = build_qlib_data_refresh_lock_key(
            mode="universes",
            target_date=target_date,
            lookback_days=lookback_days,
            descriptor=descriptor,
        )
        existing = resolve_qlib_data_refresh_lock(lock_key)
        if existing is not None:
            return _build_conflict_payload(
                error="相同日期和 universe 组合的 Qlib 数据刷新仍在进行中。",
                lock_meta=existing,
            )
        if not acquire_qlib_data_refresh_pending_lock(lock_key, meta=metadata):
            existing = resolve_qlib_data_refresh_lock(lock_key) or metadata
            return _build_conflict_payload(
                error="相同日期和 universe 组合的 Qlib 数据刷新仍在进行中。",
                lock_meta=existing,
            )
        try:
            task = qlib_refresh_runtime_data_task.delay(
                target_date=target_date.isoformat(),
                universes=normalized_universes or ["csi300"],
                lookback_days=lookback_days,
            )
            promote_qlib_data_refresh_task_lock(lock_key, task_id=task.id)
            _record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_refresh_runtime_data_task",
                kwargs={
                    "target_date": target_date.isoformat(),
                    "universes": normalized_universes or ["csi300"],
                    "lookback_days": lookback_days,
                },
            )
        except Exception:
            release_qlib_data_refresh_lock(lock_key)
            raise
        return {
            "success": True,
            "task_id": task.id,
            "message": "已投递 Qlib universe 数据刷新任务。",
            **metadata,
        }


class TriggerQlibScopedCodesRefreshUseCase:
    """Queue one qlib scoped-codes refresh task from the ops page."""

    def execute(
        self,
        *,
        target_date: date,
        lookback_days: int,
        portfolio_ids: list[int],
        all_active_portfolios: bool,
        pool_mode: str,
    ) -> dict[str, Any]:
        from apps.alpha.application.tasks import qlib_refresh_runtime_data_for_codes_task

        if not all_active_portfolios and not portfolio_ids:
            raise ValueError("scoped_codes 刷新必须提供 portfolio_ids 或 all_active_portfolios=1")

        descriptor = "all_active" if all_active_portfolios else ",".join(str(pid) for pid in sorted(portfolio_ids))
        metadata = {
            "lock_type": "qlib_data_refresh",
            "mode": "scoped_codes",
            "requested_target_date": target_date.isoformat(),
            "lookback_days": lookback_days,
            "portfolio_ids": sorted(portfolio_ids),
            "all_active_portfolios": all_active_portfolios,
            "pool_mode": pool_mode,
        }
        lock_key = build_qlib_data_refresh_lock_key(
            mode="scoped_codes",
            target_date=target_date,
            lookback_days=lookback_days,
            descriptor=f"{descriptor}:{pool_mode}",
        )
        existing = resolve_qlib_data_refresh_lock(lock_key)
        if existing is not None:
            return _build_conflict_payload(
                error="相同 scoped portfolio 范围的 Qlib 数据刷新仍在进行中。",
                lock_meta=existing,
            )
        if not acquire_qlib_data_refresh_pending_lock(lock_key, meta=metadata):
            existing = resolve_qlib_data_refresh_lock(lock_key) or metadata
            return _build_conflict_payload(
                error="相同 scoped portfolio 范围的 Qlib 数据刷新仍在进行中。",
                lock_meta=existing,
            )
        try:
            task = qlib_refresh_runtime_data_for_codes_task.delay(
                target_date=target_date.isoformat(),
                portfolio_ids=sorted(portfolio_ids),
                all_active_portfolios=all_active_portfolios,
                pool_mode=pool_mode,
                lookback_days=lookback_days,
            )
            promote_qlib_data_refresh_task_lock(lock_key, task_id=task.id)
            _record_pending_task(
                task_id=task.id,
                task_name="apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task",
                kwargs={
                    "target_date": target_date.isoformat(),
                    "portfolio_ids": sorted(portfolio_ids),
                    "all_active_portfolios": all_active_portfolios,
                    "pool_mode": pool_mode,
                    "lookback_days": lookback_days,
                },
            )
        except Exception:
            release_qlib_data_refresh_lock(lock_key)
            raise
        return {
            "success": True,
            "task_id": task.id,
            "message": "已投递 Qlib scoped codes 数据刷新任务。",
            **metadata,
        }


def collect_portfolio_refs_for_refresh(
    *,
    portfolio_ids: list[int],
    all_active_portfolios: bool,
) -> list[dict[str, Any]]:
    """Resolve active portfolio references for scoped qlib data refresh tasks."""
    refs = get_alpha_pool_data_repository().list_active_portfolio_refs(limit=0)
    if all_active_portfolios:
        return refs
    requested = set(portfolio_ids)
    return [ref for ref in refs if int(ref["portfolio_id"]) in requested]
