"""Runtime TUI metadata for the Macro-owned trend-filter replacement."""

from __future__ import annotations

from typing import Any

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-macro-trend-filter"
_ENDPOINT = "/api/macro/tui/trend-filter/"


def _fields() -> list[dict[str, Any]]:
    """Return bounded scalar fields shared by all trend-filter views."""

    return [
        {
            "key": "indicator_code",
            "label": "宏观指标代码",
            "binding": "query",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "default": "",
            "max": 80,
        },
        {
            "key": "filter_type",
            "label": "趋势算法",
            "binding": "query",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "HP",
            "options": ["HP", "KALMAN"],
        },
        {
            "key": "limit",
            "label": "历史点数",
            "binding": "query",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "default": 120,
            "min": 12,
            "max": 500,
        },
    ]


def _action(
    *,
    key: str,
    label: str,
    intent: str,
    view_type: str,
    description: str,
    sequence: int,
    view_model: dict[str, Any],
) -> dict[str, Any]:
    """Build one read-only Macro trend-filter task."""

    return {
        "key": key,
        "label": label,
        "endpoint": _ENDPOINT,
        "method": "GET",
        "intent": intent,
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "05 宏观趋势",
        "sequence": sequence,
        "task_tier": "support",
        "fields": _fields(),
        "view_model": view_model,
    }


RUNTIME_MACRO_TREND_FILTER_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="macro.trend-filter-summary",
        label="宏观趋势摘要",
        intent="inspect_macro_trend_filter_summary",
        view_type="detail",
        description="查看指标、算法、样本区间、新鲜度和决策可用性。",
        sequence=510,
        view_model={
            "kind": "detail",
            "title_path": "summary.indicator_name",
            "status_path": "summary.decision_grade",
        },
    ),
    _action(
        key="macro.trend-filter-chart",
        label="原始值与长期趋势",
        intent="chart_macro_original_and_trend",
        view_type="chart",
        description="使用扩张窗口 HP 或单向 Kalman 比较原始值与长期趋势。",
        sequence=520,
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "rows",
            "columns": [
                {"key": "period", "label": "报告期"},
                {"key": "original", "label": "原始值"},
                {"key": "trend", "label": "长期趋势"},
            ],
        },
    ),
    _action(
        key="macro.trend-filter-components",
        label="周期分量与趋势斜率",
        intent="chart_macro_cycle_and_slope",
        view_type="chart",
        description="查看原始值偏离趋势的周期分量；Kalman 模式同时显示趋势斜率。",
        sequence=530,
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "rows",
            "columns": [
                {"key": "period", "label": "报告期"},
                {"key": "cycle", "label": "周期分量"},
                {"key": "slope", "label": "趋势斜率"},
            ],
        },
    ),
)


__all__ = ["RUNTIME_MACRO_TREND_FILTER_ACTIONS"]
