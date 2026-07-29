"""Runtime TUI metadata for Task Monitor and readiness governance."""

from __future__ import annotations

from typing import Any

_SCREEN = "api-library.data-center"
_MODULE = "system-governance"
_SOURCE = "approved:runtime-task-monitor"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "query",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    options: list[str] | None = None,
    default: Any | None = None,
) -> dict[str, Any]:
    """Build one typed Task Monitor action field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if options is not None:
        field["options"] = options
    if default is not None:
        field["default"] = default
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_type: str,
    view_model: dict[str, Any],
    effect: str | None = None,
) -> dict[str, Any]:
    """Build one administrator Task Monitor action."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "read" if method == "GET" else "admin",
        "audience": "admin",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "03 任务与验收监控",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": view_model,
    }
    if effect is not None:
        action["effect"] = effect
        action["confirmation_required"] = True
    return action


_TASK_COLUMNS = [
    {"key": "task_id", "label": "任务 ID"},
    {"key": "task_name", "label": "任务名称"},
    {"key": "status", "label": "状态"},
    {"key": "started_at", "label": "开始时间"},
    {"key": "finished_at", "label": "完成时间"},
    {"key": "runtime_seconds", "label": "耗时（秒）"},
    {"key": "retries", "label": "重试次数"},
]

_SCHEDULE_COLUMNS = [
    {"key": "name", "label": "计划名称"},
    {"key": "enabled", "label": "启用"},
    {"key": "schedule_display", "label": "计划"},
    {"key": "queue", "label": "队列"},
    {"key": "last_execution_status", "label": "最近状态"},
    {"key": "last_execution_at", "label": "最近执行"},
    {"key": "recent_failure_count", "label": "近期失败"},
]

_SCHEDULE_FIELDS = [
    _field(
        "quote_pre_refresh_time",
        "行情预刷新时间（HH:MM）",
        binding="body",
        required=True,
    ),
    _field(
        "daily_evidence_time",
        "每日验收证据时间（HH:MM）",
        binding="body",
        required=True,
    ),
    _field(
        "weekly_auto_advisor_time",
        "每周自动顾问时间（HH:MM）",
        binding="body",
        required=True,
    ),
]

RUNTIME_TASK_MONITOR_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="task-monitor.dashboard",
        label="查看任务健康概览",
        endpoint="/api/system/dashboard/",
        method="GET",
        intent="read_task_monitor_dashboard",
        description="查看近期失败任务和 Celery 健康摘要。",
        sequence=500,
        fields=[],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "celery_health.is_healthy"},
    ),
    _action(
        key="task-monitor.scheduler-catalog",
        label="查看计划任务目录",
        endpoint="/api/system/scheduler/console/",
        method="GET",
        intent="read_scheduler_catalog",
        description="查看有界计划任务目录、最近执行状态和维护摘要。",
        sequence=510,
        fields=[
            _field(
                "limit",
                "返回数量",
                input_type="number",
                value_type="integer",
                default=100,
            )
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "periodic_tasks",
            "total_path": "summary.total_tasks",
            "columns": _SCHEDULE_COLUMNS,
        },
    ),
    _action(
        key="task-monitor.task-list",
        label="查询任务执行记录",
        endpoint="/api/system/list/",
        method="GET",
        intent="list_task_executions",
        description="按任务名称、状态和失败标记查询最近执行记录。",
        sequence=520,
        fields=[
            _field("task_name", "任务名称"),
            _field(
                "status",
                "状态",
                input_type="select",
                options=[
                    "",
                    "pending",
                    "started",
                    "success",
                    "failure",
                    "retry",
                    "revoked",
                    "timeout",
                ],
            ),
            _field(
                "limit",
                "返回数量",
                input_type="number",
                value_type="integer",
                default=100,
            ),
            _field(
                "failures_only",
                "仅失败任务",
                input_type="checkbox",
                value_type="boolean",
                default=False,
            ),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "items",
            "total_path": "total",
            "columns": _TASK_COLUMNS,
        },
    ),
    _action(
        key="task-monitor.task-detail",
        label="查看任务执行详情",
        endpoint="/api/system/status/<task_id>/",
        method="GET",
        intent="read_task_execution",
        description="按任务 ID 查看状态、耗时和重试次数。",
        sequence=530,
        fields=[
            _field(
                "task_id",
                "任务 ID",
                binding="path",
                required=True,
            )
        ],
        view_type="detail",
        view_model={"kind": "detail", "title_path": "task_name", "status_path": "status"},
    ),
    _action(
        key="task-monitor.statistics",
        label="查看任务统计",
        endpoint="/api/system/statistics/",
        method="GET",
        intent="read_task_statistics",
        description="查看指定任务近期成功率、平均耗时和最近状态。",
        sequence=540,
        fields=[
            _field("task_name", "任务名称", required=True),
            _field(
                "days",
                "统计天数",
                input_type="number",
                value_type="integer",
                default=7,
            ),
        ],
        view_type="detail",
        view_model={
            "kind": "detail",
            "title_path": "task_name",
            "status_path": "last_execution_status",
        },
    ),
    _action(
        key="task-monitor.celery-health",
        label="检查 Celery 健康",
        endpoint="/api/system/celery/health/",
        method="GET",
        intent="read_celery_health",
        description="检查 broker、backend、worker 和任务队列状态。",
        sequence=550,
        fields=[],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "is_healthy"},
    ),
    _action(
        key="task-monitor.readiness",
        label="查看验收监视器",
        endpoint="/api/system/readiness/monitor/",
        method="GET",
        intent="read_operational_readiness",
        description="查看验收窗口、调度、数据覆盖和决策阻断。",
        sequence=560,
        fields=[
            _field(
                "strict_runtime",
                "严格检查运行态",
                input_type="checkbox",
                value_type="boolean",
                default=False,
            )
        ],
        view_type="detail",
        view_model={
            "kind": "detail",
            "title_path": "daily_state.title",
            "status_path": "daily_state.severity",
        },
    ),
    _action(
        key="task-monitor.readiness-schedule",
        label="查看验收调度时间",
        endpoint="/api/system/readiness/schedule/",
        method="GET",
        intent="read_readiness_schedule",
        description="查看行情预刷新、每日证据和每周自动顾问时间。",
        sequence=570,
        fields=[],
        view_type="detail",
        view_model={"kind": "detail", "title_path": "daily_evidence_time"},
    ),
    _action(
        key="task-monitor.readiness-schedule-update",
        label="更新验收调度时间",
        endpoint="/api/system/readiness/schedule/",
        method="PATCH",
        intent="update_readiness_schedule",
        description="校验并更新三项收市后调度时间。",
        sequence=580,
        fields=_SCHEDULE_FIELDS,
        view_type="detail",
        view_model={"kind": "detail", "status_path": "daily_evidence_time"},
        effect="update",
    ),
    _action(
        key="task-monitor.scheduler-bootstrap",
        label="初始化默认计划任务",
        endpoint="/api/system/scheduler/bootstrap/",
        method="POST",
        intent="bootstrap_default_schedules",
        description="执行仓库维护的默认计划任务初始化命令。",
        sequence=590,
        fields=[],
        view_type="detail",
        view_model={"kind": "detail", "title_path": "executed_commands"},
        effect="execute",
    ),
)
