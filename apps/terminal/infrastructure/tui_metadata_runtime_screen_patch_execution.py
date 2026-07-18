"""Runtime screen patches for execution and risk-control TUI surfaces."""

from __future__ import annotations

from typing import Any


RUNTIME_SCREEN_PATCHES_EXECUTION: dict[str, dict[str, Any]] = {
    "execution.accounts": {
        "label": "账户清单与当前持仓",
        "summary": "集中查看当前账户清单、组合、持仓和账户级绩效检查。",
        "business_context": {
            "objective": "在执行前确认当前账户、现金、组合和持仓都支持今天的动作。",
            "decision_output": "账户与持仓检查结论：可执行、资金不足、持仓冲突或需调整账户。",
            "checkpoints": [
                "先看账户清单，确认账户名称、类型、现金和总资产。",
                "再看当前持仓，确认资产代码、名称、数量、市值和浮动盈亏。",
                "需要单账户明细时，用账户下拉选择后查看账户持仓和绩效。",
            ],
        },
    },
    "execution.account-settings": {
        "default_action_key": "operator.governance.account_settings_summary",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先确认是否存在会阻断执行的账户参数问题，再决定进入哪类配置修正。",
            "primary_outcome": "明确当前是否可执行，以及分类、仓位、成本等哪一类参数需要先修正。",
            "empty_state_hint": "先看执行阻断参数，再继续打开宏观仓位和交易成本配置。",
            "next_step_hint": "修正阻断参数后，再回到执行主线或进入配置中心治理。",
        },
        "workflow": {
            "name": "系统治理流程",
            "lane": "governance",
            "step": 5,
            "total": 6,
            "label": "执行参数",
            "role": "确认会阻断执行的参数异常，再进入分类、汇率和成本明细。",
            "previous": {"key": "ai-ops.agent-runtime", "label": "智能任务运行时治理"},
            "next": {"key": "api-library.config-center", "label": "配置中心治理"},
        },
        "business_context": {
            "objective": "先看会阻断执行的参数异常，再决定是否进入分类、汇率、成本或观察授权明细。",
            "decision_output": "执行参数结论：可执行、缺少分类或币种、没有组合或需要补配置。",
            "checkpoints": [
                "先看治理摘要，确认是否存在会阻断执行的前置条件。",
                "再看宏观仓位、交易成本、分类和汇率等具体参数。",
                "参数修正后再回到执行或决策主线。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "account-settings-governance-summary",
                "title": "一、执行阻断参数",
                "kind": "datagrid",
                "action_key": "operator.governance.account_settings_summary",
                "max_rows": 8,
                "layout_area": "governance_summary",
                "target_screen": "execution.account-settings",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
                "columns": [
                    {"key": "severity", "label": "级别"},
                    {"key": "title", "label": "异常项"},
                    {"key": "status", "label": "状态"},
                    {"key": "blocking_reason", "label": "原因"},
                    {"key": "next_action", "label": "下一步"},
                ],
            },
            {
                "key": "account-settings-macro-sizing",
                "title": "二、宏观仓位参数",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.account.macro-sizing-config",
                "max_rows": 6,
                "layout_area": "macro_sizing",
                "target_screen": "execution.account-settings",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
            {
                "key": "account-settings-trading-cost",
                "title": "三、交易成本配置",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.account.trading-cost-configs",
                "max_rows": 6,
                "layout_area": "trading_cost",
                "target_screen": "execution.account-settings",
                "user_priority": "p2",
                "presentation_semantic": "supporting_list",
            },
        ],
    },
    "execution.events": {
        "default_action_key": "auto.api.get.api.events.query",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先判断事件总线今天是否正常，再决定是否需要检查指标或运行状态。",
            "primary_outcome": "明确事件链路是否正常、是否堆积，以及是否需要排查订阅端和运行状态。",
            "empty_state_hint": "先看最近事件，再看事件指标和运行状态，不从底层实现细节入手。",
            "next_step_hint": "若发现堆积或失败升高，继续进入运行状态和订阅端排查。",
        },
        "business_context": {
            "objective": "先看最近事件，再核对事件指标和运行状态，判断事件总线是否支持当前执行链路。",
            "decision_output": "事件结论：正常、堆积、失败升高或需要排查订阅端。",
            "checkpoints": [
                "先看最近事件，确认是否持续产出和消费。",
                "再看事件指标，确认失败数、成功率和处理耗时。",
                "最后看运行状态，确认队列大小和订阅端数量。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "events-query",
                "title": "一、最近事件",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.events.query",
                "max_rows": 8,
                "layout_area": "events",
                "target_screen": "execution.events",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            },
            {
                "key": "events-metrics",
                "title": "二、事件指标",
                "kind": "detail",
                "action_key": "auto.api.get.api.events.metrics",
                "layout_area": "metrics",
                "target_screen": "execution.events",
                "user_priority": "p1",
                "presentation_semantic": "supporting_detail",
            },
            {
                "key": "events-status",
                "title": "三、事件状态",
                "kind": "detail",
                "action_key": "auto.api.get.api.events.status",
                "layout_area": "status",
                "target_screen": "execution.events",
                "user_priority": "p1",
                "presentation_semantic": "primary_status",
            },
        ],
    },
    "execution.share": {
        "default_action_key": "auto.api.get.api.share.links",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先确认分享入口是否仍可用，再决定是否继续看详情、日志或快照。",
            "primary_outcome": "明确分享链接是否正常、是否受限，以及是否需要重新生成或排查公开访问。",
            "empty_state_hint": "先看分享链接列表，再从选中记录进入详情、日志或快照。",
            "next_step_hint": "若链接异常或访问受限，继续检查分享详情、快照和访问记录。",
        },
        "business_context": {
            "objective": "先看分享链接，再沿着同屏详情、日志和快照动作检查分享链路是否可用。",
            "decision_output": "分享结论：链接正常、访问受限、快照缺失或需要重新生成公开入口。",
            "checkpoints": [
                "先看分享链接列表，确认短码、主题和所属账户。",
                "再从选中行进入详情、日志、快照或统计。",
                "公开访问需要短码和密码时，用专门的验证访问动作处理。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "share-links",
                "title": "一、分享链接",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.share.links",
                "max_rows": 8,
                "layout_area": "links",
                "target_screen": "execution.share",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            }
        ],
    },
    "risk-center.overview": {
        "default_action_key": "risk-center.effective-policy",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先确认账户的有效风控底线，再决定是否继续查看策略与模板。",
            "primary_outcome": "明确当前账户适用的风控底线、策略覆盖情况，以及是否需要调整模板。",
            "empty_state_hint": "先选择账户，再查看全局底线、账户策略和风险模板。",
            "next_step_hint": "确认有效底线后，再继续执行预检、例外申请或日常报告动作。",
        },
        "dashboard_panels": [
            {
                "key": "risk-center-floor",
                "title": "一、全局底线",
                "kind": "detail",
                "action_key": "risk-center.floor",
                "layout_area": "floor",
                "target_screen": "risk-center.overview",
                "user_priority": "p0",
                "presentation_semantic": "primary_status",
            },
            {
                "key": "risk-center-account-policies",
                "title": "二、账户策略",
                "kind": "datagrid",
                "action_key": "risk-center.account-policies",
                "max_rows": 8,
                "layout_area": "policies",
                "target_screen": "risk-center.overview",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
            {
                "key": "risk-center-templates",
                "title": "三、风险模板",
                "kind": "datagrid",
                "action_key": "risk-center.templates",
                "max_rows": 6,
                "layout_area": "templates",
                "target_screen": "risk-center.overview",
                "user_priority": "p2",
                "presentation_semantic": "supporting_list",
            },
        ],
    },
}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_EXECUTION: dict[str, set[str]] = {
    "execution.events": {"auto.api.get.api.events"},
    "execution.share": {"auto.api.get.api.share"},
}
