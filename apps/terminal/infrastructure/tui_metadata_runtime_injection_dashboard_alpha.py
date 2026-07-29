"""Runtime TUI metadata for Dashboard Alpha ranking and history."""

from __future__ import annotations

from typing import Any

from apps.alpha.application.pool_resolver import ALPHA_POOL_MODE_CHOICES
from apps.dashboard.application.alpha_homepage import ALPHA_SCOPE_CHOICES

_SCREEN = "research.signals"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-dashboard-alpha"

RUNTIME_DASHBOARD_ALPHA_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "dashboard.alpha-ranking",
        "label": "查看完整 Alpha 排名",
        "endpoint": "/api/dashboard/alpha/stocks/",
        "method": "GET",
        "intent": "read_dashboard_alpha_ranking",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按通用或组合口径查看完整 Alpha 排名及新鲜度、池范围和证伪摘要。",
        "source": _SOURCE,
        "task_group": "02 Alpha 候选",
        "sequence": 240,
        "task_tier": "operation",
        "fields": [
            {
                "key": "format",
                "label": "响应格式",
                "binding": "query",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "default": "json",
            },
            {
                "key": "alpha_scope",
                "label": "Alpha 范围",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "default": "portfolio",
                "options": sorted(ALPHA_SCOPE_CHOICES),
            },
            {
                "key": "portfolio_id",
                "label": "组合 ID",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "min": 1,
            },
            {
                "key": "pool_mode",
                "label": "股票池口径",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "default": "price_covered",
                "options": [
                    {"value": value, "label": label}
                    for value, label in ALPHA_POOL_MODE_CHOICES
                ],
            },
            {
                "key": "top_n",
                "label": "返回数量",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "default": 200,
                "min": 1,
                "max": 500,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "data.items",
            "columns": [
                {"key": "rank", "label": "排名"},
                {"key": "code", "label": "证券代码"},
                {"key": "name", "label": "名称"},
                {"key": "alpha_score", "label": "Alpha"},
                {"key": "confidence", "label": "置信度"},
                {"key": "stage_label", "label": "阶段"},
                {"key": "source", "label": "来源"},
                {"key": "asof_date", "label": "评分日"},
            ],
        },
    },
    {
        "key": "dashboard.alpha-history",
        "label": "查看 Alpha 推荐历史",
        "endpoint": "/api/dashboard/alpha/history/",
        "method": "GET",
        "intent": "list_dashboard_alpha_history",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按组合、日期、证券、阶段和来源回看当前用户的 Alpha 推荐快照。",
        "source": _SOURCE,
        "task_group": "02 Alpha 候选",
        "sequence": 250,
        "task_tier": "support",
        "fields": [
            {
                "key": "portfolio_id",
                "label": "组合 ID",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "min": 1,
            },
            {
                "key": "trade_date",
                "label": "交易日",
                "binding": "query",
                "input_type": "date",
                "value_type": "date",
                "required": False,
            },
            {
                "key": "stock_code",
                "label": "证券代码",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
            {
                "key": "stage",
                "label": "阶段",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
            {
                "key": "source",
                "label": "来源",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "data",
            "columns": [
                {"key": "id", "label": "运行 ID"},
                {"key": "trade_date", "label": "交易日"},
                {"key": "scope_label", "label": "范围"},
                {"key": "source", "label": "来源"},
                {"key": "provider_source", "label": "服务商"},
                {"key": "effective_asof_date", "label": "评分日"},
                {"key": "uses_cached_data", "label": "使用缓存"},
            ],
        },
    },
    {
        "key": "dashboard.alpha-history-detail",
        "label": "查看 Alpha 历史详情",
        "endpoint": "/api/dashboard/alpha/history/<int:run_id>/",
        "method": "GET",
        "intent": "read_dashboard_alpha_history_detail",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看一条属于当前用户的历史推荐运行及其完整候选明细。",
        "source": _SOURCE,
        "task_group": "02 Alpha 候选",
        "sequence": 260,
        "task_tier": "support",
        "fields": [
            {
                "key": "run_id",
                "label": "运行 ID",
                "binding": "path",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            }
        ],
        "view_model": {
            "kind": "detail",
            "title_path": "data.trade_date",
            "status_path": "success",
        },
    },
)
