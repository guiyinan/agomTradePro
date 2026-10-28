"""Runtime action patches for account, portfolio, and execution TUI actions."""

from __future__ import annotations

from typing import Any

RUNTIME_ACTION_PATCHES_EXECUTION: dict[str, dict[str, Any]] = {
    "auto.api.get.api.decision.workspace.recommendations": {
        "label": "查看账户统一推荐",
        "description": "读取所选账户的统一推荐、置信度及推荐依据与限制。",
        "fields": [
            {
                "key": "account_id",
                "label": "账户编号",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            },
            {
                "key": "status",
                "label": "推荐状态",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
            {
                "key": "page",
                "label": "页码",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "min": 1,
            },
            {
                "key": "page_size",
                "label": "每页条数",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "min": 1,
                "max": 200,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "columns": [
                {"key": "security_code", "label": "标的"},
                {"key": "side", "label": "方向"},
                {"key": "confidence", "label": "置信度（0–1）"},
                {"key": "human_rationale", "label": "推荐依据与限制"},
                {"key": "status", "label": "推荐状态"},
            ],
        },
    },
    "decision.workspace.summary": {
        "fields": [
            {
                "key": "account_id",
                "label": "账户编号",
                "binding": "query",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            }
        ],
    },
    "auto.api.get.api.account.accounts": {
        "task_group": "01 账户清单",
        "sequence": 100,
        "task_tier": "primary",
        "view_model": {"rows_path": "accounts", "total_path": "count"},
    },
    "account.position-list": {
        "screen_key": "execution.accounts",
        "task_group": "02 当前持仓",
        "sequence": 110,
        "task_tier": "primary",
    },
    "param.api.get.api.account.accounts.int.account_id.positions": {
        "screen_key": "execution.accounts",
        "task_group": "03 单账户持仓",
        "sequence": 120,
        "task_tier": "primary",
    },
    "param.api.get.api.account.accounts.int.account_id.performance": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.performance-report": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.valuation-snapshot": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.valuation-timeline": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.benchmarks": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.equity-curve": {
        "screen_key": "execution.accounts"
    },
    "param.api.get.api.account.accounts.int.account_id.inspections": {
        "screen_key": "execution.accounts"
    },
    "auto.api.get.api.strategy.assignments.by_portfolio": {
        "screen_key": "execution.portfolio-performance"
    },
    "auto.api.get.api.strategy.execution-logs.by_portfolio": {
        "screen_key": "execution.portfolio-performance"
    },
}
