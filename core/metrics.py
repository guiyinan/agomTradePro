"""
AgomTradePro Prometheus Metrics

统一的 Prometheus 指标定义，涵盖：
- API 请求指标（延迟、错误率、请求量）
- Celery 任务指标（成功率、重试率、队列堆积）
- 审计日志指标（写入成功/失败）

指标命名规范：
- 使用 snake_case 命名
- 指标名包含单位（seconds、bytes、total）
- 标签使用小写字母和下划线

使用示例:
    >>> from core.metrics import api_request_latency, record_api_request
    >>> record_api_request('GET', '/api/regime/', 200, 0.123)
"""

import logging
import math
from collections.abc import Callable
from functools import wraps
from time import perf_counter
from typing import NotRequired, ParamSpec, TypedDict, TypeVar, cast

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class ApiMetricSummary(TypedDict):
    """Aggregated API metric counts."""

    total: float
    errors: float


class CeleryMetricSummary(TypedDict):
    """Aggregated Celery metric counts."""

    total: float
    retries: float


class AuditMetricSummary(TypedDict):
    """Aggregated audit-write metric counts."""

    total: float
    failures: float


class MetricsSummary(TypedDict):
    """Stable metrics-summary response contract."""

    api_requests: ApiMetricSummary
    celery_tasks: CeleryMetricSummary
    audit_writes: AuditMetricSummary
    error: NotRequired[str]


def _bounded_label(value: object, *, fallback: str = "unknown", limit: int = 200) -> str:
    """Normalize a dynamic Prometheus label and cap its cardinality surface."""

    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized[:limit] if normalized else fallback


def _finite_non_negative(value: object) -> float | None:
    """Return a finite non-negative metric value or reject it."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) and normalized >= 0.0 else None


def _exception_type(exc: BaseException) -> str:
    """Return the stable exception class label used in logs and metrics."""

    return type(exc).__name__


def _retry_reason_label(value: object) -> str:
    """Accept identifier-like retry reasons without publishing raw messages."""

    normalized = _bounded_label(value, fallback="unknown", limit=80)
    return normalized if normalized.replace(".", "_").isidentifier() else "other"


# ==================== API 请求指标 ====================

# API 请求总数（按方法、端点、状态码分组）
api_request_total = Counter(
    "api_request_total", "Total API requests", ["method", "endpoint", "status_code", "view_name"]
)

# API 请求延迟（秒）- 使用直方图记录分布
api_request_latency_seconds = Histogram(
    "api_request_latency_seconds",
    "API request latency in seconds",
    ["method", "endpoint", "view_name"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# API 错误请求总数（4xx/5xx）
api_error_total = Counter(
    "api_error_total",
    "Total API error requests (4xx/5xx)",
    ["method", "endpoint", "error_class", "status_code"],
)

# ==================== Celery 任务指标 ====================

# Celery 任务执行总数
celery_task_total = Counter(
    "celery_task_total",
    "Total Celery task executions",
    ["task_name", "status"],  # status: success/failure/retry/timeout
)

# Celery 任务执行时间
celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0),
)

# Celery 任务重试次数
celery_task_retry_total = Counter(
    "celery_task_retry_total", "Total Celery task retries", ["task_name", "reason"]
)

# Celery 队列积压量（通过 Gauge 设置）
celery_queue_length = Gauge(
    "celery_queue_length", "Current number of tasks in Celery queue", ["queue_name"]
)

# Celery 活跃工作线程数
celery_active_workers = Gauge(
    "celery_active_workers", "Number of active Celery workers", ["worker_name"]
)

# ==================== 数据库连接指标 ====================

# 数据库连接池使用情况
db_connections_total = Gauge(
    "db_connections_total",
    "Total database connections",
    ["database", "status"],  # status: active/idle
)

# 数据库查询延迟
db_query_latency_seconds = Histogram(
    "db_query_latency_seconds",
    "Database query latency in seconds",
    ["database", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ==================== 审计日志指标 ====================

# 审计日志写入总数
audit_write_total = Counter(
    "audit_write_total",
    "Total audit log write operations",
    ["module", "source", "status"],  # status: success/failure
)

# 审计日志写入延迟
audit_write_latency_seconds = Histogram(
    "audit_write_latency_seconds",
    "Audit log write latency in seconds",
    ["module", "source"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# ==================== 异常指标 ====================

# 异常总数（按模块、异常类型分组）
exception_total = Counter(
    "app_exception_total", "Total exceptions by type", ["module", "exception_class"]
)

# 未捕获异常总数
unhandled_exception_total = Counter(
    "app_unhandled_exception_total", "Total unhandled exceptions", ["module"]
)

# 外部服务异常总数
external_service_error_total = Counter(
    "app_external_service_error_total",
    "Total external service errors",
    ["service_name", "error_type"],
)


# ==================== 记录函数 ====================


def record_api_request(
    method: str,
    endpoint: str,
    status_code: int,
    duration_seconds: float,
    view_name: str = "unknown",
    error_class: str | None = None,
) -> None:
    """
    记录 API 请求指标

    Args:
        method: HTTP 方法（GET/POST/PUT/DELETE）
        endpoint: API 端点路径
        status_code: HTTP 状态码
        duration_seconds: 请求处理时间（秒）
        view_name: DRF 视图名称
        error_class: 错误类名（仅错误时）
    """
    try:
        normalized_method = _bounded_label(method.upper(), limit=16)
        normalized_endpoint = _bounded_label(endpoint, limit=240)
        normalized_view_name = _bounded_label(view_name)
        normalized_duration = _finite_non_negative(duration_seconds)
        normalized_status_code = (
            status_code
            if isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 100 <= status_code <= 599
            else 500
        )

        # 记录请求总数
        api_request_total.labels(
            method=normalized_method,
            endpoint=normalized_endpoint,
            status_code=str(normalized_status_code),
            view_name=normalized_view_name,
        ).inc()

        # 记录延迟
        if normalized_duration is not None:
            api_request_latency_seconds.labels(
                method=normalized_method,
                endpoint=normalized_endpoint,
                view_name=normalized_view_name,
            ).observe(normalized_duration)

        # 记录错误（4xx/5xx）
        if normalized_status_code >= 400:
            api_error_total.labels(
                method=normalized_method,
                endpoint=normalized_endpoint,
                error_class=_bounded_label(error_class),
                status_code=str(normalized_status_code),
            ).inc()

    except Exception as exc:
        # 指标记录失败不应影响业务
        logger.warning(
            "Failed to record API metric (error_type=%s)",
            _exception_type(exc),
        )


def record_celery_task(
    task_name: str,
    status: str,
    duration_seconds: float | None = None,
    retry_reason: str | None = None,
) -> None:
    """
    记录 Celery 任务指标

    Args:
        task_name: 任务名称
        status: 任务状态（success/failure/retry/timeout）
        duration_seconds: 任务执行时间（秒）
        retry_reason: 重试原因（status=retry 时）
    """
    try:
        normalized_task_name = _bounded_label(task_name)
        requested_status = _bounded_label(status, limit=32)
        normalized_status = (
            requested_status
            if requested_status
            in {"success", "failure", "retry", "timeout", "revoked", "terminated"}
            else "unknown"
        )
        normalized_duration = _finite_non_negative(duration_seconds)

        # 记录任务总数
        celery_task_total.labels(
            task_name=normalized_task_name,
            status=normalized_status,
        ).inc()

        # 记录执行时间
        if normalized_duration is not None:
            celery_task_duration_seconds.labels(task_name=normalized_task_name).observe(
                normalized_duration
            )

        # 记录重试
        if normalized_status == "retry" and retry_reason:
            celery_task_retry_total.labels(
                task_name=normalized_task_name,
                reason=_retry_reason_label(retry_reason),
            ).inc()

    except Exception as exc:
        logger.warning(
            "Failed to record Celery metric (error_type=%s)",
            _exception_type(exc),
        )


def record_audit_write(
    module: str,
    status: str,
    source: str = "api",
    latency_seconds: float | None = None,
) -> None:
    """
    记录审计日志写入指标

    Args:
        module: 模块名称
        status: 写入状态（success/failure）
        source: 数据来源（api/mcp/sdk）
        latency_seconds: 写入延迟（秒）
    """
    try:
        normalized_module = _bounded_label(module)
        normalized_source = _bounded_label(source, limit=32)
        normalized_status = _bounded_label(status, limit=32)
        normalized_latency = _finite_non_negative(latency_seconds)

        # 记录写入总数
        audit_write_total.labels(
            module=normalized_module,
            source=normalized_source,
            status=normalized_status,
        ).inc()

        # 记录延迟
        if normalized_latency is not None:
            audit_write_latency_seconds.labels(
                module=normalized_module,
                source=normalized_source,
            ).observe(normalized_latency)

    except Exception as exc:
        logger.warning(
            "Failed to record audit metric (error_type=%s)",
            _exception_type(exc),
        )


# ==================== 装饰器 ====================


def track_api_request(view_func: Callable[P, R]) -> Callable[P, R]:
    """
    API 请求追踪装饰器

    用于 DRF 视图或视图方法，自动记录请求指标。

    使用示例:
        @track_api_request
        def get(self, request, *args, **kwargs):
            ...
    """

    @wraps(view_func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        positional = cast(tuple[object, ...], args)
        view = positional[0] if positional else None
        request = positional[1] if len(positional) > 1 else kwargs.get("request")

        # 获取视图名称
        view_name = type(view).__name__ if view is not None else "unknown"

        # 获取端点路径
        resolver_match = getattr(request, "resolver_match", None)
        route = getattr(resolver_match, "route", None)
        endpoint = _bounded_label(
            route if isinstance(route, str) and route else getattr(request, "path", None),
            limit=240,
        )
        method = _bounded_label(getattr(request, "method", None), limit=16)

        # 记录开始时间
        start_time = perf_counter()

        try:
            # 执行视图
            response = view_func(*args, **kwargs)

            # 记录指标
            duration = perf_counter() - start_time
            response_status = getattr(response, "status_code", 200)
            status_code = (
                response_status
                if isinstance(response_status, int) and not isinstance(response_status, bool)
                else 500
            )
            record_api_request(
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                duration_seconds=duration,
                view_name=view_name,
            )

            return response

        except Exception as exc:
            # 记录错误指标
            duration = perf_counter() - start_time
            error_class = _exception_type(exc)
            exception_status = getattr(exc, "status_code", 500)
            status_code = (
                exception_status
                if isinstance(exception_status, int) and not isinstance(exception_status, bool)
                else 500
            )

            record_api_request(
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                duration_seconds=duration,
                view_name=view_name,
                error_class=error_class,
            )

            raise

    return cast(Callable[P, R], wrapper)


def track_celery_task(task_func: Callable[P, R]) -> Callable[P, R]:
    """
    Celery 任务追踪装饰器

    用于 Celery 任务，自动记录任务执行指标。

    使用示例:
        @shared_task
        @track_celery_task
        def my_task(arg1, arg2):
            ...
    """

    @wraps(task_func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # 获取任务名称
        task_name = task_func.__name__

        # 记录开始时间
        start_time = perf_counter()

        try:
            # 执行任务
            result = task_func(*args, **kwargs)

            # 记录成功指标
            duration = perf_counter() - start_time
            record_celery_task(task_name=task_name, status="success", duration_seconds=duration)

            return result

        except Exception:
            # 记录失败指标
            duration = perf_counter() - start_time
            record_celery_task(task_name=task_name, status="failure", duration_seconds=duration)

            raise

    return cast(Callable[P, R], wrapper)


# ==================== 指标摘要 ====================


def record_exception(
    exception: Exception,
    module: str = "unknown",
    is_handled: bool = True,
    service_name: str | None = None,
) -> None:
    """
    记录异常指标

    Args:
        exception: 异常实例
        module: 模块名称
        is_handled: 是否已处理（True表示已捕获处理，False表示未处理）
        service_name: 外部服务名称（如果是外部服务错误）
    """
    try:
        exception_class = _exception_type(exception)
        normalized_module = _bounded_label(module)

        # 记录异常总数
        exception_total.labels(
            module=normalized_module,
            exception_class=exception_class,
        ).inc()

        # 记录未处理异常
        if not is_handled:
            unhandled_exception_total.labels(module=normalized_module).inc()

        # 记录外部服务错误
        if service_name:
            error_type = "timeout" if "timeout" in exception_class.lower() else "other"
            external_service_error_total.labels(
                service_name=_bounded_label(service_name),
                error_type=error_type,
            ).inc()

    except Exception as exc:
        # 指标记录失败不应影响业务
        logger.warning(
            "Failed to record exception metric (error_type=%s)",
            _exception_type(exc),
        )


def get_metrics_summary() -> MetricsSummary:
    """
    获取指标摘要（用于健康检查和监控）

    Returns:
        dict: 包含各类指标摘要的字典
    """
    try:
        from prometheus_client import REGISTRY

        summary: MetricsSummary = {
            "api_requests": {"total": 0.0, "errors": 0.0},
            "celery_tasks": {"total": 0.0, "retries": 0.0},
            "audit_writes": {"total": 0.0, "failures": 0.0},
        }

        # 遍历所有指标
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                name = sample.name

                # API 请求统计
                if name == "api_request_total":
                    summary["api_requests"]["total"] += float(sample.value)
                if name == "api_error_total":
                    summary["api_requests"]["errors"] += float(sample.value)

                # Celery 任务统计
                if name == "celery_task_total":
                    summary["celery_tasks"]["total"] += float(sample.value)
                if name == "celery_task_retry_total":
                    summary["celery_tasks"]["retries"] += float(sample.value)

                # 审计写入统计
                if name == "audit_write_total":
                    summary["audit_writes"]["total"] += float(sample.value)
                    if sample.labels.get("status") == "failure":
                        summary["audit_writes"]["failures"] += float(sample.value)

        return summary

    except Exception as exc:
        logger.error(
            "Failed to get metrics summary (error_type=%s)",
            _exception_type(exc),
        )
        return {
            "error": "metrics_summary_unavailable",
            "api_requests": {"total": 0.0, "errors": 0.0},
            "celery_tasks": {"total": 0.0, "retries": 0.0},
            "audit_writes": {"total": 0.0, "failures": 0.0},
        }
