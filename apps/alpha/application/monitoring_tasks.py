"""Celery tasks and helpers for observable Alpha runtime health."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from math import isfinite
from typing import Any, TypedDict

from celery import current_app
from django.utils import timezone

from apps.alpha.application.repository_provider import (
    calculate_rolling_metrics,
    get_alpha_runtime_alert_manager,
    get_alpha_score_cache_repository,
    get_qlib_model_registry_repository,
)
from apps.alpha.domain.entities import AlphaResult
from shared.infrastructure.celery_typing import typed_shared_task
from shared.infrastructure.metrics import AlphaMetrics, get_alpha_metrics

logger = logging.getLogger(__name__)

_PROVIDERS = ("qlib", "cache", "simple", "etf")
_QLIB_QUEUES = ("qlib_infer", "qlib_train")
_IC_HISTORY_WINDOW = 20

_cache_repository = get_alpha_score_cache_repository()
_registry_repository = get_qlib_model_registry_repository()


class ProviderDailyStats(TypedDict):
    """Daily cache counters for one Alpha provider."""

    count: int
    available: int


def _positive_int(value: object) -> int | None:
    """Return a strictly positive integer without accepting booleans."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _resolve_universe_count(metadata: object) -> int | None:
    """Resolve a coverage denominator from persisted, auditable metadata."""

    if not isinstance(metadata, Mapping):
        return None
    for key in ("universe_count", "pool_size"):
        count = _positive_int(metadata.get(key))
        if count is not None:
            return count
    nested_scope = metadata.get("scope_metadata")
    if isinstance(nested_scope, Mapping):
        return _positive_int(nested_scope.get("pool_size"))
    return None


def _resolve_cache_universe_count(cache: object) -> int | None:
    """Resolve the universe size recorded with one cache row."""

    scope_count = _resolve_universe_count(getattr(cache, "scope_metadata", None))
    if scope_count is not None:
        return scope_count
    return _resolve_universe_count(getattr(cache, "metrics_snapshot", None))


def _score_count(scores: object) -> int:
    """Count unique scored instruments where score payloads expose codes."""

    if not isinstance(scores, list):
        return 0
    codes = {
        str(item.get("code")).strip()
        for item in scores
        if isinstance(item, Mapping) and str(item.get("code") or "").strip()
    }
    return len(codes) if codes else len(scores)


def _record_coverage_if_resolvable(
    metrics: AlphaMetrics,
    *,
    scored_count: int,
    universe_count: int | None,
) -> str:
    """Record valid coverage or expose why the metric is unavailable."""

    if universe_count is None:
        return "unavailable"
    if scored_count < 0 or scored_count > universe_count:
        logger.warning(
            "Alpha 覆盖率样本无效: scored_count=%s, universe_count=%s",
            scored_count,
            universe_count,
        )
        return "invalid"
    metrics.record_coverage(scored_count, universe_count)
    return "available"


@typed_shared_task(name="alpha.monitor.evaluate_alerts")
def evaluate_alerts() -> dict[str, Any]:
    """Evaluate all configured Alpha alert rules."""

    alert_manager = get_alpha_runtime_alert_manager()
    alerts = alert_manager.evaluate_all()
    timestamp = timezone.now().isoformat()
    if alerts:
        logger.warning("=== Alpha 告警 (%s 条) ===", len(alerts))
        for alert in alerts:
            logger.warning("%s", alert)
        return {
            "status": "alert",
            "count": len(alerts),
            "alerts": alerts,
            "timestamp": timestamp,
        }
    return {"status": "ok", "count": 0, "timestamp": timestamp}


@typed_shared_task(name="alpha.monitor.update_provider_metrics")
def update_provider_metrics() -> dict[str, Any]:
    """Update provider success, staleness, and evidence-backed coverage metrics."""

    metrics = get_alpha_metrics()
    since = timezone.now() - timedelta(hours=1)
    for provider in _PROVIDERS:
        recent_caches = _cache_repository.list_recent_provider_caches(
            provider=provider,
            since=since,
        )
        if not recent_caches:
            continue

        total = len(recent_caches)
        available = sum(cache.status == "available" for cache in recent_caches)
        success_rate = available / total
        metrics.registry.set_gauge(
            "alpha_provider_success_rate",
            success_rate,
            labels={"provider": provider},
        )
        staleness_values = [float(cache.get_staleness_days()) for cache in recent_caches]
        avg_staleness = sum(staleness_values) / total
        metrics.registry.set_gauge(
            "alpha_provider_staleness_days",
            avg_staleness,
            labels={"provider": provider},
        )

    latest_cache = _cache_repository.get_latest_cache_for_universe(
        universe_id="csi300",
        since=timezone.now() - timedelta(days=1),
    )
    coverage_status = "unavailable"
    coverage_universe_count: int | None = None
    if latest_cache is not None:
        scored_count = _score_count(latest_cache.scores)
        coverage_universe_count = _resolve_cache_universe_count(latest_cache)
        coverage_status = _record_coverage_if_resolvable(
            metrics,
            scored_count=scored_count,
            universe_count=coverage_universe_count,
        )

    metrics.log_metrics()
    return {
        "status": "success",
        "coverage_status": coverage_status,
        "coverage_universe_count": coverage_universe_count,
        "timestamp": timezone.now().isoformat(),
    }


@typed_shared_task(name="alpha.monitor.calculate_ic_drift")
def calculate_ic_drift() -> dict[str, Any]:
    """Compare the current rolling IC with up to 20 prior observations."""

    metrics = get_alpha_metrics()
    active_model = _registry_repository.get_active_model()
    if not active_model:
        logger.warning("没有激活的模型，跳过 IC 漂移计算")
        return {"status": "skipped", "reason": "no_active_model"}

    caches = _cache_repository.list_caches_for_model(
        model_artifact_hash=active_model.artifact_hash,
        provider_source="qlib",
    )
    if len(caches) < _IC_HISTORY_WINDOW:
        logger.warning("缓存数据不足 (%s 条)，跳过 IC 漂移计算", len(caches))
        return {"status": "skipped", "reason": "insufficient_data"}

    rolling = calculate_rolling_metrics(
        model_artifact_hash=active_model.artifact_hash,
        universe_id=caches[0].universe_id,
        start_date=caches[0].intended_trade_date,
        end_date=caches[-1].intended_trade_date,
        window=_IC_HISTORY_WINDOW,
    )
    finite_ics = [float(row.ic) for row in rolling if isfinite(float(row.ic))]
    if len(finite_ics) < 2:
        logger.warning("滚动 IC 缺少当前值之前的有效历史，标记为 skipped")
        return {"status": "skipped", "reason": "insufficient_rolling_ic_history"}

    current_ic = finite_ics[-1]
    historical_ics = finite_ics[-(_IC_HISTORY_WINDOW + 1) : -1]
    historical_mean = sum(historical_ics) / len(historical_ics)
    drift = current_ic - historical_mean
    metrics.record_ic_metrics(
        current_ic,
        historical_ics,
        window=_IC_HISTORY_WINDOW,
    )
    logger.info(
        "IC 漂移计算完成: 当前 IC=%.4f, 历史均值=%.4f",
        current_ic,
        historical_mean,
    )
    return {
        "status": "success",
        "current_ic": current_ic,
        "historical_mean": historical_mean,
        "drift": drift,
        "history_count": len(historical_ics),
        "timestamp": timezone.now().isoformat(),
    }


def _queue_name(task: object) -> str:
    """Extract a task routing key from Celery inspect payloads."""

    if not isinstance(task, Mapping):
        return "default"
    delivery_info = task.get("delivery_info")
    if not isinstance(delivery_info, Mapping):
        return "default"
    routing_key = delivery_info.get("routing_key")
    return str(routing_key or "default")


@typed_shared_task(name="alpha.monitor.check_queue_lag")
def check_queue_lag() -> dict[str, Any]:
    """Measure reserved Qlib tasks without converting inspect failure to zero lag."""

    metrics = get_alpha_metrics()
    try:
        inspector = current_app.control.inspect()
        reserved = inspector.reserved()
    except Exception as exc:
        logger.warning("无法获取 Celery reserved 队列状态: %s", exc)
        return {
            "status": "unavailable",
            "reason": "celery_inspect_failed",
            "timestamp": timezone.now().isoformat(),
        }

    if not isinstance(reserved, Mapping) or not reserved:
        logger.warning("Celery inspect 没有返回 worker reserved 状态")
        return {
            "status": "unavailable",
            "reason": "no_worker_response",
            "timestamp": timezone.now().isoformat(),
        }

    queue_tasks: dict[str, int] = {}
    for tasks in reserved.values():
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            queue = _queue_name(task)
            queue_tasks[queue] = queue_tasks.get(queue, 0) + 1

    for queue_name in _QLIB_QUEUES:
        count = queue_tasks.get(queue_name, 0)
        metrics.record_queue_lag(queue_name, count)
    return {
        "status": "success",
        "queues": queue_tasks,
        "timestamp": timezone.now().isoformat(),
    }


@typed_shared_task(name="alpha.monitor.generate_daily_report")
def generate_daily_report() -> dict[str, Any]:
    """Generate a daily report from persisted cache and metric evidence."""

    metrics = get_alpha_metrics()
    today = timezone.now().date()
    today_caches = _cache_repository.list_today_cache_rows(today)
    provider_stats: dict[str, ProviderDailyStats] = {}
    for cache in today_caches:
        provider = str(cache["provider_source"])
        stats = provider_stats.setdefault(provider, {"count": 0, "available": 0})
        stats["count"] += 1
        if cache["status"] == "available":
            stats["available"] += 1

    model_activations = _registry_repository.count_activations_on(today)
    report: dict[str, Any] = {
        "date": today.isoformat(),
        "cache_records": len(today_caches),
        "provider_stats": provider_stats,
        "model_activations": model_activations,
        "metrics_snapshot": metrics.get_metrics_json(),
    }
    logger.info("=== Alpha 每日监控报告 ===")
    for provider, stats in provider_stats.items():
        success_rate = stats["available"] / stats["count"] if stats["count"] else 0.0
        logger.info(
            "%s: %s 条, 成功率 %.2f%%",
            provider,
            stats["count"],
            success_rate * 100,
        )
    return report


@typed_shared_task(name="alpha.monitor.cleanup_old_metrics")
def cleanup_old_metrics(days: int = 30) -> dict[str, Any]:
    """Archive old monitoring summaries before deleting their cache rows."""

    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("监控数据保留天数必须是正整数")
    cutoff_date = timezone.now().date() - timedelta(days=days)
    archive_result = _cache_repository.archive_before(cutoff_date)
    deleted_count = _cache_repository.cleanup_before(cutoff_date)
    logger.info(
        "归档 %s 条 Alpha 监控摘要，清理了 %s 条过期缓存记录",
        archive_result.get("archived_count", 0),
        deleted_count,
    )
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "archive": archive_result,
        "cutoff_date": cutoff_date.isoformat(),
    }


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.evaluate_alerts")
def evaluate_alerts_legacy() -> dict[str, Any]:
    """Run the canonical alert task through its legacy task name."""

    return evaluate_alerts.run()


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.update_provider_metrics")
def update_provider_metrics_legacy() -> dict[str, Any]:
    """Run the canonical provider metric task through its legacy task name."""

    return update_provider_metrics.run()


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.check_queue_lag")
def check_queue_lag_legacy() -> dict[str, Any]:
    """Run the canonical queue task through its legacy task name."""

    return check_queue_lag.run()


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.calculate_ic_drift")
def calculate_ic_drift_legacy() -> dict[str, Any]:
    """Run the canonical IC drift task through its legacy task name."""

    return calculate_ic_drift.run()


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.generate_daily_report")
def generate_daily_report_legacy() -> dict[str, Any]:
    """Run the canonical report task through its legacy task name."""

    return generate_daily_report.run()


@typed_shared_task(name="apps.alpha.application.monitoring_tasks.cleanup_old_metrics")
def cleanup_old_metrics_legacy(days: int = 30) -> dict[str, Any]:
    """Run the canonical cleanup task through its legacy task name."""

    return cleanup_old_metrics.run(days=days)


def update_metrics_from_alpha_result(result: AlphaResult, provider_name: str) -> None:
    """Record metrics from one Alpha result without inventing a universe size."""

    metrics = get_alpha_metrics()
    metrics.record_provider_call(
        provider_name=provider_name,
        success=result.success,
        latency_ms=result.latency_ms or 0,
        staleness_days=result.staleness_days,
    )
    if result.scores:
        _record_coverage_if_resolvable(
            metrics,
            scored_count=len({score.code for score in result.scores}),
            universe_count=_resolve_universe_count(result.metadata),
        )


def log_metrics_summary() -> None:
    """Log the current Alpha monitoring metric summary."""

    metrics = get_alpha_metrics()
    logger.info("=== Alpha 模块指标摘要 ===")
    for provider in _PROVIDERS:
        metric = metrics.registry.get_metric(
            "alpha_provider_success_rate",
            {"provider": provider},
        )
        if metric:
            logger.info("%s 成功率: %.2f%%", provider, metric.value * 100)

    coverage = metrics.registry.get_metric("alpha_coverage_ratio")
    if coverage:
        logger.info("覆盖率: %.2f%%", coverage.value * 100)
    for queue in _QLIB_QUEUES:
        metric = metrics.registry.get_metric(
            "qlib_infer_queue_lag" if "infer" in queue else "qlib_train_queue_lag",
            {"queue": queue},
        )
        if metric:
            logger.info("%s 队列积压: %.0f", queue, metric.value)
    logger.info("========================")
