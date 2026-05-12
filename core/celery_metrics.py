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
from typing import Any

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


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    """
    任务开始前记录开始时间

    Args:
        sender: 任务发送者
        task_id: 任务 ID
        task: Celery Task 实例
        **kwargs: 其他参数
    """
    try:
        _task_start_times[task_id] = time.perf_counter()
    except Exception as e:
        logger.warning(f"Failed to record task start time: {e}")


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, retval=None, **kwargs):
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
        task_name = task.name if task else 'unknown'

        # 计算执行时间
        start_time = _task_start_times.pop(task_id, None)
        duration = None
        if start_time is not None:
            duration = time.perf_counter() - start_time

        # 确定任务状态
        # retval 可能是 Exception 实例
        if isinstance(retval, Exception):
            status = 'failure'
        else:
            status = 'success'

        # 记录指标
        celery_task_total.labels(
            task_name=task_name,
            status=status
        ).inc()

        if duration is not None:
            celery_task_duration_seconds.labels(
                task_name=task_name
            ).observe(duration)

    except Exception as e:
        logger.warning(f"Failed to record task postrun metrics: {e}")


@task_retry.connect
def task_retry_handler(sender=None, request=None, reason=None, einfo=None, **kwargs):
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
        task_name = request.task if request else 'unknown'

        # 确定重试原因
        retry_reason = 'unknown'
        if reason:
            if isinstance(reason, Exception):
                retry_reason = reason.__class__.__name__
            else:
                retry_reason = str(reason)
        elif einfo and einfo.exception:
            retry_reason = einfo.exception.__class__.__name__

        # 记录重试指标
        celery_task_retry_total.labels(
            task_name=task_name,
            reason=retry_reason
        ).inc()

        logger.debug(
            f"Task {task_name} (id={request.id}) retrying: {retry_reason}"
        )

    except Exception as e:
        logger.warning(f"Failed to record task retry metrics: {e}")


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
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
        task_name = sender.name if sender else 'unknown'

        # 记录失败指标
        celery_task_total.labels(
            task_name=task_name,
            status='failure'
        ).inc()

        logger.debug(
            f"Task {task_name} (id={task_id}) failed: "
            f"{exception.__class__.__name__ if exception else 'unknown'}"
        )

    except Exception as e:
        logger.warning(f"Failed to record task failure metrics: {e}")


@task_revoked.connect
def task_revoked_handler(sender=None, request=None, terminated=None, signum=None, **kwargs):
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
        task_name = request.task if request else 'unknown'

        # 记录撤销指标
        status = 'terminated' if terminated else 'revoked'
        celery_task_total.labels(
            task_name=task_name,
            status=status
        ).inc()

        logger.debug(
            f"Task {task_name} (id={request.id}) {status} "
            f"(terminated={terminated}, signum={signum})"
        )

    except Exception as e:
        logger.warning(f"Failed to record task revoked metrics: {e}")


# ==================== 辅助函数 ====================

def get_task_queue_metrics() -> dict[str, Any]:
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

        # 统计活跃任务
        active_count = 0
        if active:
            for worker_tasks in active.values():
                active_count += len(worker_tasks)

        # 统计预留任务
        reserved_count = 0
        if reserved:
            for worker_tasks in reserved.values():
                reserved_count += len(worker_tasks)

        return {
            'active_tasks': active_count,
            'reserved_tasks': reserved_count,
            'workers': len(active) if active else 0,
        }

    except Exception as e:
        logger.error(f"Failed to get queue metrics: {e}", exc_info=True)
        return {
            'active_tasks': 0,
            'reserved_tasks': 0,
            'workers': 0,
            'error': str(e),
        }


def update_queue_metrics():
    """
    更新队列指标到 Prometheus

    可通过定时任务定期调用以更新 Gauge 类型的指标。
    """
    try:
        from core.metrics import celery_active_workers, celery_queue_length

        metrics = get_task_queue_metrics()

        # 更新活跃工作线程数
        celery_active_workers.labels(
            worker_name='all'
        ).set(metrics.get('workers', 0))

        # 更新队列长度
        # 注意：由于 Celery 默认队列，这里使用 'default' 队列名
        total_pending = metrics.get('reserved_tasks', 0)
        celery_queue_length.labels(
            queue_name='default'
        ).set(total_pending)

        # 对于其他队列，可以通过 inspect.reserved() 按队列分组统计

    except Exception as e:
        logger.warning(f"Failed to update queue metrics: {e}")


# ==================== 装饰器 ====================

def track_celery_task(func):
    """
    Celery 任务追踪装饰器（替代方案）

    如果不想使用信号处理器，可以使用此装饰器直接装饰任务。

    使用示例:
        @shared_task
        @track_celery_task
        def my_task(arg1, arg2):
            ...
    """
    from functools import wraps

    from core.metrics import celery_task_duration_seconds, celery_task_total

    @wraps(func)
    def wrapper(*args, **kwargs):
        task_name = func.__name__
        start_time = time.perf_counter()

        try:
            result = func(*args, **kwargs)

            # 记录成功
            duration = time.perf_counter() - start_time
            celery_task_total.labels(
                task_name=task_name,
                status='success'
            ).inc()

            if duration is not None:
                celery_task_duration_seconds.labels(
                    task_name=task_name
                ).observe(duration)

            return result

        except Retry:
            # 记录重试
            duration = time.perf_counter() - start_time
            celery_task_total.labels(
                task_name=task_name,
                status='retry'
            ).inc()

            if duration is not None:
                celery_task_duration_seconds.labels(
                    task_name=task_name
                ).observe(duration)

            raise

        except (SoftTimeLimitExceeded, TimeLimitExceeded):
            # 记录超时
            duration = time.perf_counter() - start_time
            celery_task_total.labels(
                task_name=task_name,
                status='timeout'
            ).inc()

            if duration is not None:
                celery_task_duration_seconds.labels(
                    task_name=task_name
                ).observe(duration)

            raise

        except Exception:
            # 记录失败
            duration = time.perf_counter() - start_time
            celery_task_total.labels(
                task_name=task_name,
                status='failure'
            ).inc()

            if duration is not None:
                celery_task_duration_seconds.labels(
                    task_name=task_name
                ).observe(duration)

            raise

    return wrapper
