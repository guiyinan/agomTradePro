"""Runtime TUI metadata for factor calculation and explanation."""

from __future__ import annotations

from typing import Any

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-factor-calculate"

RUNTIME_FACTOR_CALCULATE_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "factor.calculate-config",
        "label": "按配置计算因子分数",
        "endpoint": "/api/factor/calculate-config/",
        "method": "POST",
        "intent": "calculate_factor_scores_for_config",
        "risk": "write",
        "audience": "authenticated",
        "effect": "execute",
        "confirmation_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按已存组合配置、交易日和返回数量计算股票因子分数。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 700,
        "task_tier": "operation",
        "fields": [
            {
                "key": "config_id",
                "label": "组合配置 ID",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            },
            {
                "key": "trade_date",
                "label": "交易日（留空取当前日）",
                "binding": "body",
                "input_type": "date",
                "value_type": "date",
                "required": False,
            },
            {
                "key": "top_n",
                "label": "返回数量",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "default": 30,
                "min": 1,
                "max": 100,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "scores",
            "columns": [
                {"key": "rank", "label": "排名"},
                {"key": "stock_code", "label": "证券代码"},
                {"key": "stock_name", "label": "名称"},
                {"key": "composite_score", "label": "综合分"},
                {"key": "percentile_rank", "label": "百分位"},
                {"key": "sector", "label": "行业"},
            ],
        },
    },
    {
        "key": "factor.explain-config-stock",
        "label": "解释个股因子分数",
        "endpoint": "/api/factor/explain-config/",
        "method": "POST",
        "intent": "explain_factor_score_for_config",
        "risk": "write",
        "audience": "authenticated",
        "effect": "execute",
        "confirmation_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "使用指定组合配置解释一只股票的因子分数与贡献。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 710,
        "task_tier": "operation",
        "fields": [
            {
                "key": "config_id",
                "label": "组合配置 ID",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            },
            {
                "key": "stock_code",
                "label": "证券代码",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
            },
        ],
        "view_model": {
            "kind": "detail",
            "title_path": "explanation.stock_code",
            "status_path": "success",
        },
    },
)
