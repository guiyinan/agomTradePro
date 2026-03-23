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
