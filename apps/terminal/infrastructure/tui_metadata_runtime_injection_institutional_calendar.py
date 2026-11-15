"""Read-only TUI metadata for source-bound institutional-calendar research."""

from __future__ import annotations

from typing import Any

_SCREEN_KEY = "research.institutional-calendar"
_ACTION_KEY = "data-center.institutional-calendar-read"
_SOURCE = "approved:runtime-institutional-calendar-research"

_ROW_COLUMNS: list[dict[str, str]] = [
    {"key": "row_kind", "label": "记录类型"},
    {"key": "event_on", "label": "日期"},
    {"key": "end_date", "label": "结束日期"},
    {"key": "title", "label": "事项"},
    {"key": "evidence_label", "label": "证据等级"},
    {"key": "lifecycle_label", "label": "生命周期"},
    {"key": "source_status", "label": "来源状态与缺口"},
    {"key": "source_url", "label": "原文链接"},
    {"key": "attribution", "label": "来源归属"},
    {"key": "source_published_at", "label": "官方标注发布时间"},
    {"key": "first_seen_at", "label": "系统首次取得原文时间"},
    {"key": "recorded_at", "label": "本版本实际入库时间"},
    {"key": "known_at", "label": "知识截止时间"},
    {"key": "knowledge_mode", "label": "知识口径"},
    {"key": "revision", "label": "修订"},
    {"key": "research_status", "label": "研究状态"},
]

RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN: dict[str, Any] = {
    "key": _SCREEN_KEY,
    "chrome_mode": "immersive",
    "dashboard_layout": "task_flow",
}

RUNTIME_INSTITUTIONAL_CALENDAR_ACTION: dict[str, Any] = {
    "key": _ACTION_KEY,
    "label": "查询机构日历与六候窗口",
    "submit_label": "查询日历",
    "endpoint": "/api/data-center/institutional-calendar/",
    "method": "GET",
    "intent": "read_institutional_calendar_research",
    "risk": "read",
    "effect": "read",
    "audience": "authenticated",
    "session_auth_required": True,
    "screen_key": _SCREEN_KEY,
    "module_key": "investment-research",
    "view_type": "datagrid",
    "description": (
        "按明确日期、UTC 知识时间和知识口径查看来源绑定的机构事件、研究缺口与六候窗口；"
        "结果仅供研究参考。"
    ),
    "source": _SOURCE,
    "task_group": "机构日历研究",
    "task_tier": "primary",
    "sequence": 10,
    "raw_debug": False,
    "fields": [
        {
            "key": "date_from",
            "label": "开始日期",
            "binding": "query",
            "input_type": "date",
            "value_type": "date",
            "required": True,
        },
        {
            "key": "date_to",
            "label": "结束日期",
            "binding": "query",
            "input_type": "date",
            "value_type": "date",
            "required": True,
        },
        {
            "key": "known_at",
            "label": "知识截止时间（UTC，必须带时区）",
            "binding": "query",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 40,
            "placeholder": "例如 2026-11-15T00:00:00Z",
        },
        {
            "key": "mode",
            "label": "知识口径",
            "binding": "query",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": [
                {"value": "system_known", "label": "系统当时已知"},
                {"value": "market_available", "label": "市场当时可得"},
            ],
        },
        {
            "key": "event_type",
            "label": "事件类型（可选）",
            "binding": "query",
            "input_type": "text",
            "value_type": "string",
            "required": False,
            "max": 240,
        },
        {
            "key": "lifecycle",
            "label": "生命周期（可选）",
            "binding": "query",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "",
            "options": [
                {"value": "", "label": "全部生命周期"},
                {"value": "scheduled", "label": "已安排"},
                {"value": "occurred", "label": "已发生"},
                {"value": "cancelled", "label": "已取消"},
                {"value": "superseded", "label": "已被修订替代"},
            ],
        },
    ],
    "view_model": {
        "kind": "datagrid",
        "rows_path": "rows",
        "columns": _ROW_COLUMNS,
        "empty_message": "当前条件下没有可核验的机构日历行；空结果不表示事项不存在。",
    },
}

RUNTIME_INSTITUTIONAL_CALENDAR_PANEL: dict[str, Any] = {
    "key": "institutional-calendar-rows",
    "title": "机构事件、来源状态与六候窗口",
    "kind": "datagrid",
    "action_key": _ACTION_KEY,
    "user_priority": "p0",
    "presentation_semantic": "primary_list",
    "layout_area": "calendar-results",
    "max_rows": 20,
    "empty_message": "请先填写日期范围、带时区的 UTC 知识截止时间和知识口径；无记录不表示没有事项。",
    "error_message": "机构日历暂不可用；请检查输入与来源覆盖后重试。",
    "stale_message": "当前研究材料可能已变化，请重新查询并核对原文与来源时间。",
    "columns": _ROW_COLUMNS,
}

RUNTIME_INSTITUTIONAL_CALENDAR_BOUNDARY_PANEL: dict[str, Any] = {
    "key": "institutional-calendar-boundary",
    "title": "研究状态与用途边界",
    "kind": "detail",
    "user_priority": "p0",
    "presentation_semantic": "primary_status",
    "target_screen": _SCREEN_KEY,
    "layout_area": "research-boundary",
    "empty_message": (
        "未来日程可能只是暂定；只有核对可验证的正式原件后才可确认。"
        "当前研究尚未完成，结果仅供参考，不用于投资或交易决策。"
        "未覆盖类别会明确列为缺口；缺少记录不等于没有事项。"
    ),
    "columns": [],
}

RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN_FRAGMENT: dict[str, Any] = {
    **RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN,
    "dashboard_panels": [
        RUNTIME_INSTITUTIONAL_CALENDAR_BOUNDARY_PANEL,
        RUNTIME_INSTITUTIONAL_CALENDAR_PANEL,
    ],
}

__all__ = [
    "RUNTIME_INSTITUTIONAL_CALENDAR_ACTION",
    "RUNTIME_INSTITUTIONAL_CALENDAR_BOUNDARY_PANEL",
    "RUNTIME_INSTITUTIONAL_CALENDAR_PANEL",
    "RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN",
    "RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN_FRAGMENT",
]
