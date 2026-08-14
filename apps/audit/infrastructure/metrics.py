"""
Audit Module Prometheus Metrics

审计模块的 Prometheus 指标定义，用于监控审计日志写入情况。

指标定义：
- audit_write_success_total: 审计写入成功次数
- audit_write_failure_total: 审计写入失败次数
- audit_write_latency_seconds: 审计写入延迟（秒）
- audit_write_operations_total: 审计写入操作总数（按状态标签分组）

使用示例:
    >>> from apps.audit.infrastructure.metrics import (
    ...     record_audit_write_success,
    ...     record_audit_write_failure,
    ...     audit_write_latency
    ... )
    >>>
    >>> # 记录成功
    >>> record_audit_write_success(module="regime", action="analyze")
    >>>
    >>> # 记录失败
    >>> record_audit_write_failure(module="regime", error_type="database")
"""

import logging
import math
from collections.abc import Sequence
from typing import NotRequired, TypedDict

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from apps.audit.application.system_audit_outbox_observability import (
    SystemAuditOutboxBacklogSnapshot,
)

logger = logging.getLogger(__name__)


class AuditMetricsSummary(TypedDict):
    """Stable public summary of audit write metrics."""

    success_total: float
    failure_total: float
    operations_total: float
    failure_rate: float
    error: NotRequired[str]


def _safe_counter(
    name: str,
    description: str,
    labelnames: Sequence[str],
) -> Counter:
    """Safely create a Counter, returning existing one if already registered."""
    try:
        return Counter(name, description, labelnames)
    except ValueError:
        # Already registered - retrieve existing collector from registry
        for collector in REGISTRY._names_to_collectors.values():
            if isinstance(collector, Counter) and collector._name == name:
                return collector
        # Fallback: re-raise if we can't find it
        raise


def _safe_histogram(
    name: str,
    description: str,
    labelnames: Sequence[str],
    buckets: Sequence[float] | None = None,
) -> Histogram:
    """Safely create a Histogram, returning existing one if already registered."""
    try:
        if buckets is None:
            return Histogram(name, description, labelnames)
        return Histogram(name, description, labelnames, buckets=buckets)
    except ValueError:
        # Already registered - retrieve existing collector from registry
        for collector in REGISTRY._names_to_collectors.values():
            if isinstance(collector, Histogram) and collector._name == name:
                return collector
        # Fallback: re-raise if we can't find it
        raise


def _safe_gauge(
    name: str,
    description: str,
    labelnames: Sequence[str],
) -> Gauge:
    """Safely create a Gauge, returning an existing one if registered."""

    try:
        return Gauge(name, description, labelnames)
    except ValueError:
        for collector in REGISTRY._names_to_collectors.values():
            if isinstance(collector, Gauge) and collector._name == name:
                return collector
        raise


def _observe_latency(
    *,
    module: str,
    source: str,
    latency_seconds: float,
) -> None:
    """Observe a finite non-negative latency without polluting metric state."""
    if not math.isfinite(latency_seconds) or latency_seconds < 0:
        logger.warning("Skipped invalid audit latency metric")
        return
    audit_write_latency_seconds.labels(
        module=module or "unknown",
        source=source or "unknown",
    ).observe(latency_seconds)


# 审计写入成功次数（按模块和操作类型分组）
audit_write_success_total = _safe_counter(
    "audit_write_success_total",
    "Total number of successful audit write operations",
    ["module", "action", "source"],
)


# 审计写入失败次数（按模块和错误类型分组）
audit_write_failure_total = _safe_counter(
    "audit_write_failure_total",
    "Total number of failed audit write operations",
    ["module", "error_type", "source"],
)


# 审计写入延迟（秒）
audit_write_latency_seconds = _safe_histogram(
    "audit_write_latency_seconds",
    "Audit write operation latency in seconds",
    ["module", "source"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


# 审计写入操作总数（按状态标签分组）
audit_write_operations_total = _safe_counter(
    "audit_write_operations_total",
    "Total audit write operations by status",
    ["module", "status", "source"],
)


# Transactional outbox backlog projection.  The owner label is intentionally
# fixed by ``record_system_audit_outbox_backlog``; callers cannot publish
# arbitrary IDs or resource names as Prometheus labels.
system_audit_outbox_pending = _safe_gauge(
    "system_audit_outbox_pending",
    "Number of pending system-audit outbox rows",
    ["owner"],
)
system_audit_outbox_oldest_age_seconds = _safe_gauge(
    "system_audit_outbox_oldest_age_seconds",
    "Age in seconds of the oldest recoverable system-audit outbox row",
    ["owner"],
)
system_audit_outbox_due_pending = _safe_gauge(
    "system_audit_outbox_due_pending",
    "Number of due pending system-audit outbox rows",
    ["owner"],
)
system_audit_outbox_claimed = _safe_gauge(
    "system_audit_outbox_claimed",
    "Number of currently claimed system-audit outbox rows",
    ["owner"],
)
system_audit_outbox_expired_claimed = _safe_gauge(
    "system_audit_outbox_expired_claimed",
    "Number of expired claimed system-audit outbox rows",
    ["owner"],
)
system_audit_outbox_failed = _safe_gauge(
    "system_audit_outbox_failed",
    "Number of terminal failed system-audit outbox rows",
    ["owner"],
)
system_audit_outbox_delivered = _safe_gauge(
    "system_audit_outbox_delivered",
    "Number of delivered system-audit outbox rows",
    ["owner"],
)


def record_system_audit_outbox_backlog(
    snapshot: SystemAuditOutboxBacklogSnapshot,
) -> None:
    """Project one validated backlog snapshot into bounded Prometheus gauges.

    This is deliberately a projection sink, not a database reader or a
    scheduler.  A future health/metrics composition may call it after reading
    the application backlog use case; until then it remains dormant and does
    not claim that runtime backlog observation is wired.
    """

    if not isinstance(snapshot, SystemAuditOutboxBacklogSnapshot):
        logger.warning("Skipped invalid system audit outbox backlog metric snapshot")
        return
    try:
        labels = {"owner": "audit"}
        system_audit_outbox_pending.labels(**labels).set(snapshot.pending_count)
        system_audit_outbox_oldest_age_seconds.labels(**labels).set(
            snapshot.oldest_backlog_age_seconds or 0.0
        )
        system_audit_outbox_due_pending.labels(**labels).set(snapshot.due_pending_count)
        system_audit_outbox_claimed.labels(**labels).set(snapshot.claimed_count)
        system_audit_outbox_expired_claimed.labels(**labels).set(snapshot.expired_claimed_count)
        system_audit_outbox_failed.labels(**labels).set(snapshot.failed_count)
        system_audit_outbox_delivered.labels(**labels).set(snapshot.delivered_count)
    except Exception as exc:
        # Metrics are best-effort and must never turn a health projection into
        # a business failure.  Do not publish exception text or credentials.
        logger.warning(
            "Failed to record system audit outbox backlog metric (error_type=%s)",
            type(exc).__name__,
        )


def record_audit_write_success(
    module: str,
    action: str,
    source: str = "unknown",
    latency_seconds: float | None = None,
) -> None:
    """
    记录审计写入成功

    Args:
        module: 模块名称
        action: 操作类型
        source: 数据来源（MCP/SDK/API）
        latency_seconds: 写入延迟（秒），可选
    """
    try:
        audit_write_success_total.labels(
            module=module or "unknown", action=action or "unknown", source=source or "unknown"
        ).inc()

        audit_write_operations_total.labels(
            module=module or "unknown", status="success", source=source or "unknown"
        ).inc()

        if latency_seconds is not None:
            _observe_latency(
                module=module or "unknown",
                source=source or "unknown",
                latency_seconds=latency_seconds,
            )

    except Exception as exc:
        # 指标记录失败不应影响业务
        logger.warning(
            "Failed to record audit success metric (error_type=%s)",
            type(exc).__name__,
        )


def record_audit_write_failure(
    module: str,
    error_type: str,
    source: str = "unknown",
    latency_seconds: float | None = None,
) -> None:
    """
    记录审计写入失败

    Args:
        module: 模块名称
        error_type: 错误类型（database/timeout/validation/unknown）
        source: 数据来源（MCP/SDK/API）
        latency_seconds: 写入延迟（秒），可选
    """
    try:
        audit_write_failure_total.labels(
            module=module or "unknown",
            error_type=error_type or "unknown",
            source=source or "unknown",
        ).inc()

        audit_write_operations_total.labels(
            module=module or "unknown", status="failure", source=source or "unknown"
        ).inc()

        if latency_seconds is not None:
            _observe_latency(
                module=module or "unknown",
                source=source or "unknown",
                latency_seconds=latency_seconds,
            )

    except Exception as exc:
        # 指标记录失败不应影响业务
        logger.warning(
            "Failed to record audit failure metric (error_type=%s)",
            type(exc).__name__,
        )


def record_audit_write_latency(
    module: str,
    latency_seconds: float,
    source: str = "unknown",
) -> None:
    """
    记录审计写入延迟

    Args:
        module: 模块名称
        latency_seconds: 写入延迟（秒）
        source: 数据来源（MCP/SDK/API）
    """
    try:
        _observe_latency(
            module=module or "unknown",
            source=source or "unknown",
            latency_seconds=latency_seconds,
        )

    except Exception as exc:
        # 指标记录失败不应影响业务
        logger.warning(
            "Failed to record audit latency metric (error_type=%s)",
            type(exc).__name__,
        )


def get_audit_metrics_summary() -> AuditMetricsSummary:
    """
    获取审计指标摘要

    Returns:
        dict: 包含各种指标计数的字典
    """
    try:
        # 获取所有指标的当前值
        summary: AuditMetricsSummary = {
            "success_total": 0.0,
            "failure_total": 0.0,
            "operations_total": 0.0,
            "failure_rate": 0.0,
        }

        # 遍历所有标签组合获取总数
        for metric in audit_write_success_total.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    summary["success_total"] += sample.value

        for metric in audit_write_failure_total.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    summary["failure_total"] += sample.value

        for metric in audit_write_operations_total.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    summary["operations_total"] += sample.value

        # 计算失败率
        total_operations = summary["success_total"] + summary["failure_total"]
        if total_operations > 0:
            summary["failure_rate"] = summary["failure_total"] / total_operations
        return summary

    except Exception as exc:
        logger.error(
            "Failed to get audit metrics summary (error_type=%s)",
            type(exc).__name__,
        )
        return {
            "error": "metrics_unavailable",
            "success_total": 0.0,
            "failure_total": 0.0,
            "operations_total": 0.0,
            "failure_rate": 0.0,
        }


# 指标导出函数（用于集成到 Prometheus 端点）
def export_metrics() -> str:
    """
    导出 Prometheus 格式的指标

    Returns:
        str: Prometheus 文本格式的指标
    """
    try:
        # Build a dedicated registry so the endpoint exports only audit metrics
        # while staying compatible with the installed prometheus_client version.
        registry = CollectorRegistry(auto_describe=True)
        for collector in (
            audit_write_success_total,
            audit_write_failure_total,
            audit_write_operations_total,
            audit_write_latency_seconds,
            system_audit_outbox_pending,
            system_audit_outbox_oldest_age_seconds,
            system_audit_outbox_due_pending,
            system_audit_outbox_claimed,
            system_audit_outbox_expired_claimed,
            system_audit_outbox_failed,
            system_audit_outbox_delivered,
        ):
            registry.register(collector)

        payload: object = generate_latest(registry)
        if not isinstance(payload, bytes):
            raise TypeError("Prometheus metrics payload must be bytes")
        return payload.decode("utf-8")

    except Exception as exc:
        logger.error(
            "Failed to export audit metrics (error_type=%s)",
            type(exc).__name__,
        )
        return "# Audit metrics export unavailable\n"
