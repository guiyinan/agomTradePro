"""
Task Monitor Application Use Cases

任务监控用例实现。
"""

import logging
from datetime import datetime
from typing import List, Optional

from django.utils import timezone

from apps.task_monitor.application.dtos import (
    HealthCheckResponse,
    SchedulerBootstrapResponse,
    SchedulerConsoleResponse,
    SchedulerSummaryResponse,
    ScheduledTaskResponse,
    TaskListResponse,
    TaskStatisticsResponse,
    TaskStatusResponse,
)
from apps.task_monitor.domain.entities import (
    CeleryHealthStatus,
    SchedulerBootstrapResult,
    SchedulerCatalogSummary,
    ScheduledTaskRecord,
    TaskExecutionRecord,
    TaskFailureAlert,
    TaskPriority,
    TaskStatistics,
    TaskStatus,
)
from apps.task_monitor.domain.interfaces import (
    AlertChannelProtocol,
    CeleryHealthCheckerProtocol,
    SchedulerBootstrapGatewayProtocol,
    SchedulerRepositoryProtocol,
    TaskRecordRepositoryProtocol,
)
from core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class RecordTaskExecutionUseCase:
    """记录任务执行用例"""

    def __init__(
        self,
        repository: TaskRecordRepositoryProtocol,
        alert_channels: list[AlertChannelProtocol] | None = None,
    ):
        """
        初始化用例

        Args:
            repository: 任务记录仓储
            alert_channels: 告警渠道列表
        """
        self.repository = repository
        self.alert_channels = alert_channels or []

    def execute(self, record: TaskExecutionRecord) -> str:
        """
        执行记录任务

        Args:
            record: 任务执行记录

        Returns:
            str: 记录 ID
        """
        record_id = self.repository.save(record)

        # 如果任务失败，创建告警
        if record.status in [TaskStatus.FAILURE, TaskStatus.TIMEOUT]:
            self._handle_failure(record)

        return record_id

    def _handle_failure(self, record: TaskExecutionRecord) -> None:
        """处理任务失败"""
        # 假设最大重试次数为 3
        max_retries = 3
        is_final = record.retries >= max_retries

        alert = TaskFailureAlert(
            task_id=record.task_id,
            task_name=record.task_name,
            exception=record.exception or "Unknown error",
            traceback=record.traceback,
            retries=record.retries,
            max_retries=max_retries,
            is_final_failure=is_final,
            triggered_at=timezone.now(),
        )

        if alert.should_alert():
            self._send_alert(alert)

    def _send_alert(self, alert: TaskFailureAlert) -> None:
        """发送告警"""
        severity = alert.get_severity()

        for channel in self.alert_channels:
            if not channel.is_available():
                continue

            try:
                channel.send_alert(
                    level=severity,
                    title=f"Task Failed: {alert.task_name}",
                    message=f"Task {alert.task_name} failed after {alert.retries} retries.",
                    metadata={
                        "task_id": alert.task_id,
                        "exception": alert.exception,
                        "is_final_failure": alert.is_final_failure,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to send alert via {channel.__class__.__name__}: {e}")


class GetTaskStatusUseCase:
    """获取任务状态用例"""

    def __init__(self, repository: TaskRecordRepositoryProtocol):
        """
        初始化用例

        Args:
            repository: 任务记录仓储
        """
        self.repository = repository

    def execute(self, task_id: str) -> TaskStatusResponse | None:
        """
        执行获取任务状态

        Args:
            task_id: 任务 ID

        Returns:
            Optional[TaskStatusResponse]: 任务状态响应
        """
        record = self.repository.get_by_task_id(task_id)

        if not record:
            return None

        return TaskStatusResponse(
            task_id=record.task_id,
            task_name=record.task_name,
            status=record.status.value,
            started_at=record.started_at.isoformat() if record.started_at else None,
            finished_at=record.finished_at.isoformat() if record.finished_at else None,
            runtime_seconds=record.runtime_seconds,
            retries=record.retries,
            is_success=record.status == TaskStatus.SUCCESS,
            is_failure=record.status in [TaskStatus.FAILURE, TaskStatus.TIMEOUT],
        )


class ListTasksUseCase:
    """列出任务用例"""

    def __init__(self, repository: TaskRecordRepositoryProtocol):
        """
        初始化用例

        Args:
            repository: 任务记录仓储
        """
        self.repository = repository

    def execute(
        self,
        task_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
        failures_only: bool = False,
    ) -> TaskListResponse:
        """
        执行列出任务

        Args:
            task_name: 任务名称过滤
            status: 状态过滤
            limit: 返回数量限制
            failures_only: 只返回失败的任务

        Returns:
            TaskListResponse: 任务列表响应
        """
        if failures_only:
            records = self.repository.list_recent_failures(limit=limit)
        elif task_name:
            records = self.repository.list_by_task_name(
                task_name=task_name,
                limit=limit,
                status=status,
            )
        else:
            # 如果没有指定任务名称，返回最近的失败记录
            records = self.repository.list_recent_failures(limit=limit)

        items = [
            TaskStatusResponse(
                task_id=r.task_id,
                task_name=r.task_name,
                status=r.status.value,
                started_at=r.started_at.isoformat() if r.started_at else None,
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                runtime_seconds=r.runtime_seconds,
                retries=r.retries,
                is_success=r.status == TaskStatus.SUCCESS,
                is_failure=r.status in [TaskStatus.FAILURE, TaskStatus.TIMEOUT],
            )
            for r in records
        ]

        return TaskListResponse(
            total=len(items),
            items=items,
        )


class GetTaskStatisticsUseCase:
    """获取任务统计用例"""

    def __init__(self, repository: TaskRecordRepositoryProtocol):
        """
        初始化用例

        Args:
            repository: 任务记录仓储
        """
        self.repository = repository

    def execute(self, task_name: str, days: int = 7) -> TaskStatisticsResponse | None:
        """
        执行获取任务统计

        Args:
            task_name: 任务名称
            days: 统计最近多少天

        Returns:
            Optional[TaskStatisticsResponse]: 任务统计响应
        """
        stats = self.repository.get_statistics(task_name=task_name, days=days)

        if not stats:
            return None

        return TaskStatisticsResponse(
            task_name=stats.task_name,
            total_executions=stats.total_executions,
            successful_executions=stats.successful_executions,
            failed_executions=stats.failed_executions,
            average_runtime=stats.average_runtime,
            success_rate=stats.success_rate,
            last_execution_status=stats.last_execution_status.value,
            last_execution_at=stats.last_execution_at.isoformat() if stats.last_execution_at else None,
        )


class CheckCeleryHealthUseCase:
    """检查 Celery 健康状态用例"""

    def __init__(self, health_checker: CeleryHealthCheckerProtocol):
        """
        初始化用例

        Args:
            health_checker: 健康检查器
        """
        self.health_checker = health_checker

    def execute(self) -> HealthCheckResponse:
        """
        执行健康检查

        Returns:
            HealthCheckResponse: 健康检查响应

        Raises:
            ExternalServiceError: 当健康检查失败时
        """
        try:
            status = self.health_checker.check_health()

            return HealthCheckResponse(
                is_healthy=status.is_healthy,
                broker_reachable=status.broker_reachable,
                backend_reachable=status.backend_reachable,
                active_workers=status.active_workers,
                active_tasks_count=status.active_tasks_count,
                pending_tasks_count=status.pending_tasks_count,
                scheduled_tasks_count=status.scheduled_tasks_count,
                last_check=status.last_check.isoformat(),
            )

        except Exception as e:
            logger.error(f"Celery health check failed: {e}")
            raise ExternalServiceError(
                message="Failed to check Celery health",
                details={"error": str(e)}
            )


class CleanupOldRecordsUseCase:
    """清理旧记录用例"""

    def __init__(self, repository: TaskRecordRepositoryProtocol):
        """
        初始化用例

        Args:
            repository: 任务记录仓储
        """
        self.repository = repository

    def execute(self, days_to_keep: int = 30) -> int:
        """
        执行清理旧记录

        Args:
            days_to_keep: 保留天数

        Returns:
            int: 删除的记录数
        """
        count = self.repository.cleanup_old_records(days_to_keep=days_to_keep)
        logger.info(f"Cleaned up {count} old task records (older than {days_to_keep} days)")
        return count


class GetSchedulerConsoleUseCase:
    """构建周期任务后台页面上下文。"""

    def __init__(
        self,
        scheduler_repository: SchedulerRepositoryProtocol,
        health_checker: CeleryHealthCheckerProtocol,
        task_record_repository: TaskRecordRepositoryProtocol,
    ):
        self.scheduler_repository = scheduler_repository
        self.health_checker = health_checker
        self.task_record_repository = task_record_repository

    def execute(self, *, limit: int = 100) -> SchedulerConsoleResponse:
        summary = self.scheduler_repository.get_catalog_summary()
        periodic_tasks = self.scheduler_repository.list_periodic_tasks(limit=limit)
        recent_failures = ListTasksUseCase(self.task_record_repository).execute(
            failures_only=True,
            limit=10,
        )

        try:
            health = CheckCeleryHealthUseCase(self.health_checker).execute()
        except Exception as exc:
            logger.warning("Falling back to degraded Celery health payload: %s", exc)
            health = HealthCheckResponse(
                is_healthy=False,
                broker_reachable=False,
                backend_reachable=False,
                active_workers=[],
                active_tasks_count=0,
                pending_tasks_count=0,
                scheduled_tasks_count=0,
                last_check=timezone.now().isoformat(),
            )

        return SchedulerConsoleResponse(
            summary=_map_scheduler_summary(summary),
            health=health,
            periodic_tasks=[_map_scheduled_task(task) for task in periodic_tasks],
            recent_failures=recent_failures,
        )


class BootstrapDefaultSchedulesUseCase:
    """执行默认周期任务初始化。"""

    def __init__(self, gateway: SchedulerBootstrapGatewayProtocol):
        self.gateway = gateway

    def execute(self) -> SchedulerBootstrapResponse:
        result = self.gateway.initialize_default_schedules()
        return SchedulerBootstrapResponse(
            executed_commands=result.executed_commands,
            output_lines=result.output_lines,
        )


def _map_scheduled_task(task: ScheduledTaskRecord) -> ScheduledTaskResponse:
    return ScheduledTaskResponse(
        name=task.name,
        task_path=task.task_path,
        enabled=task.enabled,
        schedule_type=task.schedule_type,
        schedule_display=task.schedule_display,
        queue=task.queue,
        description=task.description,
        kwargs_preview=task.kwargs_preview,
        last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
        total_run_count=task.total_run_count,
        last_execution_status=task.last_execution_status,
        last_execution_at=(
            task.last_execution_at.isoformat() if task.last_execution_at else None
        ),
        last_runtime_seconds=task.last_runtime_seconds,
        recent_failure_count=task.recent_failure_count,
    )


def _map_scheduler_summary(summary: SchedulerCatalogSummary) -> SchedulerSummaryResponse:
    return SchedulerSummaryResponse(
        total_tasks=summary.total_tasks,
        enabled_tasks=summary.enabled_tasks,
        disabled_tasks=summary.disabled_tasks,
        crontab_tasks=summary.crontab_tasks,
        interval_tasks=summary.interval_tasks,
        one_off_tasks=summary.one_off_tasks,
    )
