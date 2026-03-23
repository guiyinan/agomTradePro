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

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

logger = logging.getLogger(__name__)


def _safe_counter(name: str, description: str, labelnames: list) -> Counter:
    """Safely create a Counter, returning existing one if already registered."""
    try:
        return Counter(name, description, labelnames)
    except ValueError:
        # Already registered - retrieve existing collector from registry
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        # Fallback: re-raise if we can't find it
        raise


def _safe_histogram(name: str, description: str, labelnames: list, buckets=None) -> Histogram:
    """Safely create a Histogram, returning existing one if already registered."""
    try:
        kwargs = {"buckets": buckets} if buckets else {}
        return Histogram(name, description, labelnames, **kwargs)
    except ValueError:
        # Already registered - retrieve existing collector from registry
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, '_name') and collector._name == name:
                return collector
        # Fallback: re-raise if we can't find it
        raise


# 审计写入成功次数（按模块和操作类型分组）
audit_write_success_total = _safe_counter(
    "audit_write_success_total",
    "Total number of successful audit write operations",
    ["module", "action", "source"]
)


# 审计写入失败次数（按模块和错误类型分组）
audit_write_failure_total = _safe_counter(
    "audit_write_failure_total",
    "Total number of failed audit write operations",
    ["module", "error_type", "source"]
)


# 审计写入延迟（秒）
audit_write_latency_seconds = _safe_histogram(
    "audit_write_latency_seconds",
    "Audit write operation latency in seconds",
    ["module", "source"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)


# 审计写入操作总数（按状态标签分组）
audit_write_operations_total = _safe_counter(
    "audit_write_operations_total",
    "Total audit write operations by status",
    ["module", "status", "source"]
)


def record_audit_write_success(
    module: str,
    action: str,
    source: str = "unknown",
    latency_seconds: float = None,
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
            module=module or "unknown",
            action=action or "unknown",
            source=source or "unknown"
        ).inc()

        audit_write_operations_total.labels(
            module=module or "unknown",
            status="success",
            source=source or "unknown"
        ).inc()

        if latency_seconds is not None:
            audit_write_latency_seconds.labels(
                module=module or "unknown",
                source=source or "unknown"
            ).observe(latency_seconds)

    except Exception as e:
        # 指标记录失败不应影响业务
        logger.warning(f"Failed to record audit success metric: {e}")


def record_audit_write_failure(
    module: str,
    error_type: str,
    source: str = "unknown",
    latency_seconds: float = None,
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
            source=source or "unknown"
        ).inc()

        audit_write_operations_total.labels(
            module=module or "unknown",
            status="failure",
            source=source or "unknown"
        ).inc()

        if latency_seconds is not None:
            audit_write_latency_seconds.labels(
                module=module or "unknown",
                source=source or "unknown"
            ).observe(latency_seconds)

    except Exception as e:
        # 指标记录失败不应影响业务
        logger.warning(f"Failed to record audit failure metric: {e}")


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
        audit_write_latency_seconds.labels(
            module=module or "unknown",
            source=source or "unknown"
        ).observe(latency_seconds)

    except Exception as e:
        # 指标记录失败不应影响业务
        logger.warning(f"Failed to record audit latency metric: {e}")


def get_audit_metrics_summary() -> dict:
    """
    获取审计指标摘要

    Returns:
        dict: 包含各种指标计数的字典
    """
    try:
        # 获取所有指标的当前值
        summary = {
            "success_total": 0,
            "failure_total": 0,
            "operations_total": 0,
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
        else:
            summary["failure_rate"] = 0.0

        return summary

    except Exception as e:
        logger.error(f"Failed to get audit metrics summary: {e}", exc_info=True)
        return {
            "error": str(e),
            "success_total": 0,
            "failure_total": 0,
            "operations_total": 0,
            "failure_rate": 0.0,
        }


# 指标导出函数（用于集成到 Prometheus 端点）
def export_metrics() -> str:
    """
    导出 Prometheus 格式的指标

    Returns:
        str: Prometheus 文本格式的指标
    """
    from prometheus_client import exposition

    try:
        # 生成 Prometheus 文本格式输出
        output = []

        # 添加成功计数指标
        for metric in audit_write_success_total.collect():
            output.append(exposition.metric_to_sample(metric))

        # 添加失败计数指标
        for metric in audit_write_failure_total.collect():
            output.append(exposition.metric_to_sample(metric))

        # 添加操作总数指标
        for metric in audit_write_operations_total.collect():
            output.append(exposition.metric_to_sample(metric))

        # 添加延迟直方图指标
        for metric in audit_write_latency_seconds.collect():
            output.append(exposition.metric_to_sample(metric))

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Failed to export audit metrics: {e}", exc_info=True)
        return f"# Error exporting metrics: {e}\n"
