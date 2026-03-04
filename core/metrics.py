"""
AgomSAAF Prometheus Metrics

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

from prometheus_client import Counter, Histogram, Gauge
import logging
from functools import wraps
from time import perf_counter
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ==================== API 请求指标 ====================

# API 请求总数（按方法、端点、状态码分组）
api_request_total = Counter(
    'api_request_total',
    'Total API requests',
    ['method', 'endpoint', 'status_code', 'view_name']
)

# API 请求延迟（秒）- 使用直方图记录分布
api_request_latency_seconds = Histogram(
    'api_request_latency_seconds',
    'API request latency in seconds',
    ['method', 'endpoint', 'view_name'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
)

# API 错误请求总数（4xx/5xx）
api_error_total = Counter(
    'api_error_total',
    'Total API error requests (4xx/5xx)',
    ['method', 'endpoint', 'error_class', 'status_code']
)

# ==================== Celery 任务指标 ====================

# Celery 任务执行总数
celery_task_total = Counter(
    'celery_task_total',
    'Total Celery task executions',
    ['task_name', 'status']  # status: success/failure/retry/timeout
)

# Celery 任务执行时间
celery_task_duration_seconds = Histogram(
    'celery_task_duration_seconds',
    'Celery task execution duration in seconds',
    ['task_name'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0)
)

# Celery 任务重试次数
celery_task_retry_total = Counter(
    'celery_task_retry_total',
    'Total Celery task retries',
    ['task_name', 'reason']
)

# Celery 队列积压量（通过 Gauge 设置）
celery_queue_length = Gauge(
    'celery_queue_length',
    'Current number of tasks in Celery queue',
    ['queue_name']
)

# Celery 活跃工作线程数
celery_active_workers = Gauge(
    'celery_active_workers',
    'Number of active Celery workers',
    ['worker_name']
)

# ==================== 数据库连接指标 ====================

# 数据库连接池使用情况
db_connections_total = Gauge(
    'db_connections_total',
    'Total database connections',
    ['database', 'status']  # status: active/idle
)

# 数据库查询延迟
db_query_latency_seconds = Histogram(
    'db_query_latency_seconds',
    'Database query latency in seconds',
    ['database', 'operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

# ==================== 审计日志指标 ====================

# 审计日志写入总数
audit_write_total = Counter(
    'audit_write_total',
    'Total audit log write operations',
    ['module', 'source', 'status']  # status: success/failure
)

# 审计日志写入延迟
audit_write_latency_seconds = Histogram(
    'audit_write_latency_seconds',
    'Audit log write latency in seconds',
    ['module', 'source'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# ==================== 异常指标 ====================

# 异常总数（按模块、异常类型分组）
exception_total = Counter(
    'app_exception_total',
    'Total exceptions by type',
    ['module', 'exception_class']
)

# 未捕获异常总数
unhandled_exception_total = Counter(
    'app_unhandled_exception_total',
    'Total unhandled exceptions',
    ['module']
)

# 外部服务异常总数
external_service_error_total = Counter(
    'app_external_service_error_total',
    'Total external service errors',
    ['service_name', 'error_type']
)


# ==================== 记录函数 ====================

def record_api_request(
    method: str,
    endpoint: str,
    status_code: int,
    duration_seconds: float,
    view_name: str = 'unknown',
    error_class: Optional[str] = None,
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
        # 记录请求总数
        api_request_total.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code),
            view_name=view_name or 'unknown'
        ).inc()

        # 记录延迟
        api_request_latency_seconds.labels(
            method=method,
            endpoint=endpoint,
            view_name=view_name or 'unknown'
        ).observe(duration_seconds)

        # 记录错误（4xx/5xx）
        if status_code >= 400:
            api_error_total.labels(
                method=method,
                endpoint=endpoint,
                error_class=error_class or 'unknown',
                status_code=str(status_code)
            ).inc()

    except Exception as e:
        # 指标记录失败不应影响业务
        logger.warning(f"Failed to record API metric: {e}")


def record_celery_task(
    task_name: str,
    status: str,
    duration_seconds: Optional[float] = None,
    retry_reason: Optional[str] = None,
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
        # 记录任务总数
        celery_task_total.labels(
            task_name=task_name or 'unknown',
            status=status
        ).inc()

        # 记录执行时间
        if duration_seconds is not None:
            celery_task_duration_seconds.labels(
                task_name=task_name or 'unknown'
            ).observe(duration_seconds)

        # 记录重试
        if status == 'retry' and retry_reason:
            celery_task_retry_total.labels(
                task_name=task_name or 'unknown',
                reason=retry_reason
            ).inc()

    except Exception as e:
        logger.warning(f"Failed to record Celery metric: {e}")


def record_audit_write(
    module: str,
    status: str,
    source: str = 'api',
    latency_seconds: Optional[float] = None,
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
        # 记录写入总数
        audit_write_total.labels(
            module=module or 'unknown',
            source=source,
            status=status
        ).inc()

        # 记录延迟
        if latency_seconds is not None:
            audit_write_latency_seconds.labels(
                module=module or 'unknown',
                source=source
            ).observe(latency_seconds)

    except Exception as e:
        logger.warning(f"Failed to record audit metric: {e}")


# ==================== 装饰器 ====================

def track_api_request(view_func: Callable) -> Callable:
    """
    API 请求追踪装饰器

    用于 DRF 视图或视图方法，自动记录请求指标。

    使用示例:
        @track_api_request
        def get(self, request, *args, **kwargs):
            ...
    """
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        # 获取视图名称
        view_name = self.__class__.__name__ if hasattr(self, '__class__') else 'unknown'

        # 获取端点路径
        endpoint = request.path
        method = request.method

        # 记录开始时间
        start_time = perf_counter()

        try:
            # 执行视图
            response = view_func(self, request, *args, **kwargs)

            # 记录指标
            duration = perf_counter() - start_time
            status_code = getattr(response, 'status_code', 200)
            record_api_request(
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                duration_seconds=duration,
                view_name=view_name
            )

            return response

        except Exception as e:
            # 记录错误指标
            duration = perf_counter() - start_time
            error_class = e.__class__.__name__
            status_code = getattr(e, 'status_code', 500)

            record_api_request(
                method=method,
                endpoint=endpoint,
                status_code=status_code,
                duration_seconds=duration,
                view_name=view_name,
                error_class=error_class
            )

            raise

    return wrapper


def track_celery_task(task_func: Callable) -> Callable:
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
    def wrapper(*args, **kwargs):
        # 获取任务名称
        task_name = task_func.__name__

        # 记录开始时间
        start_time = perf_counter()

        try:
            # 执行任务
            result = task_func(*args, **kwargs)

            # 记录成功指标
            duration = perf_counter() - start_time
            record_celery_task(
                task_name=task_name,
                status='success',
                duration_seconds=duration
            )

            return result

        except Exception as e:
            # 记录失败指标
            duration = perf_counter() - start_time
            record_celery_task(
                task_name=task_name,
                status='failure',
                duration_seconds=duration
            )

            raise

    return wrapper


# ==================== 指标摘要 ====================

def record_exception(
    exception: Exception,
    module: str = 'unknown',
    is_handled: bool = True,
    service_name: Optional[str] = None,
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
        exception_class = exception.__class__.__name__

        # 记录异常总数
        exception_total.labels(
            module=module or 'unknown',
            exception_class=exception_class
        ).inc()

        # 记录未处理异常
        if not is_handled:
            unhandled_exception_total.labels(
                module=module or 'unknown'
            ).inc()

        # 记录外部服务错误
        if service_name:
            error_type = 'timeout' if 'timeout' in str(exception).lower() else 'other'
            external_service_error_total.labels(
                service_name=service_name,
                error_type=error_type
            ).inc()

    except Exception as e:
        # 指标记录失败不应影响业务
        logger.warning(f"Failed to record exception metric: {e}")


def get_metrics_summary() -> dict:
    """
    获取指标摘要（用于健康检查和监控）

    Returns:
        dict: 包含各类指标摘要的字典
    """
    try:
        from prometheus_client import REGISTRY

        summary = {
            'api_requests': {'total': 0, 'errors': 0},
            'celery_tasks': {'total': 0, 'retries': 0},
            'audit_writes': {'total': 0, 'failures': 0},
        }

        # 遍历所有指标
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                name = sample.name

                # API 请求统计
                if name == 'api_request_total' and not sample.labels.get('status_code', '').startswith('4'):
                    summary['api_requests']['total'] += sample.value
                if name == 'api_error_total':
                    summary['api_requests']['errors'] += sample.value

                # Celery 任务统计
                if name == 'celery_task_total':
                    summary['celery_tasks']['total'] += sample.value
                if name == 'celery_task_retry_total':
                    summary['celery_tasks']['retries'] += sample.value

                # 审计写入统计
                if name == 'audit_write_total':
                    summary['audit_writes']['total'] += sample.value
                    if sample.labels.get('status') == 'failure':
                        summary['audit_writes']['failures'] += sample.value

        return summary

    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}", exc_info=True)
        return {
            'error': str(e),
            'api_requests': {'total': 0, 'errors': 0},
            'celery_tasks': {'total': 0, 'retries': 0},
            'audit_writes': {'total': 0, 'failures': 0},
        }
