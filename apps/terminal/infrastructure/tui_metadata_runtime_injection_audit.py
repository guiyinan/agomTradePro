"""Runtime TUI metadata for the audit review workbench."""

from __future__ import annotations

from typing import Any

_SCREEN = "execution.audit"
_MODULE = "execution"
_SOURCE = "approved:runtime-audit-review"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "query",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    default: object | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Build one bounded TUI field contract."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if default is not None:
        field["default"] = default
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    if options is not None:
        field["options"] = options
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    view_type: str,
    description: str,
    task_group: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    method: str = "GET",
    audience: str = "authenticated",
    risk: str = "read",
    effect: str = "read",
    confirmation_required: bool = False,
    audit_required: bool = False,
) -> dict[str, Any]:
    """Build one audit action with consistent IA and governance metadata."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": risk,
        "audience": audience,
        "effect": effect,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": task_group,
        "sequence": sequence,
        "task_tier": "operation",
        "fields": fields,
        "view_model": view_model,
    }
    if confirmation_required:
        action["confirmation_required"] = True
    if audit_required:
        action["audit_required"] = True
    return action


_REPORT_COLUMNS: list[dict[str, str]] = [
    {"key": "id", "label": "报告"},
    {"key": "backtest_id", "label": "回测"},
    {"key": "attribution_method", "label": "方法"},
    {"key": "period_start", "label": "开始"},
    {"key": "period_end", "label": "结束"},
    {"key": "total_pnl", "label": "总收益"},
    {"key": "regime_accuracy", "label": "判断准确率"},
    {"key": "created_at", "label": "生成时间"},
]

_LOG_QUERY_FIELDS: list[dict[str, Any]] = [
    _field("start_date", "开始日期", input_type="date", value_type="date"),
    _field("end_date", "结束日期", input_type="date", value_type="date"),
    _field("module", "模块"),
    _field("response_status", "响应状态", input_type="number", value_type="integer"),
    _field("mcp_tool_name", "工具名称"),
    _field("mcp_client_id", "Token / 客户端"),
    _field(
        "page",
        "页码",
        input_type="number",
        value_type="integer",
        default=1,
        minimum=1,
        maximum=1_000_000,
    ),
    _field(
        "page_size",
        "每页数量",
        input_type="number",
        value_type="integer",
        default=20,
        minimum=1,
        maximum=100,
    ),
]

_LOG_COLUMNS: list[dict[str, str]] = [
    {"key": "timestamp", "label": "时间"},
    {"key": "username", "label": "用户"},
    {"key": "source", "label": "来源"},
    {"key": "module", "label": "模块"},
    {"key": "action", "label": "动作"},
    {"key": "mcp_tool_name", "label": "工具"},
    {"key": "response_status", "label": "状态"},
    {"key": "duration_ms", "label": "耗时(ms)"},
]

_TRACE_QUERY_FIELDS: list[dict[str, Any]] = [
    _field("mcp_client_id", "Token / 客户端"),
    _field(
        "page",
        "页码",
        input_type="number",
        value_type="integer",
        default=1,
        minimum=1,
        maximum=1_000_000,
    ),
    _field(
        "page_size",
        "每页数量",
        input_type="number",
        value_type="integer",
        default=20,
        minimum=1,
        maximum=100,
    ),
]

_TRACE_COLUMNS: list[dict[str, str]] = [
    {"key": "started_at", "label": "开始时间"},
    {"key": "request_id", "label": "请求"},
    {"key": "username", "label": "用户"},
    {"key": "mcp_client_id", "label": "Token / 客户端"},
    {"key": "source", "label": "来源"},
    {"key": "step_count", "label": "步骤"},
    {"key": "status", "label": "结果"},
    {"key": "summary", "label": "摘要"},
]


RUNTIME_AUDIT_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="audit.overview",
        label="审计复盘概览",
        endpoint="/api/audit/tui/overview/",
        intent="inspect_audit_review_overview",
        view_type="detail",
        description="查看最新验证、近期归因报告和待复盘回测。",
        task_group="01 复盘概览",
        sequence=10,
        fields=[],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.report-list",
        label="归因报告",
        endpoint="/api/audit/tui/reports/",
        intent="list_attribution_reports",
        view_type="datagrid",
        description="按归因方法筛选最近 50 份报告，并查看可生成报告的回测。",
        task_group="02 归因报告",
        sequence=20,
        fields=[
            _field(
                "method",
                "归因方法",
                input_type="select",
                options=["", "heuristic", "brinson"],
            )
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "reports",
            "columns": _REPORT_COLUMNS,
        },
    ),
    _action(
        key="audit.report-generate-preview",
        label="预览报告生成",
        endpoint="/api/audit/reports/generate/preview/",
        method="POST",
        intent="preview_attribution_report_generation",
        view_type="detail",
        description="检查目标回测和写入影响，不生成报告。",
        task_group="02 归因报告",
        sequence=30,
        fields=[
            _field(
                "backtest_id",
                "回测 ID",
                binding="body",
                input_type="number",
                value_type="integer",
                required=True,
                minimum=1,
            )
        ],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.report-generate",
        label="生成归因报告",
        endpoint="/api/audit/reports/generate/",
        method="POST",
        intent="generate_attribution_report",
        view_type="detail",
        description="确认后为指定的已完成回测生成归因报告。",
        task_group="02 归因报告",
        sequence=40,
        fields=[
            _field(
                "backtest_id",
                "回测 ID",
                binding="body",
                input_type="number",
                value_type="integer",
                required=True,
                minimum=1,
            )
        ],
        view_model={"kind": "detail"},
        risk="write",
        effect="create",
        confirmation_required=True,
        audit_required=True,
    ),
    _action(
        key="audit.operation-log-list",
        label="操作日志",
        endpoint="/api/audit/operation-logs/",
        intent="list_owned_or_admin_operation_logs",
        view_type="datagrid",
        description="普通用户仅查看本人记录；审计管理员可查看全量记录。",
        task_group="03 操作日志",
        sequence=50,
        fields=_LOG_QUERY_FIELDS,
        view_model={
            "kind": "datagrid",
            "rows_path": "logs",
            "columns": _LOG_COLUMNS,
        },
    ),
    _action(
        key="audit.operation-log-detail",
        label="操作日志详情",
        endpoint="/api/audit/operation-logs/{log_id}/",
        intent="inspect_owned_or_admin_operation_log",
        view_type="detail",
        description="查看单次操作的请求、响应、错误和校验信息。",
        task_group="03 操作日志",
        sequence=60,
        fields=[
            _field(
                "log_id",
                "日志 ID",
                binding="path",
                required=True,
                maximum=255,
            )
        ],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.operation-log-stats",
        label="操作日志统计",
        endpoint="/api/audit/operation-logs/stats/",
        intent="inspect_operation_log_statistics",
        view_type="detail",
        description="管理员查看操作总量、错误率、耗时与分组统计。",
        task_group="03 操作日志",
        sequence=70,
        audience="admin",
        risk="admin",
        fields=[
            _field("start_date", "开始日期", input_type="date", value_type="date"),
            _field("end_date", "结束日期", input_type="date", value_type="date"),
            _field(
                "group_by",
                "分组维度",
                input_type="select",
                default="module",
                options=["module", "tool", "user", "status"],
            ),
        ],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.operation-log-export-json",
        label="导出日志证据",
        endpoint="/api/audit/operation-logs/export/",
        intent="export_operation_log_evidence",
        view_type="detail",
        description="管理员按最长 90 天范围导出 JSON 审计证据；表格另支持本地 CSV 导出。",
        task_group="03 操作日志",
        sequence=80,
        audience="admin",
        risk="admin",
        fields=[
            _field("start_date", "开始日期", input_type="date", value_type="date"),
            _field("end_date", "结束日期", input_type="date", value_type="date"),
            _field("mcp_client_id", "Token / 客户端"),
            _field(
                "format",
                "导出格式",
                input_type="select",
                default="json",
                options=["json"],
            ),
        ],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.decision-trace-list",
        label="决策链",
        endpoint="/api/audit/decision-traces/",
        intent="list_owned_or_admin_decision_traces",
        view_type="datagrid",
        description="普通用户仅查看本人决策链；审计管理员可查看全量链路。",
        task_group="04 决策链",
        sequence=90,
        fields=_TRACE_QUERY_FIELDS,
        view_model={
            "kind": "datagrid",
            "rows_path": "traces",
            "columns": _TRACE_COLUMNS,
        },
    ),
    _action(
        key="audit.decision-trace-detail",
        label="决策链详情",
        endpoint="/api/audit/decision-traces/{request_id}/",
        intent="inspect_owned_or_admin_decision_trace",
        view_type="detail",
        description="查看一次请求的完整调用步骤、状态与摘要。",
        task_group="04 决策链",
        sequence=100,
        fields=[
            _field(
                "request_id",
                "请求 ID",
                binding="path",
                required=True,
                maximum=255,
            ),
            _field("mcp_client_id", "Token / 客户端"),
        ],
        view_model={"kind": "detail"},
    ),
)
