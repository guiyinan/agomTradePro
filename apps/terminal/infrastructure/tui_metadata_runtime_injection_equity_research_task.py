"""Runtime metadata for one read-only equity research task."""

from __future__ import annotations

from typing import Any

RUNTIME_EQUITY_RESEARCH_TASK_SCREEN: dict[str, Any] = {
    "key": "task.asset-research",
}

RUNTIME_EQUITY_RESEARCH_TASK_ACTION: dict[str, Any] = {
    "key": "equity.research-snapshot",
    "label": "单标的研究快照",
    "submit_label": "开始研究",
    "endpoint": "/api/equity/research-snapshot/<str:stock_code>/",
    "method": "GET",
    "intent": "research_single_equity_snapshot",
    "risk": "read",
    "effect": "read",
    "audience": "authenticated",
    "screen_key": "task.asset-research",
    "module_key": "investment-research",
    "view_type": "detail",
    "description": "读取已有研究材料，保留来源时间、缺口和决策限制。",
    "source": "approved:runtime-equity-research-task",
    "task_group": "01 研究标的",
    "task_tier": "primary",
    "sequence": 10,
    "raw_debug": False,
    "fields": [
        {
            "key": "stock_code",
            "label": "股票名称或代码",
            "binding": "path",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "default": "",
            "max": 32,
            "placeholder": "例如 600000.SH；或证券主数据中的唯一名称",
        }
    ],
    "view_model": {"kind": "detail"},
}

__all__ = [
    "RUNTIME_EQUITY_RESEARCH_TASK_ACTION",
    "RUNTIME_EQUITY_RESEARCH_TASK_SCREEN",
]
