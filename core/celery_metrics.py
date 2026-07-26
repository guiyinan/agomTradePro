"""
Celery Prometheus Metrics Signal Handlers

自动记录 Celery 任务的 Prometheus 指标：
- 任务执行总数（按任务名称、状态分组）
- 任务执行延迟
- 任务重试次数
- 任务失败原因

使用方式：
    在 core/celery.py 中导入此模块即可自动启用信号处理。

    # core/celery.py
    from .celery_metrics import *  # noqa
"""

import logging
import time
from collections.abc import Callable, Mapping
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from celery.exceptions import Retry, SoftTimeLimitExceeded, TimeLimitExceeded
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_revoked,
)

logger = logging.getLogger(__name__)

# 存储任务开始时间的字典
_task_start_times: dict[str, float] = {}

P = ParamSpec("P")
R = TypeVar("R")


def _stable_task_name(value: object, *, attribute: str) -> str:
    """Return a bounded task label without trusting a dynamic Celery object."""

    raw_name = getattr(value, attribute, None)
    if not isinstance(raw_name, str):
        return "unknown"
    normalized = raw_name.strip()
    return normalized[:200] if normalized else "unknown"


def _count_worker_tasks(payload: object) -> tuple[int, int]:
    """Count tasks and workers from a Celery inspect mapping."""

    if not isinstance(payload, Mapping):
        return 0, 0
    task_count = 0
    worker_count = 0
    for worker_tasks in payload.values():
        if not isinstance(worker_tasks, (list, tuple)):
            continue
        worker_count += 1
        task_count += len(worker_tasks)
    return task_count, worker_count


def _metric_count(metrics: Mapping[str, int | str], key: str) -> float:
    """Return one validated numeric queue metric for Prometheus."""

    value = metrics.get(key, 0)
    return float(value) if isinstance(value, int) and not isinstance(value, bool) else 0.0


@task_prerun.connect  # type: ignore[misc]  # Celery signal decorator is untyped.
def task_prerun_handler(
    sender: object | None = None,
    task_id: str | None = None,
    task: object | None = None,
    **kwargs: object,
) -> None:
    """
    任务开始前记录开始时间

    Args:
        sender: 任务发送者
        task_id: 任务 ID
        task: Celery Task 实例
        **kwargs: 其他参数
    """
    try:
        if task_id:
            _task_start_times[task_id] = time.perf_counter()
    except Exception as exc:
        logger.warning(
            "Failed to record task start time (error_type=%s)",
            type(exc).__name__,
        )


@task_postrun.connect  # type: ignore[misc]  # Celery signal decorator is untyped.
def task_postrun_handler(
    sender: object | None = None,
    task_id: str | None = None,
    task: object | None = None,
    retval: object = None,
    **kwargs: object,
) -> None:
    """
    任务完成后记录指标

    记录：
    - 任务总数
    - 任务执行时间
    - 任务状态（成功/失败）

    Args:
        sender: 任务发送者
        task_id: 任务 ID
        task: Celery Task 实例
        retval: 返回值
        **kwargs: 其他参数
    """
    try:
        from core.metrics import celery_task_duration_seconds, celery_task_total

        # 获取任务名称
        task_name = _stable_task_name(task, attribute="name")

        # 计算执行时间
        start_time = _task_start_times.pop(task_id, None) if task_id else None
        duration = None
        if start_time is not None:
            duration = time.perf_counter() - start_time

        # 确定任务状态
        # retval 可能是 Exception 实例
        if isinstance(retval, Exception):
            status = "failure"
        else:
            status = "success"

        # 记录指标
        celery_task_total.labels(task_name=task_name, status=status).inc()

        if duration is not None:
            celery_task_duration_seconds.labels(task_name=task_name).observe(duration)

    except Exception as exc:
        logger.warning(
            "Failed to record task postrun metrics (error_type=%s)",
            type(exc).__name__,
        )


@task_retry.connect  # type: ignore[misc]  # Celery signal decorator is untyped.
def task_retry_handler(
    sender: object | None = None,
    request: object | None = None,
    reason: object = None,
    einfo: object | None = None,
    **kwargs: object,
) -> None:
    """
    任务重试时记录指标

    记录：
    - 重试次数
    - 重试原因

    Args:
        sender: 任务发送者
        request: 任务请求
        reason: 重试原因
        einfo: 异常信息
        **kwargs: 其他参数
    """
    try:
        from core.metrics import celery_task_retry_total

        # 获取任务名称
        task_name = _stable_task_name(request, attribute="task")

        # 确定重试原因
        retry_reason = "unknown"
        if reason:
            retry_reason = type(reason).__name__
        else:
            exception = getattr(einfo, "exception", None)
            if isinstance(exception, BaseException):
                retry_reason = type(exception).__name__

        # 记录重试指标
        celery_task_retry_total.labels(task_name=task_name, reason=retry_reason).inc()

        logger.debug(
            "Task %s (id=%s) retrying: %s",
            task_name,
            getattr(request, "id", "unknown"),
            retry_reason,
        )

    except Exception as exc:
        logger.warning(
            "Failed to record task retry metrics (error_type=%s)",
            type(exc).__name__,
        )


@task_failure.connect  # type: ignore[misc]  # Celery signal decorator is untyped.
def task_failure_handler(
    sender: object | None = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    **kwargs: object,
) -> None:
    """
    任务失败时记录指标

    记录失败的任务状态。

    Args:
        sender: 任务发送者
        task_id: 任务 ID
        exception: 异常实例
        **kwargs: 其他参数
    """
    try:
        from core.metrics import celery_task_total

        # 获取任务名称
        task_name = _stable_task_name(sender, attribute="name")

        # 记录失败指标
        celery_task_total.labels(task_name=task_name, status="failure").inc()

        logger.debug(
            "Task %s (id=%s) failed: %s",
            task_name,
            task_id,
            type(exception).__name__ if exception else "unknown",
        )

    except Exception as exc:
        logger.warning(
            "Failed to record task failure metrics (error_type=%s)",
            type(exc).__name__,
        )


@task_revoked.connect  # type: ignore[misc]  # Celery signal decorator is untyped.
def task_revoked_handler(
    sender: object | None = None,
    request: object | None = None,
    terminated: bool | None = None,
    signum: int | None = None,
    **kwargs: object,
) -> None:
    """
    任务被撤销时记录指标

    记录撤销的任务状态。

    Args:
        sender: 任务发送者
        request: 任务请求
        terminated: 是否被终止
        signum: 信号编号
        **kwargs: 其他参数
    """
    try:
        from core.metrics import celery_task_total

        # 获取任务名称
        task_name = _stable_task_name(request, attribute="task")

        # 记录撤销指标
        status = "terminated" if terminated else "revoked"
        celery_task_total.labels(task_name=task_name, status=status).inc()

        logger.debug(
            "Task %s (id=%s) %s (terminated=%s, signum=%s)",
            task_name,
            getattr(request, "id", "unknown"),
            status,
            terminated,
            signum,
        )

    except Exception as exc:
        logger.warning(
            "Failed to record task revoked metrics (error_type=%s)",
            type(exc).__name__,
        )


# ==================== 辅助函数 ====================


def get_task_queue_metrics() -> dict[str, int | str]:
    """
    获取 Celery 队列指标

    Returns:
        Dict: 包含队列长度、活跃任务数等指标
    """
    try:
        from core.celery import app

        # 获取所有已注册的任务
        inspect = app.control.inspect()
        active = inspect.active()
        reserved = inspect.reserved()
        inspect.stats()

        active_count, active_workers = _count_worker_tasks(active)
        reserved_count, reserved_workers = _count_worker_tasks(reserved)

        return {
            "active_tasks": active_count,
            "reserved_tasks": reserved_count,
            "workers": max(active_workers, reserved_workers),
        }

    except Exception as exc:
        logger.error(
            "Failed to get queue metrics (error_type=%s)",
            type(exc).__name__,
        )
        return {
            "active_tasks": 0,
            "reserved_tasks": 0,
            "workers": 0,
            "error": "queue_metrics_unavailable",
        }


def update_queue_metrics() -> None:
    """
    更新队列指标到 Prometheus

    可通过定时任务定期调用以更新 Gauge 类型的指标。
    """
    try:
        from core.metrics import celery_active_workers, celery_queue_length

        metrics = get_task_queue_metrics()

        # 更新活跃工作线程数
        celery_active_workers.labels(worker_name="all").set(_metric_count(metrics, "workers"))

        # 更新队列长度
        # 注意：由于 Celery 默认队列，这里使用 'default' 队列名
        total_pending = _metric_count(metrics, "reserved_tasks")
        celery_queue_length.labels(queue_name="default").set(total_pending)

        # 对于其他队列，可以通过 inspect.reserved() 按队列分组统计

    except Exception as exc:
        logger.warning(
            "Failed to update queue metrics (error_type=%s)",
            type(exc).__name__,
        )


# ==================== 装饰器 ====================


def track_celery_task(func: Callable[P, R]) -> Callable[P, R]:
    """
    Celery 任务追踪装饰器（替代方案）

    如果不想使用信号处理器，可以使用此装饰器直接装饰任务。

    使用示例:
        @shared_task
        @track_celery_task
        def my_task(arg1, arg2):
            ...
    """
    from core.metrics import celery_task_duration_seconds, celery_task_total

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        task_name = func.__name__
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)

            # 记录成功
            duration = time.perf_counter() - start_time
            celery_task_total.labels(task_name=task_name, status="success").inc()

            if duration is not None:
                celery_task_duration_seconds.labels(task_name=task_name).observe(duration)

            return result

        except Retry:
            # 记录重试
            duration = time.perf_counter() - start_time
            celery_task_total.labels(task_name=task_name, status="retry").inc()

            if duration is not None:
                celery_task_duration_seconds.labels(task_name=task_name).observe(duration)

            raise

        except (SoftTimeLimitExceeded, TimeLimitExceeded):
            # 记录超时
            duration = time.perf_counter() - start_time
            celery_task_total.labels(task_name=task_name, status="timeout").inc()

            if duration is not None:
                celery_task_duration_seconds.labels(task_name=task_name).observe(duration)

            raise

        except Exception:
            # 记录失败
            duration = time.perf_counter() - start_time
            celery_task_total.labels(task_name=task_name, status="failure").inc()

            if duration is not None:
                celery_task_duration_seconds.labels(task_name=task_name).observe(duration)

            raise

    return cast(Callable[P, R], wrapper)
