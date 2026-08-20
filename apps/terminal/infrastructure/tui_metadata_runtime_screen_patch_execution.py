"""Runtime screen patches for execution and risk-control TUI surfaces."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_EXECUTION: dict[str, dict[str, Any]] = {
    "execution.accounts": {
        "label": "账户清单与当前持仓",
        "summary": "集中查看账户、持仓、实盘连接、订单和执行就绪状态。",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先确认本地连接和实盘门禁，再处理待确认订单。",
            "primary_outcome": "得到可交易、需复核、已停止或离线的明确结论。",
            "empty_state_hint": "若本地连接为空，请先完成 Windows Agent 和账户绑定。",
            "next_step_hint": "连接正常后复核待确认订单；出现异常时先停止并对账。",
        },
        "business_context": {
            "objective": "在执行前确认当前账户、现金、组合和持仓都支持今天的动作。",
            "decision_output": "账户与持仓检查结论：可执行、资金不足、持仓冲突或需调整账户。",
            "checkpoints": [
                "先看账户清单，确认账户名称、类型、现金和总资产。",
                "再看当前持仓，确认资产代码、名称、数量、市值和浮动盈亏。",
                "需要单账户明细时，用账户下拉选择后查看账户持仓和绩效。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "simulated-accounts",
                "title": "我的投资账户",
                "kind": "datagrid",
                "action_key": "simulated-trading.accounts",
                "max_rows": 8,
                "layout_area": "simulated_accounts",
                "target_screen": "execution.accounts",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            },
            {
                "key": "broker-execution-readiness",
                "title": "实盘就绪结论",
                "kind": "detail",
                "action_key": "broker-execution.overview",
                "layout_area": "broker_readiness",
                "target_screen": "execution.accounts",
                "user_priority": "p0",
                "presentation_semantic": "primary_status",
            },
            {
                "key": "broker-execution-orders",
                "title": "待确认与执行中订单",
                "kind": "datagrid",
                "action_key": "broker-execution.order-list",
                "max_rows": 8,
                "layout_area": "broker_orders",
                "target_screen": "execution.accounts",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            },
            {
                "key": "broker-execution-connections",
                "title": "本地连接",
                "kind": "datagrid",
                "action_key": "broker-execution.connection-status",
                "max_rows": 6,
                "layout_area": "broker_connections",
                "target_screen": "execution.accounts",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
        ],
    },
}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_EXECUTION: dict[str, set[str]] = {
    "broker-execution.qmt-setup": {"auto.api.get.api.broker-execution.qmt-onboarding"},
    "execution.accounts": {"auto.api.get.api.account.positions"},
    "execution.events": {"auto.api.get.api.events"},
    "execution.share": {"auto.api.get.api.share"},
}
