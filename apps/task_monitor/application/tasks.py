"""
Task Monitor Application Tasks

Celery 任务钩子和装饰器，用于自动记录任务执行状态。
"""

import logging
from typing import Any

from celery import Task
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_revoked,
)
from django.utils import timezone

from apps.operational_readiness.application.tasks import (
    execute_personal_readiness_daily_task,
)
from apps.operational_readiness.management.commands.run_personal_readiness_daily import (
    run_personal_readiness_daily,
)
from apps.task_monitor.application.repository_provider import (
    get_database_backup_service,
    get_task_record_repository,
)
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.domain.interfaces import TaskRecordRepositoryProtocol
from shared.config.secrets import get_secrets
from shared.domain.task_outcomes import task_business_failure_message
from shared.infrastructure.alert_service import create_default_alert_service

logger = logging.getLogger(__name__)

# 全局仓储实例
_repository: TaskRecordRepositoryProtocol | None = None
_FAILED_BUSINESS_OUTCOMES = {"failed", "partial", "blocked"}


def get_repository() -> TaskRecordRepositoryProtocol:
    """获取仓储实例（延迟初始化）"""
    global _repository
    if _repository is None:
        _repository = get_task_record_repository()
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


def _resolve_terminal_status(*, state: str | None, retval: Any) -> TaskStatus:
    """Resolve technical state together with a task's normalized business outcome."""

    if state == "FAILURE":
        return TaskStatus.FAILURE
    if state == "REVOKED":
        return TaskStatus.REVOKED
    if isinstance(retval, dict):
        outcome = str(retval.get("outcome", "")).strip().lower()
        if outcome in _FAILED_BUSINESS_OUTCOMES:
            return TaskStatus.FAILURE
    return TaskStatus.SUCCESS


# ========== Celery 信号处理 ==========


@task_prerun.connect  # type: ignore[misc]
def task_prerun_handler(
    sender: Any = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **kwds: Any,
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

    except Exception as exc:
        logger.error(
            "Failed to record task start: error_type=%s",
            exc.__class__.__name__,
        )


@task_postrun.connect  # type: ignore[misc]
def task_postrun_handler(
    sender: Any = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    retval: Any | None = None,
    state: str | None = None,
    **kwds: Any,
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

        # 同时读取 Celery 技术状态和规范化业务 outcome。
        status = _resolve_terminal_status(state=state, retval=retval)
        business_failure = task_business_failure_message(retval)

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
            exception=business_failure,
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as exc:
        logger.error(
            "Failed to record task completion: error_type=%s",
            exc.__class__.__name__,
        )


@task_failure.connect  # type: ignore[misc]
def task_failure_handler(
    sender: Any = None,
    task_id: str | None = None,
    exception: Exception | None = None,
    traceback: str | None = None,
    einfo: Any | None = None,
    **kwds: Any,
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
        if einfo:
            captured_exception = getattr(einfo, "exception", None)
            exception_str = (
                captured_exception.__class__.__name__
                if captured_exception is not None
                else "TaskFailure"
            )
        elif exception:
            exception_str = exception.__class__.__name__

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
            traceback=None,
            runtime_seconds=runtime_seconds,
            retries=existing.retries,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        use_case = get_use_case()
        use_case.execute(record)

    except Exception as exc:
        logger.error(
            "Failed to record task failure: error_type=%s",
            exc.__class__.__name__,
        )


@task_retry.connect  # type: ignore[misc]
def task_retry_handler(
    sender: Any = None,
    task_id: str | None = None,
    request: Any | None = None,
    reason: str | None = None,
    einfo: Any | None = None,
    **kwds: Any,
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
            exception=(
                reason.__class__.__name__
                if isinstance(reason, BaseException)
                else "task_retry" if reason else None
            ),
            traceback=None,
            runtime_seconds=None,
            retries=existing.retries + 1,
            priority=existing.priority,
            queue=existing.queue,
            worker=existing.worker,
        )

        repository.save(record)

    except Exception as exc:
        logger.error(
            "Failed to record task retry: error_type=%s",
            exc.__class__.__name__,
        )


@task_revoked.connect  # type: ignore[misc]
def task_revoked_handler(
    sender: Any = None,
    task_id: str | None = None,
    signum: int | None = None,
    terminated: bool | None = None,
    expired: bool | None = None,
    **kwds: Any,
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

    except Exception as exc:
        logger.error(
            "Failed to record task revocation: error_type=%s",
            exc.__class__.__name__,
        )


# ========== Celery 定时清理任务 ==========

from celery import shared_task  # noqa: E402


@shared_task(time_limit=300, soft_time_limit=280)  # type: ignore[misc]
def cleanup_old_task_records(days_to_keep: int = 30) -> dict[str, Any]:
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
        logger.error(
            "Failed to cleanup old task records: error_type=%s",
            exc.__class__.__name__,
        )
        raise


# ========== P1-2: 数据库备份任务 ==========


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
    time_limit=300,
    soft_time_limit=280,
)
def backup_database_task(
    self: Any,
    keep_days: int | None = None,
    compress: bool = True,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """
    P1-2: 数据库备份 Celery 任务

    执行数据库备份并清理旧备份文件。
    支持 SQLite 和 PostgreSQL。

    Args:
        keep_days: 显式保留最近 N 天的运维覆盖；省略时读取 typed runtime policy
        compress: 是否压缩备份文件（默认 True）
        output_dir: 自定义备份目录（可选）

    Returns:
        dict: 备份结果，包含备份文件路径和清理统计
    """
    import subprocess

    try:
        result = get_database_backup_service().backup_database(
            keep_days=keep_days,
            compress=compress,
            output_dir=output_dir,
        )

        logger.info(
            "Database backup task completed",
            extra={
                "keep_days": keep_days,
                "compress": compress,
                "output_dir": output_dir,
                "backup_file": result.backup_file,
                "removed_old_backups": result.removed_old_backups,
            },
        )

        return {
            "status": "success",
            "message": f"Database backup created: {result.backup_file}",
            "backup_file": result.backup_file,
            "keep_days": result.keep_days,
            "compressed": result.compressed,
            "removed_old_backups": result.removed_old_backups,
        }

    except subprocess.CalledProcessError as exc:
        logger.error(
            "Database backup command failed: error_type=%s",
            exc.__class__.__name__,
        )
        # 重试任务
        raise self.retry(exc=exc) from exc

    except Exception as exc:
        logger.error(
            "Database backup task failed: error_type=%s",
            exc.__class__.__name__,
        )
        raise


@shared_task(time_limit=300, soft_time_limit=280)  # type: ignore[misc]
def verify_backup_task(backup_file: str) -> dict[str, Any]:
    """
    验证备份文件完整性

    Args:
        backup_file: 备份文件路径

    Returns:
        dict: 验证结果
    """
    from pathlib import Path

    backup_path = Path(backup_file)

    if not backup_path.exists():
        return {
            "status": "error",
            "message": f"Backup file not found: {backup_file}",
        }

    # 检查文件大小
    file_size = backup_path.stat().st_size

    if file_size == 0:
        return {
            "status": "error",
            "message": "Backup file is empty",
        }

    # 对于压缩文件，尝试读取验证
    if backup_file.endswith(".gz"):
        import gzip

        try:
            with gzip.open(backup_path, "rb") as f:
                # 读取一小部分验证
                f.read(1024)
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Backup file is corrupted ({exc.__class__.__name__})",
            }

    logger.info(
        "Backup verification passed",
        extra={
            "backup_file": backup_file,
            "file_size": file_size,
        },
    )

    return {
        "status": "success",
        "backup_file": backup_file,
        "file_size": file_size,
    }


@shared_task(  # type: ignore[misc]
    bind=True,
    name="apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
    time_limit=3600,
    soft_time_limit=3300,
)
def run_personal_readiness_daily_task(
    self: Any,
    target_date: str | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    output_dir: str = "var/readiness-evidence",
    required_days: int = 20,
    calendar_source: str = "auto",
    max_qlib_staleness_days: int = 5,
    repair_accounts: bool = False,
    run_workspace_refresh: bool = True,
    include_weekly_advisor: bool = True,
    persist_risk_report: bool = True,
    strict_daily: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "scheduler",
) -> dict[str, Any]:
    """Proxy the legacy task name to the canonical readiness owner."""

    return execute_personal_readiness_daily_task(
        task=self,
        target_date=target_date,
        user_id=user_id,
        account_id=account_id,
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        max_qlib_staleness_days=max_qlib_staleness_days,
        repair_accounts=repair_accounts,
        run_workspace_refresh=run_workspace_refresh,
        include_weekly_advisor=include_weekly_advisor,
        persist_risk_report=persist_risk_report,
        strict_daily=strict_daily,
        allow_unclosed_target_date=allow_unclosed_target_date,
        trigger_source=trigger_source,
        runner=run_personal_readiness_daily,
    )
