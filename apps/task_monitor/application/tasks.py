"""
Task Monitor Application Tasks

Celery 任务钩子和装饰器，用于自动记录任务执行状态。
"""

import functools
import logging
import traceback as tb_module
from datetime import datetime
from typing import Optional

from celery import Task
from celery.signals import (
    task_prerun,
    task_postrun,
    task_failure,
    task_retry,
    task_revoked,
)
from django.utils import timezone

from apps.task_monitor.domain.entities import (
    TaskStatus,
    TaskPriority,
    TaskExecutionRecord,
)
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.infrastructure.repositories import DjangoTaskRecordRepository
from shared.infrastructure.alert_service import create_default_alert_service
from shared.config.secrets import get_secrets

logger = logging.getLogger(__name__)

# 全局仓储实例
_repository: Optional[DjangoTaskRecordRepository] = None


def get_repository() -> DjangoTaskRecordRepository:
    """获取仓储实例（延迟初始化）"""
    global _repository
    if _repository is None:
        _repository = DjangoTaskRecordRepository()
    return _repository


def get_use_case() -> RecordTaskExecutionUseCase:
    """获取用例实例（带告警功能）"""
    # 创建告警服务
    secrets = get_secrets()
    alert_service = create_default_alert_service(
        slack_webhook=secrets.slack_webhook,
        use_console=True,
    )

    return RecordTaskExecutionUseCase(
        repository=get_repository(),
        alert_channels=[alert_service],
    )


# ========== Celery 信号处理 ==========

@task_prerun.connect
def task_prerun_handler(
    sender=None,
    task_id: Optional[str] = None,
    task: Optional[Task] = None,
    args: Optional[tuple] = None,
    kwargs: Optional[dict] = None,
    **kwds
) -> None:
    """任务开始前记录"""
    if not task_id or not task:
        return

    try:
        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=task.name,
            status=TaskStatus.STARTED,
            args=args or (),
            kwargs=kwargs or {},
            started_at=timezone.now(),
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue=task.request.get("delivery_info", {}).get("routing_key"),
            worker=task.request.get("hostname"),
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as e:
        logger.error(f"Failed to record task start: {e}")


@task_postrun.connect
def task_postrun_handler(
    sender=None,
    task_id: Optional[str] = None,
    task: Optional[Task] = None,
    args: Optional[tuple] = None,
    kwargs: Optional[dict] = None,
    retval: Optional[any] = None,
    state: Optional[str] = None,
    **kwds
) -> None:
    """任务完成后记录"""
    if not task_id or not task:
        return

    try:
        # 获取之前的记录
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        # 确定状态
        status = TaskStatus.SUCCESS
        if state == "SUCCESS":
            status = TaskStatus.SUCCESS
        elif state == "FAILURE":
            status = TaskStatus.FAILURE
        elif state == "REVOKED":
            status = TaskStatus.REVOKED

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        # 序列化结果
        result = None
        if retval is not None:
            try:
                result = str(retval)[:10000]  # 限制长度
            except Exception:
                result = "<unserializable result>"

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=task.name,
            status=status,
            args=args or existing.args,
            kwargs=kwargs or existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=result,
            exception=None,
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as e:
        logger.error(f"Failed to record task completion: {e}")


@task_failure.connect
def task_failure_handler(
    sender=None,
    task_id: Optional[str] = None,
    exception: Optional[Exception] = None,
    traceback: Optional[str] = None,
    einfo: Optional[any] = None,
    **kwds
) -> None:
    """任务失败记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        # 获取异常信息
        exception_str = None
        traceback_str = None
        if einfo:
            exception_str = str(einfo.exception)
            traceback_str = einfo.traceback
        elif exception:
            exception_str = str(exception)
            traceback_str = traceback.format_exc()

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.FAILURE,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=None,
            exception=exception_str,
            traceback=traceback_str,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as e:
        logger.error(f"Failed to record task failure: {e}")


@task_retry.connect
def task_retry_handler(
    sender=None,
    task_id: Optional[str] = None,
    request: Optional[any] = None,
    reason: Optional[str] = None,
    einfo: Optional[any] = None,
    **kwds
) -> None:
    """任务重试记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        # 更新重试次数
        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.RETRY,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=None,
            result=None,
            exception=str(reason) if reason else None,
            traceback=einfo.traceback if einfo else None,
            runtime_seconds=None,
            retries=existing.retries + 1,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        repository.save(record)

    except Exception as e:
        logger.error(f"Failed to record task retry: {e}")


@task_revoked.connect
def task_revoked_handler(
    sender=None,
    task_id: Optional[str] = None,
    signum: Optional[int] = None,
    terminated: Optional[bool] = None,
    expired: Optional[bool] = None,
    **kwds
) -> None:
    """任务撤销记录"""
    if not task_id:
        return

    try:
        repository = get_repository()
        existing = repository.get_by_task_id(task_id)

        if not existing:
            return

        # 计算运行时长
        runtime_seconds = None
        if existing.started_at:
            runtime_seconds = (timezone.now() - existing.started_at).total_seconds()

        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=existing.task_name,
            status=TaskStatus.REVOKED,
            args=existing.args,
            kwargs=existing.kwargs,
            started_at=existing.started_at,
            finished_at=timezone.now(),
            result=None,
            exception=f"Task revoked (terminated={terminated}, expired={expired})",
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        repository.save(record)

    except Exception as e:
        logger.error(f"Failed to record task revocation: {e}")


# ========== Celery 定时清理任务 ==========

from celery import shared_task


@shared_task
def cleanup_old_task_records(days_to_keep: int = 30) -> dict:
    """
    清理旧的任务记录

    定时任务，清理超过保留期限的任务记录。

    Args:
        days_to_keep: 保留天数（默认 30 天）

    Returns:
        dict: 清理结果
    """
    try:
        from apps.task_monitor.application.use_cases import CleanupOldRecordsUseCase

        use_case = CleanupOldRecordsUseCase(repository=get_repository())
        count = use_case.execute(days_to_keep=days_to_keep)

        logger.info(f"Cleaned up {count} old task records")

        return {
            "status": "success",
            "deleted_count": count,
            "days_to_keep": days_to_keep,
        }

    except Exception as exc:
        logger.error(f"Failed to cleanup old task records: {exc}")
        raise
