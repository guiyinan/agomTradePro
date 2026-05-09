"""
Task Monitor Infrastructure Repositories

任务监控仓储实现。
"""

import json
import logging
from io import StringIO
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID

from django.core.management import call_command
from django.db import models
from django.db.models import Avg, Count, Q
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from apps.task_monitor.domain.entities import (
    CeleryHealthStatus,
    SchedulerBootstrapResult,
    SchedulerCatalogSummary,
    ScheduledTaskRecord,
    TaskExecutionRecord,
    TaskPriority,
    TaskStatistics,
    TaskStatus,
)
from apps.task_monitor.domain.interfaces import (
    CeleryHealthCheckerProtocol,
    SchedulerBootstrapGatewayProtocol,
    SchedulerRepositoryProtocol,
    TaskRecordRepositoryProtocol,
)
from apps.task_monitor.infrastructure.models import TaskExecutionModel

logger = logging.getLogger(__name__)


def _safe_float(value: any) -> float:
    """
    安全解析浮点数，处理 None、字符串等异常情况

    Args:
        value: 任意值

    Returns:
        float: 解析后的浮点数，失败返回 0.0
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _to_json_compatible(value: Any) -> Any:
    """Normalize arbitrary values into JSON-safe Python primitives."""
    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_json_compatible(item) for item in value]

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, UUID):
        return str(value)

    try:
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder))
    except TypeError:
        return str(value)


class DjangoTaskRecordRepository(TaskRecordRepositoryProtocol):
    """基于 Django ORM 的任务记录仓储实现"""

    def save(self, record: TaskExecutionRecord) -> str:
        """保存任务执行记录"""
        normalized_args = _to_json_compatible(record.args)
        normalized_kwargs = _to_json_compatible(record.kwargs)

        try:
            # 尝试更新现有记录
            model = TaskExecutionModel.objects.get(task_id=record.task_id)
            model.status = record.status.value
            model.args = normalized_args
            model.kwargs = normalized_kwargs
            model.started_at = record.started_at
            model.finished_at = record.finished_at
            model.result = record.result
            model.exception = record.exception
            model.traceback = record.traceback
            model.runtime_seconds = record.runtime_seconds
            model.retries = record.retries
            model.priority = record.priority.value
            model.queue = record.queue
            model.worker = record.worker
            model.save()
        except TaskExecutionModel.DoesNotExist:
            # 创建新记录
            model = TaskExecutionModel.objects.create(
                task_id=record.task_id,
                task_name=record.task_name,
                status=record.status.value,
                args=normalized_args,
                kwargs=normalized_kwargs,
                started_at=record.started_at,
                finished_at=record.finished_at,
                result=record.result,
                exception=record.exception,
                traceback=record.traceback,
                runtime_seconds=record.runtime_seconds,
                retries=record.retries,
                priority=record.priority.value,
                queue=record.queue,
                worker=record.worker,
            )

        return str(model.id)

    def get_by_task_id(self, task_id: str) -> TaskExecutionRecord | None:
        """根据任务 ID 获取记录"""
        try:
            model = TaskExecutionModel.objects.get(task_id=task_id)
            return self._model_to_entity(model)
        except TaskExecutionModel.DoesNotExist:
            return None

    def list_by_task_name(
        self,
        task_name: str,
        limit: int = 100,
        status: str | None = None
    ) -> list[TaskExecutionRecord]:
        """根据任务名称列出记录"""
        queryset = TaskExecutionModel.objects.filter(task_name=task_name)

        if status:
            queryset = queryset.filter(status=status)

        models_list = queryset.order_by("-created_at")[:limit]

        return [self._model_to_entity(m) for m in models_list]

    def list_recent_failures(
        self,
        hours: int = 24,
        limit: int = 50
    ) -> list[TaskExecutionRecord]:
        """列出最近的失败记录"""
        since = timezone.now() - timedelta(hours=hours)

        queryset = TaskExecutionModel.objects.filter(
            status__in=["failure", "timeout"],
            created_at__gte=since
        ).order_by("-created_at")[:limit]

        return [self._model_to_entity(m) for m in queryset]

    def get_statistics(
        self,
        task_name: str,
        days: int = 7
    ) -> TaskStatistics | None:
        """获取任务统计信息"""
        since = timezone.now() - timedelta(days=days)

        base_qs = TaskExecutionModel.objects.filter(
            task_name=task_name,
            created_at__gte=since
        )

        total = base_qs.count()
        if total == 0:
            return None

        successful = base_qs.filter(status="success").count()
        failed = base_qs.filter(status__in=["failure", "timeout"]).count()

        avg_runtime_qs = base_qs.filter(runtime_seconds__isnull=False)
        avg_runtime_result = avg_runtime_qs.aggregate(avg=Avg("runtime_seconds"))
        average_runtime = _safe_float(avg_runtime_result["avg"])

        success_rate = _safe_float(successful / total) if total > 0 else 0.0

        latest = base_qs.order_by("-created_at").first()

        return TaskStatistics(
            task_name=task_name,
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            average_runtime=average_runtime,
            success_rate=success_rate,
            last_execution_status=TaskStatus(latest.status) if latest else TaskStatus.PENDING,
            last_execution_at=latest.created_at if latest else None,
        )

    def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """清理旧记录"""
        cutoff = timezone.now() - timedelta(days=days_to_keep)
        count, _ = TaskExecutionModel.objects.filter(
            created_at__lt=cutoff
        ).delete()
        return count

    def _model_to_entity(self, model: TaskExecutionModel) -> TaskExecutionRecord:
        """将 ORM 模型转换为领域实体"""
        return TaskExecutionRecord(
            task_id=model.task_id,
            task_name=model.task_name,
            status=TaskStatus(model.status),
            args=tuple(model.args) if model.args else (),
            kwargs=model.kwargs if model.kwargs else {},
            started_at=model.started_at,
            finished_at=model.finished_at,
            result=model.result,
            exception=model.exception,
            traceback=model.traceback,
            runtime_seconds=model.runtime_seconds,
            retries=model.retries,
            priority=TaskPriority(model.priority),
            queue=model.queue,
            worker=model.worker,
        )


class CeleryHealthChecker(CeleryHealthCheckerProtocol):
    """Celery 健康检查实现"""

    def __init__(self, celery_app):
        """
        初始化健康检查器

        Args:
            celery_app: Celery 应用实例
        """
        self.celery_app = celery_app

    def check_health(self) -> CeleryHealthStatus:
        """检查 Celery 健康状态"""
        is_healthy = True
        broker_reachable = False
        backend_reachable = False
        active_workers = []
        active_tasks_count = 0
        pending_tasks_count = 0
        scheduled_tasks_count = 0

        try:
            # 检查 Broker 连接
            try:
                self.celery_app.connection_for_read().connect()
                broker_reachable = True
            except Exception as e:
                logger.warning(f"Broker connection failed: {e}")
                is_healthy = False

            # 检查 Backend 连接
            try:
                self.celery_app.backend
                backend_reachable = True
            except Exception as e:
                logger.warning(f"Backend connection failed: {e}")
                is_healthy = False

            # 获取 Worker 信息
            try:
                inspect = self.celery_app.control.inspect(timeout=2.0)
                active_workers = list(inspect.active().keys()) if inspect.active() else []

                # 获取任务统计
                active_tasks = inspect.active()
                if active_tasks:
                    for worker_tasks in active_tasks.values():
                        active_tasks_count += len(worker_tasks)

                scheduled_tasks = inspect.scheduled()
                if scheduled_tasks:
                    for worker_tasks in scheduled_tasks.values():
                        scheduled_tasks_count += len(worker_tasks)

                reserved_tasks = inspect.reserved()
                if reserved_tasks:
                    for worker_tasks in reserved_tasks.values():
                        pending_tasks_count += len(worker_tasks)

            except Exception as e:
                logger.warning(f"Failed to get worker/task info: {e}")

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            is_healthy = False

        return CeleryHealthStatus(
            is_healthy=is_healthy,
            broker_reachable=broker_reachable,
            backend_reachable=backend_reachable,
            active_workers=active_workers,
            active_tasks_count=active_tasks_count,
            pending_tasks_count=pending_tasks_count,
            scheduled_tasks_count=scheduled_tasks_count,
            last_check=timezone.now(),
        )


class DjangoSchedulerRepository(SchedulerRepositoryProtocol):
    """Read-only repository for database-backed periodic tasks."""

    def get_catalog_summary(self) -> SchedulerCatalogSummary:
        queryset = PeriodicTask.objects.all()
        return SchedulerCatalogSummary(
            total_tasks=queryset.count(),
            enabled_tasks=queryset.filter(enabled=True).count(),
            disabled_tasks=queryset.filter(enabled=False).count(),
            crontab_tasks=queryset.filter(crontab__isnull=False).count(),
            interval_tasks=queryset.filter(interval__isnull=False).count(),
            one_off_tasks=queryset.filter(one_off=True).count(),
        )

    def list_periodic_tasks(self, limit: int = 100) -> list[ScheduledTaskRecord]:
        tasks = list(
            PeriodicTask.objects.select_related("crontab", "interval", "clocked", "solar")
            .order_by("enabled", "name")[:limit]
        )
        task_paths = [task.task for task in tasks if task.task]
        latest_execution_map = self._latest_execution_map(task_paths)
        recent_failure_counts = self._recent_failure_counts(task_paths)

        return [
            ScheduledTaskRecord(
                name=task.name,
                task_path=task.task,
                enabled=bool(task.enabled),
                schedule_type=self._schedule_type(task),
                schedule_display=self._schedule_display(task),
                queue=(task.queue or None),
                description=str(task.description or ""),
                kwargs_preview=_truncate_text(str(task.kwargs or "{}"), 120),
                last_run_at=task.last_run_at,
                total_run_count=int(task.total_run_count or 0),
                last_execution_status=(
                    latest_execution_map[task.task].status
                    if task.task in latest_execution_map
                    else None
                ),
                last_execution_at=(
                    latest_execution_map[task.task].created_at
                    if task.task in latest_execution_map
                    else None
                ),
                last_runtime_seconds=(
                    latest_execution_map[task.task].runtime_seconds
                    if task.task in latest_execution_map
                    else None
                ),
                recent_failure_count=int(recent_failure_counts.get(task.task, 0)),
            )
            for task in tasks
        ]

    def _latest_execution_map(self, task_paths: list[str]) -> dict[str, TaskExecutionModel]:
        if not task_paths:
            return {}

        latest_map: dict[str, TaskExecutionModel] = {}
        queryset = TaskExecutionModel.objects.filter(task_name__in=task_paths).order_by(
            "task_name",
            "-created_at",
        )
        for model in queryset:
            latest_map.setdefault(model.task_name, model)
        return latest_map

    def _recent_failure_counts(self, task_paths: list[str]) -> dict[str, int]:
        if not task_paths:
            return {}

        since = timezone.now() - timedelta(hours=24)
        rows = (
            TaskExecutionModel.objects.filter(
                task_name__in=task_paths,
                status__in=["failure", "timeout"],
                created_at__gte=since,
            )
            .values("task_name")
            .annotate(total=Count("id"))
        )
        return {str(row["task_name"]): int(row["total"]) for row in rows}

    @staticmethod
    def _schedule_type(task: PeriodicTask) -> str:
        if task.crontab_id:
            return "crontab"
        if task.interval_id:
            return "interval"
        if task.clocked_id:
            return "clocked"
        if task.solar_id:
            return "solar"
        return "custom"

    @staticmethod
    def _schedule_display(task: PeriodicTask) -> str:
        if task.crontab_id and task.crontab:
            timezone_name = getattr(task.crontab, "timezone", None)
            timezone_suffix = f" ({timezone_name})" if timezone_name else ""
            return (
                f"cron {task.crontab.minute} {task.crontab.hour} "
                f"{task.crontab.day_of_month} {task.crontab.month_of_year} "
                f"{task.crontab.day_of_week}{timezone_suffix}"
            )
        if task.interval_id and task.interval:
            return f"every {task.interval.every} {str(task.interval.period).lower()}"
        if task.clocked_id and task.clocked:
            return f"clocked @ {task.clocked.clocked_time.isoformat()}"
        if task.solar_id and task.solar:
            return (
                f"solar {task.solar.event} @ lat={task.solar.latitude}, "
                f"lon={task.solar.longitude}"
            )
        return "unspecified"


class ManagementCommandSchedulerBootstrapGateway(SchedulerBootstrapGatewayProtocol):
    """Initialize scheduler defaults through management commands."""

    def initialize_default_schedules(self) -> SchedulerBootstrapResult:
        buffer = StringIO()
        call_command("init_scheduler_defaults", stdout=buffer, stderr=buffer)
        output_lines = [
            line.strip()
            for line in buffer.getvalue().splitlines()
            if line.strip()
        ]
        return SchedulerBootstrapResult(
            executed_commands=["init_scheduler_defaults"],
            output_lines=output_lines,
        )


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"
