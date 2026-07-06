"""Runtime TUI metadata injection constants for auto-advisor surfaces."""

from __future__ import annotations

from typing import Any


RUNTIME_ADVISOR_SCREEN: dict[str, Any] = {
    "key": "command-center.auto-advisor",
    "label": "自动投顾",
    "module_key": "command-center",
    "group": "workflow",
    "summary": "按账户读取持仓驱动的今日建议单和建议订单清单。",
    "view_type": "datagrid",
    "default_action_key": "advisor.account_selector",
    "business_context": {
        "objective": "确认一个账户今天是否行动、下多少单、每单怎么下。",
        "decision_output": "账户级结论、持仓摘要、建议订单清单和阻断项。",
        "checkpoints": [
            "先选账户，再进入今日建议单。",
            "优先检查减仓、清仓和阻断项。",
            "新增买入只在现金、价格和风控允许时展示。",
        ],
    },
}

RUNTIME_ADVISOR_SELECTOR_ACTION: dict[str, Any] = {
    "key": "advisor.account_selector",
    "label": "账户选择",
    "endpoint": "/api/account/accounts/",
    "method": "GET",
    "intent": "read_account_selector_for_auto_advisor",
    "risk": "read",
    "screen_key": "command-center.auto-advisor",
    "view_type": "datagrid",
    "description": "先选账户，再继续查看该账户的今日自动投顾建议单。",
    "source": "approved:runtime-advisor",
    "task_group": "01 账户选择",
    "sequence": 90,
    "task_tier": "primary",
    "fields": [],
    "view_model": {
        "rows_path": "accounts",
        "total_path": "count",
    },
}

RUNTIME_ADVISOR_ACTION: dict[str, Any] = {
    "key": "advisor.today_sheet",
    "label": "今日自动投顾建议单",
    "endpoint": "/api/decision/advisor/sheet/",
    "method": "GET",
    "intent": "auto_safe_read_candidate",
    "risk_level": "read",
    "screen_key": "command-center.auto-advisor",
    "view_type": "datagrid",
    "description": "按 account_id 读取账户级持仓、配置偏离和建议订单清单。",
    "source": "approved:runtime-advisor",
    "task_group": "01 自动投顾",
    "sequence": 100,
    "task_tier": "primary",
    "fields": [
        {
            "key": "account_id",
            "label": "账户 ID",
            "input_type": "text",
            "required": True,
            "default": "",
            "placeholder": "输入账户 ID",
            "binding": "query",
            "value_type": "string",
        }
    ],
    "view_model": {
        "kind": "datagrid",
        "rows_path": "data.order_intents",
        "total_path": "data.order_summary.total",
        "status_path": "data.today_conclusion",
        "title_path": "data.account.account_name",
    },
}
