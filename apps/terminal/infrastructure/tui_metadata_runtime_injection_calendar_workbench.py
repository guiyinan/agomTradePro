"""Runtime behavior metadata for the dedicated exchange-calendar workbench."""

from __future__ import annotations

from typing import Any

_SCREEN = "data-center.calendar-workbench"
_MODULE = "system-governance"
_SOURCE = "approved:runtime-calendar-workbench"
_ACTION_PREFIX = "data-center.calendar-workbench-"


def _field(
    key: str,
    label: str,
    *,
    binding: str,
    input_type: str = "text",
    value_type: str = "string",
    required: bool = True,
    maximum: int | None = None,
    placeholder: str | None = None,
    presentation_semantic: str | None = None,
) -> dict[str, Any]:
    """Build one explicit field without inventing a user-input default."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if maximum is not None:
        field["max"] = maximum
    if placeholder is not None:
        field["placeholder"] = placeholder
    if presentation_semantic is not None:
        field["presentation_semantic"] = presentation_semantic
    return field


def _action(
    *,
    key_suffix: str,
    label: str,
    endpoint: str,
    intent: str,
    method: str,
    effect: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    submit_label: str,
    task_tier: str,
    confirmation_required: bool,
    audit_required: bool,
    result_continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one session-protected owner action for the exact workbench task."""

    if key_suffix == "scope":
        result_view_model: dict[str, Any] = {"kind": "message"}
    elif key_suffix == "current":
        result_view_model = {
            "kind": "datagrid",
            "rows_path": "current.calendar_days",
            "columns": [
                {"key": "calendar_date", "label": "日期"},
                {"key": "calendar_state", "label": "状态"},
                {"key": "previous_open_date", "label": "前一开市日"},
            ],
        }
    else:
        result_view_model = {"kind": "detail"}
    action: dict[str, Any] = {
        "key": _ACTION_PREFIX + key_suffix,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin" if effect == "read" else "write",
        "audience": "admin",
        "effect": effect,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "交易日历工作台",
        "sequence": sequence,
        "task_tier": task_tier,
        "fields": fields,
        "view_model": result_view_model,
        "result_semantics": ["primary_status"],
        "submit_label": submit_label,
        "session_auth_required": True,
        "raw_debug": False,
        "confirmation_required": confirmation_required,
        "audit_required": audit_required,
    }
    if result_continuation is not None:
        action["result_continuation"] = result_continuation
    return action


RUNTIME_CALENDAR_WORKBENCH_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key_suffix="scope",
        label="查看日历配置状态",
        endpoint="/api/data-center/exchange-calendars/workbench/scope/",
        intent="read_calendar_workbench_scope",
        method="GET",
        effect="read",
        description="查看日历数据集、合同、策略和服务商的安全配置状态。",
        sequence=10,
        fields=[],
        submit_label="读取状态",
        task_tier="primary",
        confirmation_required=False,
        audit_required=False,
    ),
    _action(
        key_suffix="current",
        label="查看指定交易所当前日历",
        endpoint="/api/data-center/exchange-calendars/workbench/current/",
        intent="read_current_exchange_calendar_reference",
        method="GET",
        effect="read",
        description="输入明确的交易所标识，查看该交易所当前已发布的参考日历。",
        sequence=20,
        fields=[
            _field(
                "exchange",
                "交易所标识",
                binding="query",
                maximum=32,
                placeholder="输入交易所标识",
            )
        ],
        submit_label="查看日历",
        task_tier="primary",
        confirmation_required=False,
        audit_required=False,
    ),
    _action(
        key_suffix="prepare",
        label="准备日历发布预览",
        endpoint="/api/data-center/exchange-calendars/workbench/prepare/",
        intent="prepare_exchange_calendar_publication_preview",
        method="POST",
        effect="create",
        description="按明确的交易所和完整日期范围获取日历快照并准备发布预览。",
        sequence=30,
        fields=[
            _field(
                "exchange",
                "交易所标识",
                binding="body",
                maximum=32,
                placeholder="输入交易所标识",
            ),
            _field(
                "coverage_start",
                "覆盖开始日期",
                binding="body",
                input_type="date",
                value_type="date",
            ),
            _field(
                "coverage_end",
                "覆盖结束日期",
                binding="body",
                input_type="date",
                value_type="date",
            ),
        ],
        submit_label="准备预览",
        task_tier="operation",
        confirmation_required=True,
        audit_required=True,
        result_continuation={
            "target_action_key": _ACTION_PREFIX + "confirm",
            "field_map": {"confirmation_token": "confirmation_token"},
        },
    ),
    _action(
        key_suffix="confirm",
        label="确认发布日历预览",
        endpoint="/api/data-center/exchange-calendars/workbench/confirm/",
        intent="confirm_exchange_calendar_publication_preview",
        method="POST",
        effect="create",
        description="复核预览后确认发布；预览过期或权限失效时需要重新准备。",
        sequence=40,
        fields=[
            _field(
                "confirmation_token",
                "发布确认",
                binding="body",
                input_type="hidden",
                presentation_semantic="api_token",
            )
        ],
        submit_label="确认发布",
        task_tier="operation",
        confirmation_required=True,
        audit_required=True,
    ),
)


RUNTIME_CALENDAR_WORKBENCH_SCREEN: dict[str, Any] = {
    "key": _SCREEN,
    "dashboard_layout": "task_flow",
    "workflow": {
        "name": "交易日历参考发布",
        "label": "交易日历工作台",
        "role": "检查配置和当前参考日历，按明确范围准备并确认参考版本。",
        "previous": {"key": "api-library.data-center", "label": "数据与系统健康"},
        "next": {"key": "data-center.egress-config", "label": "数据出口配置"},
    },
    "business_context": {
        "objective": "让管理员核对唯一日历配置和当前参考版本，并完成明确范围的准备与发布。",
        "decision_output": "当前参考日历范围和发布状态；所有结果仅供参考，不用于交易或投资决策。",
        "checkpoints": [
            "先查看日历配置状态；元数据已选中不代表密钥或运行连接已经验证。",
            "输入明确交易所标识后查看当前已发布参考日历。",
            "需要更新时填写交易所和完整日期范围，准备预览并检查范围。",
            "在预览有效期内明确确认；预览过期或权限失效时重新准备。",
        ],
    },
    "dashboard_panels": [
        {
            "key": "calendar-capture-scope",
            "title": "一、日历配置状态",
            "kind": "detail",
            "action_key": _ACTION_PREFIX + "scope",
            "user_priority": "p0",
            "presentation_semantic": "primary_status",
            "layout_area": "configuration",
            "target_screen": _SCREEN,
            "empty_message": "尚未读取日历配置状态。",
            "error_message": "日历配置状态暂不可用，请检查管理员配置后重试。",
            "stale_message": "配置状态可能已变化，请重新读取后再准备预览。",
            "columns": [],
        },
        {
            "key": "calendar-current-reference",
            "title": "二、当前参考日历",
            "kind": "datagrid",
            "action_key": _ACTION_PREFIX + "current",
            "user_priority": "p0",
            "presentation_semantic": "primary_list",
            "layout_area": "current-reference",
            "target_screen": _SCREEN,
            "empty_message": "请输入明确的交易所标识后查看当前参考日历；无当前版本时可准备预览。",
            "error_message": "当前参考日历暂不可用，请检查交易所标识或配置状态。",
            "stale_message": "当前参考状态可能已变化，请重新读取。",
            "columns": [
                {"key": "calendar_date", "label": "日期"},
                {"key": "calendar_state", "label": "状态"},
                {"key": "previous_open_date", "label": "前一开市日"},
            ],
        },
        {
            "key": "calendar-reference-boundary",
            "title": "参考数据用途",
            "kind": "detail",
            "user_priority": "p0",
            "presentation_semantic": "primary_status",
            "layout_area": "reference-boundary",
            "target_screen": _SCREEN,
            "empty_message": "交易日历仅作为参考；当前链路没有盘中状态能力，不可用于交易或投资决策。",
            "columns": [],
        },
    ],
}


__all__ = [
    "RUNTIME_CALENDAR_WORKBENCH_ACTIONS",
    "RUNTIME_CALENDAR_WORKBENCH_SCREEN",
]
