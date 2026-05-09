"""
Task Monitor Application DTOs

数据传输对象定义。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class TaskStatusResponse:
    """任务状态响应 DTO"""
    task_id: str
    task_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    runtime_seconds: float | None
    retries: int
    is_success: bool
    is_failure: bool


@dataclass
class TaskListResponse:
    """任务列表响应 DTO"""
    total: int
    items: list[TaskStatusResponse]


@dataclass
class HealthCheckResponse:
    """健康检查响应 DTO"""
    is_healthy: bool
    broker_reachable: bool
    backend_reachable: bool
    active_workers: list[str]
    active_tasks_count: int
    pending_tasks_count: int
    scheduled_tasks_count: int
    last_check: str


@dataclass
class TaskStatisticsResponse:
    """任务统计响应 DTO"""
    task_name: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_runtime: float
    success_rate: float
    last_execution_status: str
    last_execution_at: str | None


@dataclass
class ScheduledTaskResponse:
    """周期任务行 DTO。"""

    name: str
    task_path: str
    enabled: bool
    schedule_type: str
    schedule_display: str
    queue: str | None
    description: str
    kwargs_preview: str
    last_run_at: str | None
    total_run_count: int
    last_execution_status: str | None
    last_execution_at: str | None
    last_runtime_seconds: float | None
    recent_failure_count: int


@dataclass
class SchedulerSummaryResponse:
    """周期任务摘要 DTO。"""

    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    crontab_tasks: int
    interval_tasks: int
    one_off_tasks: int


@dataclass
class SchedulerBootstrapResponse:
    """周期任务初始化响应 DTO。"""

    executed_commands: list[str]
    output_lines: list[str]


@dataclass
class SchedulerConsoleResponse:
    """统一任务后台页面 DTO。"""

    summary: SchedulerSummaryResponse
    health: HealthCheckResponse
    periodic_tasks: list[ScheduledTaskResponse]
    recent_failures: TaskListResponse
