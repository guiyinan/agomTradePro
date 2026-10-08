"""
Task Monitor Domain Entities

任务监控领域实体，仅使用 Python 标准库。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    """任务状态枚举"""

    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    """任务优先级"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskOrphanLeaseState(Enum):
    """Evidence state for a task-specific domain lease."""

    ABSENT = "absent"
    NOT_REQUIRED = "not_required"
    ACTIVE = "active"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskOrphanClusterSnapshot:
    """One read-only broker and worker snapshot used for orphan decisions."""

    observed_at: datetime
    complete: bool
    broker_visibility_timeout_seconds: int | None
    grace_seconds: int | None
    ready_message_count: int | None
    active_task_ids: tuple[str, ...] | None
    reserved_task_ids: tuple[str, ...] | None
    scheduled_task_ids: tuple[str, ...] | None
    responding_worker_names: tuple[str, ...] | None
    managed_queue_count: int = 0


@dataclass(frozen=True)
class TaskOrphanAttemptEvidence:
    """Task-specific hard-limit, backend, and lease evidence."""

    hard_time_limit_seconds: int | None
    backend_state: str | None
    lease_state: TaskOrphanLeaseState
    lease_evidence_code: str

    def to_safe_dict(
        self,
        *,
        record: "TaskExecutionRecord",
        snapshot: TaskOrphanClusterSnapshot,
    ) -> dict[str, str | int | bool | None]:
        """Build the bounded public evidence projection for a confirmed orphan."""

        from hashlib import sha256

        attempt_digest = (
            sha256(record.attempt_id.encode("utf-8")).hexdigest()
            if record.attempt_id is not None
            else None
        )
        worker_online = (
            record.worker in snapshot.responding_worker_names
            if record.worker is not None and snapshot.responding_worker_names is not None
            else None
        )
        return {
            "evidence_version": "task_monitor_orphan_v1",
            "error_code": "TASK_ORPHAN_TIMEOUT",
            "observed_at": snapshot.observed_at.isoformat(),
            "attempt_id_sha256": attempt_digest,
            "hard_time_limit_seconds": self.hard_time_limit_seconds,
            "broker_visibility_timeout_seconds": snapshot.broker_visibility_timeout_seconds,
            "grace_seconds": snapshot.grace_seconds,
            "backend_state": self.backend_state,
            "ready_message_count": snapshot.ready_message_count,
            "managed_queue_count": snapshot.managed_queue_count,
            "queue_evidence_code": "complete_all_managed_queues_empty",
            "worker_snapshot_complete": snapshot.complete,
            "original_worker_online": worker_online,
            "task_seen_active": record.task_id in (snapshot.active_task_ids or ()),
            "task_seen_reserved": record.task_id in (snapshot.reserved_task_ids or ()),
            "task_seen_scheduled": record.task_id in (snapshot.scheduled_task_ids or ()),
            "domain_lease_state": self.lease_state.value,
            "domain_lease_evidence_code": self.lease_evidence_code,
        }


@dataclass(frozen=True)
class TaskExecutionRecord:
    """任务执行记录（值对象）"""

    task_id: str
    task_name: str
    status: TaskStatus
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    result: str | None
    exception: str | None
    traceback: str | None
    runtime_seconds: float | None
    retries: int
    priority: TaskPriority
    queue: str | None
    worker: str | None
    attempt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value,
            "args": self.args,
            "kwargs": self.kwargs,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result,
            "exception": self.exception,
            "traceback": self.traceback,
            "runtime_seconds": self.runtime_seconds,
            "retries": self.retries,
            "priority": self.priority.value,
            "queue": self.queue,
            "worker": self.worker,
        }


@dataclass(frozen=True)
class TaskFailureAlert:
    """任务失败告警（值对象）"""

    task_id: str
    task_name: str
    exception: str
    traceback: str | None
    retries: int
    max_retries: int
    is_final_failure: bool
    triggered_at: datetime

    def should_alert(self) -> bool:
        """判断是否应该发送告警"""
        return self.is_final_failure

    def get_severity(self) -> str:
        """获取告警严重程度"""
        if self.is_final_failure:
            return "critical"
        return "warning"


@dataclass(frozen=True)
class CeleryHealthStatus:
    """Celery 健康状态（值对象）"""

    is_healthy: bool
    broker_reachable: bool
    backend_reachable: bool
    active_workers: list[str]
    active_tasks_count: int
    pending_tasks_count: int
    scheduled_tasks_count: int
    last_check: datetime

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "is_healthy": self.is_healthy,
            "broker_reachable": self.broker_reachable,
            "backend_reachable": self.backend_reachable,
            "active_workers": self.active_workers,
            "active_tasks_count": self.active_tasks_count,
            "pending_tasks_count": self.pending_tasks_count,
            "scheduled_tasks_count": self.scheduled_tasks_count,
            "last_check": self.last_check.isoformat(),
        }


@dataclass(frozen=True)
class TaskStatistics:
    """任务统计信息（值对象）"""

    task_name: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_runtime: float
    success_rate: float
    last_execution_status: TaskStatus
    last_execution_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "task_name": self.task_name,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "average_runtime": self.average_runtime,
            "success_rate": self.success_rate,
            "last_execution_status": self.last_execution_status.value,
            "last_execution_at": (
                self.last_execution_at.isoformat() if self.last_execution_at else None
            ),
        }


@dataclass(frozen=True)
class ScheduledTaskRecord:
    """周期任务读模型。"""

    name: str
    task_path: str
    enabled: bool
    schedule_type: str
    schedule_display: str
    queue: str | None
    description: str
    kwargs_preview: str
    last_run_at: datetime | None
    total_run_count: int
    last_execution_status: str | None
    last_execution_at: datetime | None
    last_runtime_seconds: float | None
    recent_failure_count: int


@dataclass(frozen=True)
class ScheduledCrontabRecord:
    """周期任务 crontab 读模型。"""

    name: str
    exists: bool
    enabled: bool
    hour: str | None
    minute: str | None
    day_of_week: str | None


@dataclass(frozen=True)
class SchedulerCatalogSummary:
    """周期任务目录摘要。"""

    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    crontab_tasks: int
    interval_tasks: int
    one_off_tasks: int


@dataclass(frozen=True)
class SchedulerBootstrapResult:
    """默认周期任务初始化结果。"""

    executed_commands: list[str]
    output_lines: list[str]
