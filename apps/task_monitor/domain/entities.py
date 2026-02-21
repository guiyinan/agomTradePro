"""
Task Monitor Domain Entities

任务监控领域实体，仅使用 Python 标准库。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


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


@dataclass(frozen=True)
class TaskExecutionRecord:
    """任务执行记录（值对象）"""

    task_id: str
    task_name: str
    status: TaskStatus
    args: tuple
    kwargs: dict
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    result: Optional[str]
    exception: Optional[str]
    traceback: Optional[str]
    runtime_seconds: Optional[float]
    retries: int
    priority: TaskPriority
    queue: Optional[str]
    worker: Optional[str]

    def to_dict(self) -> dict:
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
    traceback: Optional[str]
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

    def to_dict(self) -> dict:
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
    last_execution_at: Optional[datetime]

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "task_name": self.task_name,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "average_runtime": self.average_runtime,
            "success_rate": self.success_rate,
            "last_execution_status": self.last_execution_status.value,
            "last_execution_at": self.last_execution_at.isoformat() if self.last_execution_at else None,
        }
