"""Application services for Alpha/Qlib operational pages."""

from __future__ import annotations

import ast
import logging
from datetime import date
from typing import Any

from django.utils import timezone

from apps.alpha.application.repository_provider import (
    TushareQlibBuilder,
    get_alpha_alert_repository,
    get_alpha_score_cache_repository,
    get_qlib_model_registry_repository,
    inspect_latest_trade_date,
)
from apps.alpha.domain.entities import normalize_stock_code
from apps.task_monitor.application.provider import (
    get_celery_health_checker,
    get_task_record_repository,
)
from core.integration.runtime_settings import get_runtime_qlib_config

logger = logging.getLogger(__name__)

INFERENCE_TASK_NAMES = (
    "apps.alpha.application.tasks.qlib_predict_scores",
    "alpha.qlib_daily_inference",
    "apps.alpha.application.tasks.qlib_daily_inference",
    "alpha.qlib_daily_scoped_inference",
    "apps.alpha.application.tasks.qlib_daily_scoped_inference",
)

QLIB_DATA_REFRESH_TASK_NAMES = (
    "apps.alpha.application.tasks.qlib_refresh_runtime_data_task",
    "apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task",
)


def _parse_universe_list(raw_universes: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize universe input from forms/tasks."""
    if raw_universes is None:
        return ["csi300"]
    if isinstance(raw_universes, str):
        return [item.strip().lower() for item in raw_universes.split(",") if item.strip()]
    return [str(item).strip().lower() for item in raw_universes if str(item).strip()]


def _serialize_task_result(raw_value: str | None) -> dict[str, Any] | str | None:
    """Parse task-monitor result payloads stored as stringified dicts when possible."""
    if not raw_value:
        return None
    try:
        parsed = ast.literal_eval(raw_value)
    except (ValueError, SyntaxError):
        return raw_value
    return parsed


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class QlibRuntimeDataRefreshService:
    """Refresh local qlib runtime data for universes or explicit code scopes."""

    def get_runtime_config(self) -> dict[str, Any]:
        """Return runtime qlib config through the integration bridge."""

        return get_runtime_qlib_config()

    def refresh_universes(
        self,
        *,
        target_date: date,
        universes: str | list[str] | tuple[str, ...] | None = None,
        lookback_days: int = 400,
    ) -> dict[str, Any]:
        """Refresh local qlib data for named universes."""
        qlib_config = self.get_runtime_config()
        if not qlib_config.get("enabled"):
            return {"status": "skipped", "reason": "qlib_disabled"}

        provider_uri = qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data")
        normalized_universes = _parse_universe_list(universes) or ["csi300"]
        summary = TushareQlibBuilder(provider_uri).build_recent_data(
            target_date=target_date,
            universes=normalized_universes,
            lookback_days=lookback_days,
        )
        return {
            "status": "success",
            "provider_uri": provider_uri,
            "universes": normalized_universes,
            "requested_target_date": summary.requested_target_date.isoformat(),
            "effective_target_date": _to_iso(summary.effective_target_date),
            "latest_local_date_before": _to_iso(summary.latest_local_date_before),
            "latest_local_date_after": _to_iso(summary.latest_local_date_after),
            "calendar_days_written": summary.calendar_days_written,
            "instrument_files_written": summary.instrument_files_written,
            "feature_series_written": summary.feature_series_written,
            "stock_count": summary.stock_count,
            "universe_count": summary.universe_count,
            "warning_messages": list(summary.warning_messages),
        }

    def refresh_codes(
        self,
        *,
        target_date: date,
        stock_codes: list[str] | tuple[str, ...] | set[str],
        universe_id: str = "scoped_portfolios",
        lookback_days: int = 120,
    ) -> dict[str, Any]:
        """Refresh local qlib data for one explicit stock scope."""
        qlib_config = self.get_runtime_config()
        if not qlib_config.get("enabled"):
            return {"status": "skipped", "reason": "qlib_disabled"}

        provider_uri = qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data")
        normalized_codes = sorted(
            {
                normalize_stock_code(code)
                for code in stock_codes
                if normalize_stock_code(code)
            }
        )
        if not normalized_codes:
            return {
                "status": "skipped",
                "reason": "empty_stock_scope",
                "stock_count": 0,
            }

        summary = TushareQlibBuilder(provider_uri).build_recent_data_for_codes(
            target_date=target_date,
            stock_codes=normalized_codes,
            universe_id=universe_id,
            lookback_days=lookback_days,
        )
        return {
            "status": "success",
            "provider_uri": provider_uri,
            "universe_id": universe_id,
            "requested_target_date": summary.requested_target_date.isoformat(),
            "effective_target_date": _to_iso(summary.effective_target_date),
            "latest_local_date_before": _to_iso(summary.latest_local_date_before),
            "latest_local_date_after": _to_iso(summary.latest_local_date_after),
            "calendar_days_written": summary.calendar_days_written,
            "instrument_files_written": summary.instrument_files_written,
            "feature_series_written": summary.feature_series_written,
            "stock_count": summary.stock_count,
            "warning_messages": list(summary.warning_messages),
        }


class AlphaOpsOverviewQueryService:
    """Build the aggregated payload for the Alpha inference ops page."""

    def build(self) -> dict[str, Any]:
        """Return the Alpha inference ops overview payload."""
        from apps.alpha.application.ops_locks import list_active_dashboard_alpha_refresh_locks

        qlib_config = get_runtime_qlib_config()
        active_model = get_qlib_model_registry_repository().get_active_model()
        return {
            "active_model": self._serialize_active_model(active_model),
            "qlib_runtime": qlib_config,
            "celery_health": self._get_celery_health(),
            "dashboard_refresh_locks": list_active_dashboard_alpha_refresh_locks(),
            "recent_tasks": self._list_recent_tasks(INFERENCE_TASK_NAMES, limit=12),
            "recent_caches": self._list_recent_caches(limit=12),
            "recent_alerts": self._list_recent_alerts(limit=8),
        }

    def _serialize_active_model(self, active_model: Any | None) -> dict[str, Any] | None:
        if active_model is None:
            return None
        return {
            "model_name": active_model.model_name,
            "artifact_hash": active_model.artifact_hash,
            "model_type": active_model.model_type,
            "universe": active_model.universe,
            "feature_set_id": active_model.feature_set_id,
            "label_id": active_model.label_id,
            "data_version": active_model.data_version,
            "ic": active_model.ic,
            "icir": active_model.icir,
            "rank_ic": active_model.rank_ic,
            "activated_at": _to_iso(active_model.activated_at),
            "activated_by": active_model.activated_by,
            "admin_url": "/admin/alpha/qlibmodelregistrymodel/",
        }

    def _get_celery_health(self) -> dict[str, Any]:
        try:
            return get_celery_health_checker().check_health().to_dict()
        except Exception as exc:
            logger.warning("Failed to inspect celery health for alpha ops: %s", exc)
            return {
                "is_healthy": False,
                "broker_reachable": False,
                "backend_reachable": False,
                "active_workers": [],
                "active_tasks_count": 0,
                "pending_tasks_count": 0,
                "scheduled_tasks_count": 0,
                "last_check": timezone.now().isoformat(),
                "error": str(exc),
            }

    def _list_recent_tasks(self, task_names: tuple[str, ...], *, limit: int) -> list[dict[str, Any]]:
        records = []
        repository = get_task_record_repository()
        for task_name in task_names:
            records.extend(repository.list_by_task_name(task_name, limit=limit))

        deduped: dict[str, Any] = {}
        for record in records:
            deduped[record.task_id] = record

        ordered = sorted(
            deduped.values(),
            key=lambda item: item.started_at or item.finished_at or timezone.now(),
            reverse=True,
        )[:limit]
        return [
            {
                "task_id": record.task_id,
                "task_name": record.task_name,
                "status": record.status.value,
                "started_at": _to_iso(record.started_at),
                "finished_at": _to_iso(record.finished_at),
                "runtime_seconds": record.runtime_seconds,
                "queue": record.queue,
                "worker": record.worker,
                "exception": record.exception,
                "result": _serialize_task_result(record.result),
            }
            for record in ordered
        ]

    def _list_recent_caches(self, *, limit: int) -> list[dict[str, Any]]:
        rows = get_alpha_score_cache_repository().list_recent_qlib_caches(limit=limit)
        return [
            {
                "id": row.id,
                "universe_id": row.universe_id,
                "scope_hash": row.scope_hash,
                "scope_label": row.scope_label,
                "intended_trade_date": row.intended_trade_date.isoformat(),
                "asof_date": row.asof_date.isoformat(),
                "status": row.status,
                "model_artifact_hash": row.model_artifact_hash,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "score_count": len(row.scores or []),
            }
            for row in rows
        ]

    def _list_recent_alerts(self, *, limit: int) -> list[dict[str, Any]]:
        rows = get_alpha_alert_repository().list_recent_alerts(limit=limit)
        return [
            {
                "id": row.id,
                "alert_type": row.alert_type,
                "severity": row.severity,
                "title": row.title,
                "message": row.message,
                "is_resolved": row.is_resolved,
                "created_at": row.created_at.isoformat(),
                "resolved_at": _to_iso(row.resolved_at),
            }
            for row in rows
        ]


class QlibDataOpsOverviewQueryService:
    """Build the aggregated payload for the Qlib data ops page."""

    def build(self) -> dict[str, Any]:
        """Return the Qlib data ops overview payload."""
        runtime_config = get_runtime_qlib_config()
        latest_local_trade_date = None
        local_data_error = None
        provider_uri = runtime_config.get("provider_uri")
        if runtime_config.get("enabled") and provider_uri:
            try:
                latest_local_trade_date = inspect_latest_trade_date(provider_uri)
            except Exception as exc:
                local_data_error = str(exc)
                logger.warning("Failed to inspect qlib latest local date: %s", exc)

        recent_tasks = AlphaOpsOverviewQueryService()._list_recent_tasks(
            QLIB_DATA_REFRESH_TASK_NAMES,
            limit=10,
        )
        latest_build_summary = self._extract_latest_build_summary(recent_tasks)
        lag_days = None
        if latest_local_trade_date is not None:
            lag_days = max((timezone.localdate() - latest_local_trade_date).days, 0)
        return {
            "qlib_runtime": runtime_config,
            "local_data_status": {
                "latest_trade_date": _to_iso(latest_local_trade_date),
                "lag_days": lag_days,
                "local_data_error": local_data_error,
                "supported_universes": ["csi300", "csi500", "sse50", "csi1000"],
            },
            "recent_tasks": recent_tasks,
            "latest_build_summary": latest_build_summary,
        }

    def _extract_latest_build_summary(self, recent_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        for task in recent_tasks:
            result = task.get("result")
            if not isinstance(result, dict):
                continue
            if "summary" in result and isinstance(result["summary"], dict):
                return result["summary"]
            if "requested_target_date" in result:
                return result
        return None
