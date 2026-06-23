"""Promote smoke-passing TUI tool actions into user-task screens."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.terminal.application.tui_metadata import (
    compact_tui_metadata_payload,
    validate_tui_metadata,
)


SCREEN_SPECS = {
    "command-center.decision-flow": {
        "key": "command-center.decision-flow",
        "label": "每日决策流程",
        "module_key": "command-center",
        "group": "workflow",
        "summary": "按环境、信号、约束、建议和复盘顺序检查当天是否应该行动。",
        "view_type": "detail",
        "status": "online",
        "default_action_key": "auto.api.get.api.decision.context.step1",
    },
    "execution.accounts": {
        "key": "execution.accounts",
        "label": "账户与组合检查",
        "module_key": "execution",
        "group": "execution",
        "summary": "查看账户健康、组合、持仓、流水、资产和交易成本，作为执行前检查。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.account.accounts",
    },
    "execution.trading-ledger": {
        "key": "execution.trading-ledger",
        "label": "持仓与交易流水",
        "module_key": "execution",
        "group": "execution",
        "summary": "查看持仓、交易流水、资金流水和模拟交易记录，确认执行结果是否落账。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "execution.trading-ledger.account-selector",
    },
    "execution.portfolio-performance": {
        "key": "execution.portfolio-performance",
        "label": "组合绩效与估值",
        "module_key": "execution",
        "group": "execution",
        "summary": "查看账户和组合绩效、估值快照、净值曲线、基准和检查记录。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.account.portfolios",
    },
    "execution.account-settings": {
        "key": "execution.account-settings",
        "label": "账户参数与权限",
        "module_key": "execution",
        "group": "execution",
        "summary": "维护执行前需要核对的资产分类、币种、汇率、成本、观察授权和仓位测算参数。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.account.categories",
    },
    "macro-regime.strategy": {
        "key": "macro-regime.strategy",
        "label": "策略与仓位规则",
        "module_key": "macro-regime",
        "group": "macro",
        "summary": "查看策略清单、仓位规则、执行记录和策略绑定状态。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.strategy.strategies",
    },
    "macro-regime.rotation": {
        "key": "macro-regime.rotation",
        "label": "轮动与配置",
        "module_key": "macro-regime",
        "group": "macro",
        "summary": "查看轮动资产、信号、模板、账户配置和最新配置建议。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.rotation.assets",
    },
    "macro-regime.risk-controls": {
        "key": "macro-regime.risk-controls",
        "label": "节奏与对冲风控",
        "module_key": "macro-regime",
        "group": "macro",
        "summary": "查看决策频率、Beta Gate、对冲组合和主动风控提醒。",
        "view_type": "status",
        "status": "online",
        "default_action_key": "auto.api.get.api.decision-rhythm.summary",
    },
    "macro-regime.beta-gate": {
        "key": "macro-regime.beta-gate",
        "label": "Beta Gate 放行检查",
        "module_key": "macro-regime",
        "group": "macro",
        "summary": "查看 Beta Gate 状态、配置、决策记录、标的池和版本对比，判断市场暴露是否放行。",
        "view_type": "status",
        "status": "online",
        "default_action_key": "auto.api.get.api.beta-gate",
    },
    "macro-regime.hedge": {
        "key": "macro-regime.hedge",
        "label": "对冲与主动预警",
        "module_key": "macro-regime",
        "group": "macro",
        "summary": "查看对冲组合、相关性、快照、有效性和当前预警，判断是否需要降风险或对冲。",
        "view_type": "status",
        "status": "online",
        "default_action_key": "auto.api.get.api.hedge.snapshots",
    },
    "research.asset-lab": {
        "key": "research.asset-lab",
        "label": "资产与市场研究",
        "module_key": "research",
        "group": "research",
        "summary": "查看资产池、基金、板块、情绪和筛选器，作为研究入口。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.asset-analysis.pool-summary",
    },
    "research.alpha-triggers": {
        "key": "research.alpha-triggers",
        "label": "Alpha 触发器",
        "module_key": "research",
        "group": "research",
        "summary": "查看 Alpha 触发器、候选池、观察列表和绩效统计，跟踪离散触发后的研究动作。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.alpha-triggers.candidates.statistics",
    },
    "research.fund-sector": {
        "key": "research.fund-sector",
        "label": "基金与板块研究",
        "module_key": "research",
        "group": "research",
        "summary": "查看基金排行、基金池和板块信息，补充资产研究的横向比较。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.fund.rank",
    },
    "research.screening-sentiment": {
        "key": "research.screening-sentiment",
        "label": "筛选器与情绪观察",
        "module_key": "research",
        "group": "research",
        "summary": "查看筛选器、筛选指标、情绪指数和情绪健康，用于候选过滤和风险提示。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.filter.indicators",
    },
    "ai-ops.prompt-workbench": {
        "key": "ai-ops.prompt-workbench",
        "label": "Prompt 与模型配置",
        "module_key": "ai-ops",
        "group": "ops",
        "summary": "查看 AI Provider、Prompt 模板、链路、日志和可用模型。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.prompt.templates",
    },
    "ai-ops.providers": {
        "key": "ai-ops.providers",
        "label": "AI 服务商与用量",
        "module_key": "ai-ops",
        "group": "ops",
        "summary": "查看我的 AI 服务商、模型、调用日志和配额状态，确认 AI 助手是否可用。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.prompt.chat.providers",
    },
    "ai-ops.terminal": {
        "key": "ai-ops.terminal",
        "label": "AI 交互终端",
        "module_key": "ai-ops",
        "group": "ops",
        "summary": "用自然语言询问系统状态、生成说明或执行已授权的终端任务。",
        "view_type": "detail",
        "status": "online",
        "default_action_key": "terminal.chat_router",
    },
    "api-library.runtime": {
        "key": "api-library.runtime",
        "label": "系统运行状态",
        "module_key": "api-library",
        "group": "system",
        "summary": "查看健康检查、Celery、基础系统状态和初始化检查。",
        "view_type": "status",
        "status": "online",
        "default_action_key": "auto.api.get.api.health",
    },
    "api-library.config-center": {
        "key": "api-library.config-center",
        "label": "Qlib 训练配置",
        "module_key": "api-library",
        "group": "system",
        "summary": "查看和维护 Qlib 运行配置、训练模板和训练运行记录。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "config_center.qlib_runtime",
    },
    "api-library.data-center": {
        "key": "api-library.data-center",
        "label": "数据中心",
        "module_key": "api-library",
        "group": "system",
        "summary": "查看数据中心状态、新闻、市场温度和个人阈值。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.data-center",
    },
    "api-library.market-thermometer": {
        "key": "api-library.market-thermometer",
        "label": "市场温度数据",
        "module_key": "api-library",
        "group": "system",
        "summary": "查看市场温度历史、个人阈值和可执行的数据同步动作，辅助环境与脉搏判断。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.data-center.market-thermometer.history",
    },
    "execution.events": {
        "key": "execution.events",
        "label": "事件与实时监控",
        "module_key": "execution",
        "group": "execution",
        "summary": "查看事件查询、事件指标、实时状态和运行状态，辅助盘中检查。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.events.status",
    },
    "execution.share": {
        "key": "execution.share",
        "label": "分享与观察",
        "module_key": "execution",
        "group": "execution",
        "summary": "查看分享链接、公开快照和访问记录，支持复盘与观察者协作。",
        "view_type": "datagrid",
        "status": "online",
        "default_action_key": "auto.api.get.api.share",
    },
}


ACTION_SCREEN_RULES: tuple[tuple[str, str], ...] = (
    ("auto.api.get.api.decision.context.", "command-center.decision-flow"),
    ("auto.api.get.api.decision.workspace.", "command-center.decision-flow"),
    ("auto.api.get.api.decision.audit", "command-center.decision-flow"),
    ("auto.api.get.api.decision-rhythm", "macro-regime.risk-controls"),
    ("auto.api.get.api.decision", "command-center.decision-flow"),
    ("auto.api.get.api.dashboard.attention-items", "command-center.decision-flow"),
    ("auto.api.get.api.dashboard.action-recommendation", "command-center.decision-flow"),
    ("auto.api.get.api.dashboard.v1.alpha-decision-chain", "command-center.decision-flow"),
    ("auto.api.get.api.dashboard.alpha.", "command-center.dashboard"),
    ("auto.api.get.api.dashboard.", "command-center.dashboard"),
    ("auto.api.get.api.dashboard", "command-center.dashboard"),
    ("auto.api.get.api.account.portfolios", "execution.portfolio-performance"),
    ("auto.api.get.api.account.positions", "execution.trading-ledger"),
    ("auto.api.get.api.account.transactions", "execution.trading-ledger"),
    ("auto.api.get.api.account.capital-flows", "execution.trading-ledger"),
    ("auto.api.get.api.simulated-trading", "execution.trading-ledger"),
    ("auto.api.get.api.account.assets", "execution.account-settings"),
    ("auto.api.get.api.account.categories", "execution.account-settings"),
    ("auto.api.get.api.account.currencies", "execution.account-settings"),
    ("auto.api.get.api.account.exchange-rates", "execution.account-settings"),
    ("auto.api.get.api.account.observer-grants", "execution.account-settings"),
    ("auto.api.get.api.account.trading-cost-configs", "execution.account-settings"),
    ("auto.api.get.api.account.macro-sizing-config", "execution.account-settings"),
    ("auto.api.get.api.account.volatility", "execution.account-settings"),
    ("auto.api.get.api.account.sizing-context", "execution.account-settings"),
    ("auto.api.get.api.account.", "execution.accounts"),
    ("auto.api.get.api.account", "execution.accounts"),
    ("auto.api.get.api.strategy", "macro-regime.strategy"),
    ("auto.api.get.api.rotation", "macro-regime.rotation"),
    ("auto.api.get.api.beta-gate", "macro-regime.beta-gate"),
    ("auto.api.get.api.hedge", "macro-regime.hedge"),
    ("auto.api.get.api.regime", "macro-regime.navigator"),
    ("auto.api.get.api.pulse", "macro-regime.pulse"),
    ("auto.api.get.api.policy", "policy.workbench"),
    ("auto.api.get.api.alpha-triggers", "research.alpha-triggers"),
    ("auto.api.get.api.alpha.", "research.alpha"),
    ("auto.api.get.api.alpha", "research.alpha"),
    ("auto.api.get.api.signal", "research.signals"),
    ("auto.api.get.api.factor", "research.factors"),
    ("auto.api.get.api.backtest", "research.backtests"),
    ("auto.api.get.api.asset-analysis", "research.asset-lab"),
    ("auto.api.get.api.equity", "research.asset-lab"),
    ("auto.api.get.api.fund", "research.fund-sector"),
    ("auto.api.get.api.sector", "research.fund-sector"),
    ("auto.api.get.api.sentiment", "research.screening-sentiment"),
    ("auto.api.get.api.filter", "research.screening-sentiment"),
    ("auto.api.get.api.audit", "execution.audit"),
    ("auto.api.get.api.events", "execution.events"),
    ("auto.api.get.api.realtime", "execution.events"),
    ("auto.api.get.api.share", "execution.share"),
    ("auto.api.get.api.ai.me", "ai-ops.providers"),
    ("auto.api.get.api.prompt.chat", "ai-ops.providers"),
    ("auto.api.get.api.prompt", "ai-ops.prompt-workbench"),
    ("auto.api.get.api.terminal", "ai-ops.terminal"),
    ("auto.api.get.api.agent-runtime", "ai-ops.agent-runtime"),
    ("auto.api.get.api.ai-capability", "ai-ops.capabilities"),
    ("auto.api.get.api.ai", "ai-ops.capabilities"),
    ("auto.api.get.api.health", "api-library.runtime"),
    ("auto.api.get.api.ready", "api-library.runtime"),
    ("auto.api.get.api.setup", "api-library.runtime"),
    ("auto.api.get.api.system", "api-library.runtime"),
    ("auto.api.get.api.data-center.market-thermometer", "api-library.market-thermometer"),
    ("auto.api.get.api.data-center", "api-library.data-center"),
    ("param.api.get.api.decision-rhythm", "macro-regime.risk-controls"),
    ("param.api.get.api.decision.workspace", "command-center.decision-flow"),
    ("param.api.get.api.dashboard", "command-center.dashboard"),
    ("param.api.get.api.valuation", "execution.accounts"),
    ("param.api.get.api.account.accounts.int.account_id.performance", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.performance-report", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.valuation", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.benchmarks", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.equity-curve", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.inspections", "execution.portfolio-performance"),
    ("param.api.get.api.account.portfolios.int.portfolio_id.performance-report", "execution.portfolio-performance"),
    ("param.api.get.api.account.portfolios.int.portfolio_id.valuation", "execution.portfolio-performance"),
    ("param.api.get.api.account.portfolios.int.portfolio_id.benchmarks", "execution.portfolio-performance"),
    ("param.api.get.api.account.accounts.int.account_id.positions", "execution.trading-ledger"),
    ("param.api.get.api.account.accounts.int.account_id.trades", "execution.trading-ledger"),
    ("param.api.get.api.account.portfolios.pk.positions", "execution.trading-ledger"),
    ("param.api.get.api.account.positions", "execution.trading-ledger"),
    ("param.api.get.api.account.transactions", "execution.trading-ledger"),
    ("param.api.get.api.account.capital-flows", "execution.trading-ledger"),
    ("param.api.get.api.account.assets", "execution.account-settings"),
    ("param.api.get.api.account.observer-grants", "execution.account-settings"),
    ("param.api.get.api.account.trading-cost-configs", "execution.account-settings"),
    ("param.api.get.api.account.categories", "execution.account-settings"),
    ("param.api.get.api.account.currencies", "execution.account-settings"),
    ("param.api.get.api.account.exchange-rates", "execution.account-settings"),
    ("param.api.get.api.account.portfolios.int.portfolio_id.allocation", "execution.account-settings"),
    ("param.api.get.api.account", "execution.accounts"),
    ("param.api.get.api.simulated-trading", "execution.trading-ledger"),
    ("param.api.get.api.strategy", "macro-regime.strategy"),
    ("param.api.get.api.policy", "policy.workbench"),
    ("param.api.get.api.alpha-triggers", "research.alpha-triggers"),
    ("param.api.get.api.signal", "research.signals"),
    ("param.api.get.api.filter", "research.screening-sentiment"),
    ("param.api.get.api.backtest", "research.backtests"),
    ("param.api.get.api.audit", "execution.audit"),
    ("param.api.get.api.fund", "research.fund-sector"),
    ("param.api.get.api.factor", "research.factors"),
    ("param.api.get.api.rotation", "macro-regime.rotation"),
    ("param.api.get.api.beta-gate", "macro-regime.beta-gate"),
    ("param.api.get.api.hedge", "macro-regime.hedge"),
    ("param.api.get.api.system", "api-library.runtime"),
    ("param.api.get.api.share", "execution.share"),
    ("param.api.get.api.ai.me", "ai-ops.providers"),
    ("param.api.get.api.prompt", "ai-ops.prompt-workbench"),
    ("param.api.get.api.terminal", "ai-ops.terminal"),
    ("param.api.get.api.agent-runtime", "ai-ops.agent-runtime"),
    ("param.api.get.api.ai-capability", "ai-ops.capabilities"),
)

EXACT_SCREEN_RULES = {
    "terminal.chat_router": "ai-ops.terminal",
    "param.api.get.api.account.portfolios.pk": "execution.portfolio-performance",
    "param.api.get.api.account.portfolios.pk.statistics": "execution.portfolio-performance",
    "param.api.get.api.account.portfolios.pk.positions": "execution.portfolio-performance",
    "param.api.get.api.valuation.snapshot.str.snapshot_id": "command-center.decision-flow",
}

EXACT_VIEW_TYPE_RULES = {
    "auto.api.get.api.decision.workspace.aggregated": "datagrid",
    "auto.api.get.api.decision.workspace.recommendations": "datagrid",
    "auto.api.get.api.decision.workspace.conflicts": "datagrid",
    "auto.api.get.api.decision-rhythm.quotas": "datagrid",
    "auto.api.get.api.decision-rhythm.cooldowns": "datagrid",
    "auto.api.get.api.decision-rhythm.requests": "datagrid",
    "auto.api.get.api.beta-gate.configs": "datagrid",
    "auto.api.get.api.beta-gate.decisions": "datagrid",
    "auto.api.get.api.beta-gate.universe": "datagrid",
    "auto.api.get.api.beta-gate.version.compare": "datagrid",
    "auto.api.get.api.hedge.pairs": "datagrid",
    "auto.api.get.api.hedge.pairs.all_effectiveness": "datagrid",
    "auto.api.get.api.hedge.correlations": "datagrid",
    "auto.api.get.api.hedge.snapshots": "datagrid",
    "auto.api.get.api.hedge.snapshots.latest": "datagrid",
    "auto.api.get.api.hedge.alerts": "datagrid",
    "auto.api.get.api.hedge.alerts.active": "datagrid",
}

EXACT_VIEW_MODEL_RULES = {
    "auto.api.get.api.decision.workspace.recommendations": {
        "rows_path": "recommendations",
        "total_path": "total_count",
        "page_path": "page",
        "page_size_path": "page_size",
    },
    "auto.api.get.api.decision.workspace.conflicts": {
        "rows_path": "conflicts",
        "total_path": "total_count",
    },
    "auto.api.get.api.beta-gate.configs": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.beta-gate.decisions": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.beta-gate.universe": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.beta-gate.version.compare": {
        "rows_path": "results",
    },
    "auto.api.get.api.hedge.pairs": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.hedge.correlations": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.hedge.snapshots": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.hedge.snapshots.latest": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.hedge.alerts": {
        "rows_path": "results",
        "total_path": "count",
    },
    "auto.api.get.api.hedge.alerts.active": {
        "rows_path": "results",
        "total_path": "count",
    },
}

EXACT_FIELD_OVERRIDES = {
    "auto.api.get.api.decision.workspace.recommendations": {
        "account_id": {
            "input_type": "text",
            "value_type": "string",
            "default": "default",
            "placeholder": "默认账户口径，可改成自定义账户ID",
        },
    },
    "auto.api.get.api.decision.workspace.conflicts": {
        "account_id": {
            "input_type": "text",
            "value_type": "string",
            "default": "default",
            "placeholder": "默认账户口径，可改成自定义账户ID",
        },
    },
    "auto.api.get.api.decision-rhythm.quotas.by-period": {
        "account_id": {
            "input_type": "text",
            "value_type": "string",
            "default": "default",
            "placeholder": "默认账户口径，可改成自定义账户ID",
        },
    },
}

APPROVED_OPERATION_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "terminal.session.start",
        "label": "开启终端会话",
        "method": "POST",
        "endpoint": "/api/terminal/session/",
        "intent": "start_terminal_session",
        "screen_key": "ai-ops.terminal",
        "view_type": "detail",
        "risk": "ai",
        "fields": [],
        "description": "创建一个新的终端交互会话。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 10,
    },
    {
        "key": "share.public.access",
        "label": "公开分享 / 验证访问",
        "method": "POST",
        "endpoint": "/api/share/public/<str:short_code>/access/",
        "intent": "access_public_share",
        "screen_key": "execution.share",
        "view_type": "detail",
        "risk": "read",
        "fields": [
            {
                "key": "short_code",
                "label": "分享码",
                "input_type": "text",
                "required": True,
                "placeholder": "输入分享码",
                "binding": "path",
                "value_type": "string",
            },
            {
                "key": "password",
                "label": "访问密码",
                "input_type": "text",
                "required": False,
                "placeholder": "如分享受密码保护则输入访问密码",
                "binding": "body",
                "value_type": "string",
            },
        ],
        "description": "输入分享码和可选访问密码，建立当前会话的公开分享访问权限。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 20,
    },
    {
        "key": "data_center.decision_reliability_repair",
        "label": "修复决策数据就绪度",
        "method": "POST",
        "endpoint": "/api/data-center/decision-reliability/repair/",
        "intent": "repair_decision_reliability_inputs",
        "screen_key": "command-center.decision-flow",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "target_date", "label": "目标日期", "input_type": "date", "required": False},
            {"key": "portfolio_id", "label": "组合 ID", "input_type": "number", "required": False, "value_type": "integer"},
            {
                "key": "asset_codes",
                "label": "资产代码",
                "input_type": "text",
                "required": False,
                "placeholder": "逗号分隔，如 000001.SH,510300.SH",
                "value_type": "list",
            },
            {
                "key": "macro_indicator_codes",
                "label": "宏观指标",
                "input_type": "text",
                "required": False,
                "placeholder": "逗号分隔",
                "value_type": "list",
            },
            {"key": "strict", "label": "严格模式", "input_type": "checkbox", "required": False, "default": True, "value_type": "boolean"},
            {"key": "quote_max_age_hours", "label": "报价最大小时", "input_type": "number", "required": False, "default": 4, "value_type": "float"},
        ],
        "description": "检查并修复决策前需要的宏观、报价、Pulse 和 Alpha 输入。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 10,
    },
    {
        "key": "data_center.market_thermometer_calculate",
        "label": "重算市场温度",
        "method": "POST",
        "endpoint": "/api/data-center/market-thermometer/calculate/",
        "intent": "calculate_market_thermometer",
        "screen_key": "macro-regime.pulse",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "as_of_date", "label": "日期", "input_type": "date", "required": False},
        ],
        "description": "按指定日期或当前日期重新计算市场温度快照。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 10,
    },
    {
        "key": "data_center.market_thermometer_sync_inputs",
        "label": "同步市场温度输入",
        "method": "POST",
        "endpoint": "/api/data-center/market-thermometer/sync-inputs/",
        "intent": "sync_market_thermometer_inputs",
        "screen_key": "macro-regime.pulse",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "as_of_date", "label": "日期", "input_type": "date", "required": False},
        ],
        "description": "同步市场温度计算所需输入数据。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 20,
    },
    {
        "key": "data_center.sync_quotes",
        "label": "同步最新报价",
        "method": "POST",
        "endpoint": "/api/data-center/sync/quotes/",
        "intent": "sync_latest_quotes",
        "screen_key": "api-library.data-center",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "provider_id", "label": "Provider ID", "input_type": "number", "required": True, "value_type": "integer"},
            {
                "key": "asset_codes",
                "label": "资产代码",
                "input_type": "text",
                "required": True,
                "placeholder": "逗号分隔，如 000001.SH,510300.SH",
                "value_type": "list",
            },
        ],
        "description": "从指定数据源同步一组资产的最新报价。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 10,
    },
    {
        "key": "execution.trading-ledger.account-selector",
        "label": "账户选择",
        "method": "GET",
        "endpoint": "/api/account/accounts/",
        "intent": "read_account_selector_for_trading_ledger",
        "screen_key": "execution.trading-ledger",
        "view_type": "datagrid",
        "risk": "read",
        "fields": [],
        "description": "先选账户，再继续查看该账户的持仓、交易和资金流水。",
        "source": "approved:manual-read",
        "task_group": "02 账户选择",
        "sequence": 200,
    },
    {
        "key": "auto.api.get.api.data-center.indicators",
        "label": "指标目录",
        "method": "GET",
        "endpoint": "/api/data-center/indicators/",
        "intent": "read_data_center_indicators",
        "screen_key": "api-library.data-center",
        "view_type": "datagrid",
        "risk": "read",
        "fields": [],
        "description": "查看可查询的指标目录，供宏观序列等条件任务直接选取指标。",
        "source": "approved:manual-read",
        "task_group": "02 指标目录",
        "sequence": 200,
    },
    {
        "key": "auto.api.get.api.data-center.providers",
        "label": "服务商列表",
        "method": "GET",
        "endpoint": "/api/data-center/providers/",
        "intent": "read_data_center_providers",
        "screen_key": "api-library.data-center",
        "view_type": "datagrid",
        "risk": "read",
        "fields": [],
        "description": "查看数据服务商状态和编号，供同步与排障任务直接选取服务商。",
        "source": "approved:manual-read",
        "task_group": "04 服务商",
        "sequence": 400,
    },
    {
        "key": "auto.api.get.api.data-center.publishers",
        "label": "发布机构目录",
        "method": "GET",
        "endpoint": "/api/data-center/publishers/",
        "intent": "read_data_center_publishers",
        "screen_key": "api-library.data-center",
        "view_type": "datagrid",
        "risk": "read",
        "fields": [],
        "description": "查看宏观与市场数据的发布机构目录和口径来源。",
        "source": "approved:manual-read",
        "task_group": "05 发布机构",
        "sequence": 500,
    },
    {
        "key": "alpha.inference.trigger_batch",
        "label": "触发 Alpha 批量推理",
        "method": "POST",
        "endpoint": "/api/alpha/ops/inference/trigger/",
        "intent": "trigger_alpha_inference_batch",
        "screen_key": "research.alpha",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "mode", "label": "模式", "input_type": "hidden", "required": True, "default": "daily_scoped_batch"},
            {"key": "top_n", "label": "Top N", "input_type": "number", "required": False, "default": 30, "value_type": "integer"},
            {
                "key": "pool_mode",
                "label": "资产池",
                "input_type": "select",
                "required": False,
                "default": "price_covered",
                "options": [
                    {"value": "price_covered", "label": "价格覆盖"},
                    {"value": "all_active", "label": "全部启用"},
                ],
            },
        ],
        "description": "触发按组合范围聚合的 Alpha 推理任务。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 10,
    },
    {
        "key": "alpha.qlib_data_refresh",
        "label": "刷新 Qlib 运行数据",
        "method": "POST",
        "endpoint": "/api/alpha/ops/qlib-data/refresh/",
        "intent": "refresh_qlib_runtime_data",
        "screen_key": "research.alpha",
        "view_type": "detail",
        "risk": "write",
        "fields": [
            {"key": "mode", "label": "模式", "input_type": "hidden", "required": True, "default": "scoped_codes"},
            {"key": "target_date", "label": "目标日期", "input_type": "date", "required": True},
            {"key": "lookback_days", "label": "回看天数", "input_type": "number", "required": False, "default": 400, "value_type": "integer"},
            {"key": "portfolio_ids", "label": "组合 ID", "input_type": "text", "required": False, "placeholder": "逗号分隔", "value_type": "list"},
            {"key": "all_active_portfolios", "label": "全部启用组合", "input_type": "checkbox", "required": False, "default": False, "value_type": "boolean"},
            {
                "key": "pool_mode",
                "label": "资产池",
                "input_type": "select",
                "required": False,
                "default": "price_covered",
                "options": [
                    {"value": "price_covered", "label": "价格覆盖"},
                    {"value": "all_active", "label": "全部启用"},
                ],
            },
        ],
        "description": "刷新 Qlib 推理所需的运行数据。",
        "source": "approved:operation",
        "task_group": "00 可执行操作",
        "sequence": 20,
    },
    {
        "key": "config_center.qlib_runtime",
        "label": "Qlib 运行配置",
        "method": "GET",
        "endpoint": "/api/system/config-center/qlib/runtime/",
        "intent": "read_qlib_runtime_config",
        "screen_key": "api-library.config-center",
        "view_type": "detail",
        "risk": "admin",
        "fields": [],
        "description": "查看当前 Qlib 运行配置、活跃模型和训练占用状态。",
        "source": "approved:admin",
        "task_group": "01 运行配置",
        "sequence": 10,
    },
    {
        "key": "config_center.qlib_runtime_update",
        "label": "更新 Qlib 运行配置",
        "method": "POST",
        "endpoint": "/api/system/config-center/qlib/runtime/",
        "intent": "update_qlib_runtime_config",
        "screen_key": "api-library.config-center",
        "view_type": "detail",
        "risk": "admin",
        "fields": [
            {"key": "enabled", "label": "启用", "input_type": "checkbox", "required": False, "value_type": "boolean"},
            {"key": "provider_uri", "label": "Provider URI", "input_type": "text", "required": False},
            {"key": "region", "label": "区域", "input_type": "text", "required": False},
            {"key": "model_root", "label": "模型目录", "input_type": "text", "required": False},
            {"key": "default_universe", "label": "默认标的池", "input_type": "text", "required": False},
            {"key": "default_feature_set_id", "label": "默认特征集", "input_type": "text", "required": False},
            {"key": "default_label_id", "label": "默认标签集", "input_type": "text", "required": False},
            {"key": "train_queue_name", "label": "训练队列", "input_type": "text", "required": False},
            {"key": "infer_queue_name", "label": "推理队列", "input_type": "text", "required": False},
            {"key": "allow_auto_activate", "label": "允许自动激活", "input_type": "checkbox", "required": False, "value_type": "boolean"},
            {"key": "alpha_fixed_provider", "label": "固定 Provider", "input_type": "text", "required": False},
            {"key": "alpha_pool_mode", "label": "资产池模式", "input_type": "text", "required": False},
        ],
        "description": "更新 Qlib 运行时配置。",
        "source": "approved:admin",
        "task_group": "00 管理操作",
        "sequence": 10,
    },
    {
        "key": "config_center.training_profiles",
        "label": "训练模板",
        "method": "GET",
        "endpoint": "/api/system/config-center/qlib/training-profiles/",
        "intent": "list_qlib_training_profiles",
        "screen_key": "api-library.config-center",
        "view_type": "datagrid",
        "risk": "admin",
        "fields": [],
        "view_model": {"kind": "datagrid", "rows_path": "data"},
        "description": "查看已登记的 Qlib 训练模板。",
        "source": "approved:admin",
        "task_group": "02 训练模板",
        "sequence": 20,
    },
    {
        "key": "config_center.training_profile_save",
        "label": "保存训练模板",
        "method": "POST",
        "endpoint": "/api/system/config-center/qlib/training-profiles/",
        "intent": "save_qlib_training_profile",
        "screen_key": "api-library.config-center",
        "view_type": "detail",
        "risk": "admin",
        "fields": [
            {"key": "id", "label": "模板 ID", "input_type": "number", "required": False, "value_type": "integer"},
            {"key": "profile_key", "label": "模板键", "input_type": "text", "required": True},
            {"key": "name", "label": "模板名称", "input_type": "text", "required": True},
            {"key": "model_name", "label": "模型名称", "input_type": "text", "required": True},
            {"key": "model_type", "label": "模型类型", "input_type": "text", "required": True},
            {"key": "universe", "label": "标的池", "input_type": "text", "required": False},
            {"key": "start_date", "label": "开始日期", "input_type": "date", "required": False, "value_type": "date"},
            {"key": "end_date", "label": "结束日期", "input_type": "date", "required": False, "value_type": "date"},
            {"key": "feature_set_id", "label": "特征集", "input_type": "text", "required": False},
            {"key": "label_id", "label": "标签集", "input_type": "text", "required": False},
            {"key": "learning_rate", "label": "学习率", "input_type": "number", "required": False, "value_type": "float"},
            {"key": "epochs", "label": "轮数", "input_type": "number", "required": False, "value_type": "integer"},
            {"key": "model_params", "label": "模型参数", "input_type": "textarea", "required": False, "placeholder": "{\"key\": \"value\"}", "value_type": "object"},
            {"key": "extra_train_config", "label": "额外训练配置", "input_type": "textarea", "required": False, "placeholder": "{\"key\": \"value\"}", "value_type": "object"},
            {"key": "activate_after_train", "label": "训练后激活", "input_type": "checkbox", "required": False, "value_type": "boolean"},
            {"key": "is_active", "label": "启用模板", "input_type": "checkbox", "required": False, "default": True, "value_type": "boolean"},
            {"key": "notes", "label": "备注", "input_type": "textarea", "required": False},
        ],
        "description": "创建或更新一个 Qlib 训练模板。",
        "source": "approved:admin",
        "task_group": "00 管理操作",
        "sequence": 20,
    },
    {
        "key": "config_center.training_runs",
        "label": "训练运行记录",
        "method": "GET",
        "endpoint": "/api/system/config-center/qlib/training-runs/",
        "intent": "list_qlib_training_runs",
        "screen_key": "api-library.config-center",
        "view_type": "datagrid",
        "risk": "admin",
        "fields": [],
        "view_model": {"kind": "datagrid", "rows_path": "data"},
        "description": "查看最近的 Qlib 训练运行记录。",
        "source": "approved:admin",
        "task_group": "03 训练运行",
        "sequence": 30,
    },
    {
        "key": "config_center.training_run_detail",
        "label": "训练运行详情",
        "method": "GET",
        "endpoint": "/api/system/config-center/qlib/training-runs/<str:run_id>/",
        "intent": "read_qlib_training_run_detail",
        "screen_key": "api-library.config-center",
        "view_type": "detail",
        "risk": "admin",
        "fields": [
            {"key": "run_id", "label": "运行 ID", "input_type": "text", "required": True, "binding": "path"},
        ],
        "description": "按运行 ID 查看一条训练运行详情。",
        "source": "approved:admin",
        "task_group": "03 训练运行",
        "sequence": 40,
    },
    {
        "key": "config_center.training_run_trigger",
        "label": "触发训练任务",
        "method": "POST",
        "endpoint": "/api/system/config-center/qlib/training-runs/trigger/",
        "intent": "trigger_qlib_training_run",
        "screen_key": "api-library.config-center",
        "view_type": "detail",
        "risk": "admin",
        "fields": [
            {"key": "profile_key", "label": "模板键", "input_type": "text", "required": False},
            {"key": "model_name", "label": "模型名称", "input_type": "text", "required": False},
            {"key": "model_type", "label": "模型类型", "input_type": "text", "required": False},
            {"key": "universe", "label": "标的池", "input_type": "text", "required": False},
            {"key": "start_date", "label": "开始日期", "input_type": "date", "required": False, "value_type": "date"},
            {"key": "end_date", "label": "结束日期", "input_type": "date", "required": False, "value_type": "date"},
            {"key": "feature_set_id", "label": "特征集", "input_type": "text", "required": False},
            {"key": "label_id", "label": "标签集", "input_type": "text", "required": False},
            {"key": "learning_rate", "label": "学习率", "input_type": "number", "required": False, "value_type": "float"},
            {"key": "epochs", "label": "轮数", "input_type": "number", "required": False, "value_type": "integer"},
            {"key": "model_params", "label": "模型参数", "input_type": "textarea", "required": False, "placeholder": "{\"key\": \"value\"}", "value_type": "object"},
            {"key": "extra_train_config", "label": "额外训练配置", "input_type": "textarea", "required": False, "placeholder": "{\"key\": \"value\"}", "value_type": "object"},
            {"key": "activate", "label": "训练后激活", "input_type": "checkbox", "required": False, "value_type": "boolean"},
        ],
        "description": "提交一个新的 Qlib 训练任务。",
        "source": "approved:admin",
        "task_group": "00 管理操作",
        "sequence": 30,
    },
)


EXACT_LABELS = {
    "auto.api.get.api.setup.password-strength": "初始化密码强度",
    "auto.api.get.api.dashboard": "今日仪表盘",
    "auto.api.get.api.dashboard.regime-status": "市场环境卡片",
    "auto.api.get.api.dashboard.pulse-card": "脉搏卡片",
    "auto.api.get.api.dashboard.allocation": "资产配置",
    "auto.api.get.api.dashboard.performance": "组合表现",
    "auto.api.get.api.dashboard.alpha.history": "Alpha 历史",
    "auto.api.get.api.dashboard.alpha.coverage": "Alpha 覆盖",
    "auto.api.get.api.dashboard.alpha.ic-trends": "Alpha IC 趋势",
    "auto.api.get.api.decision.context.step1": "第一步：环境状态",
    "auto.api.get.api.decision.context.step2": "第二步：信号检查",
    "auto.api.get.api.decision.context.step3": "第三步：风险约束",
    "auto.api.get.api.decision.context.step4": "第四步：候选确认",
    "auto.api.get.api.decision.context.step5": "第五步：执行准备",
    "auto.api.get.api.decision.context.step6": "第六步：复盘记录",
    "auto.api.get.api.decision.workspace.aggregated": "决策工作台汇总",
    "auto.api.get.api.decision.workspace.params": "决策参数",
    "auto.api.get.api.decision.audit": "决策审计",
    "auto.api.get.api.dashboard.attention-items": "重点关注事项",
    "auto.api.get.api.dashboard.action-recommendation": "行动建议",
    "auto.api.get.api.dashboard.v1.alpha-decision-chain": "Alpha 决策链",
    "auto.api.get.api.account.profile": "账户资料",
    "auto.api.get.api.account.health": "账户健康",
    "auto.api.get.api.account.macro-sizing-config": "宏观仓位参数",
    "auto.api.get.api.account.users.search": "用户检索",
    "auto.api.get.api.account.accounts": "账户列表",
    "auto.api.get.api.account.portfolios": "组合列表",
    "auto.api.get.api.account.positions": "持仓明细",
    "auto.api.get.api.account.transactions": "交易流水",
    "auto.api.get.api.account.capital-flows": "资金流水",
    "auto.api.get.api.account.assets": "资产清单",
    "auto.api.get.api.account.observer-grants": "观察者授权",
    "auto.api.get.api.account.trading-cost-configs": "交易成本配置",
    "auto.api.get.api.account.volatility": "账户波动率",
    "auto.api.get.api.account.sizing-context": "仓位测算上下文",
    "auto.api.get.api.account.categories": "账户分类",
    "auto.api.get.api.account.categories.roots": "根分类",
    "auto.api.get.api.account.categories.tree": "分类树",
    "auto.api.get.api.account.currencies": "币种列表",
    "auto.api.get.api.account.currencies.base": "基准币种",
    "auto.api.get.api.account.exchange-rates": "汇率表",
    "auto.api.get.api.simulated-trading": "模拟交易状态",
    "auto.api.get.api.simulated-trading.accounts": "模拟账户",
    "auto.api.get.api.simulated-trading.fee-configs": "模拟交易费用",
    "auto.api.get.api.strategy.strategies": "策略清单",
    "auto.api.get.api.strategy.position-rules": "仓位规则",
    "auto.api.get.api.strategy.rules": "策略规则",
    "auto.api.get.api.strategy.script-configs": "策略脚本配置",
    "auto.api.get.api.strategy.assignments": "策略绑定",
    "auto.api.get.api.strategy.assignments.by_portfolio": "策略绑定（按组合）",
    "auto.api.get.api.strategy.execution-logs": "策略执行记录",
    "auto.api.get.api.strategy.execution-logs.by_portfolio": "策略执行记录（按组合）",
    "auto.api.get.api.strategy.execution-logs.by_strategy": "策略执行记录（按策略）",
    "auto.api.get.api.strategy.strategies.my_strategies": "我的策略",
    "auto.api.get.api.decision-rhythm.quotas": "决策节奏配额",
    "auto.api.get.api.decision-rhythm.cooldowns": "冷却期",
    "auto.api.get.api.decision-rhythm.requests": "节奏请求",
    "auto.api.get.api.decision-rhythm.requests.statistics": "节奏统计",
    "auto.api.get.api.decision-rhythm.summary": "决策节奏概览",
    "auto.api.get.api.decision-rhythm.trend-data": "节奏趋势",
    "auto.api.get.api.alpha-triggers": "Alpha 触发器入口",
    "auto.api.get.api.alpha-triggers.triggers": "触发器列表",
    "auto.api.get.api.alpha-triggers.triggers.active": "活跃触发器",
    "auto.api.get.api.alpha-triggers.triggers.statistics": "触发器统计",
    "auto.api.get.api.alpha-triggers.candidates": "候选列表",
    "auto.api.get.api.alpha-triggers.candidates.actionable": "可操作候选",
    "auto.api.get.api.alpha-triggers.candidates.watch-list": "观察列表",
    "auto.api.get.api.alpha-triggers.candidates.statistics": "候选统计",
    "auto.api.get.api.alpha-triggers.performance": "触发器绩效",
    "auto.api.get.api.agent-runtime": "AI 任务入口",
    "auto.api.get.api.agent-runtime.health": "运行时健康",
    "auto.api.get.api.agent-runtime.tasks": "任务队列",
    "auto.api.get.api.agent-runtime.tasks.needs_attention": "待处理任务",
    "auto.api.get.api.agent-runtime.proposals": "提案列表",
    "auto.api.get.api.agent-runtime.tasks.pk.artifacts": "任务产物",
    "auto.api.get.api.agent-runtime.tasks.pk.timeline": "任务时间线",
    "auto.api.get.api.rotation.recommendation": "轮动配置建议",
    "auto.api.get.api.rotation.assets": "轮动资产",
    "auto.api.get.api.rotation.assets.with_prices": "带价格轮动资产",
    "auto.api.get.api.rotation.asset-classes": "轮动资产类别",
    "auto.api.get.api.rotation.asset-classes.with_prices": "带价格资产类别",
    "auto.api.get.api.rotation.configs": "轮动配置",
    "auto.api.get.api.rotation.signals.latest": "最新轮动信号",
    "auto.api.get.api.rotation.templates": "轮动模板",
    "auto.api.get.api.rotation.account-configs": "账户轮动配置",
    "auto.api.get.api.rotation.health": "轮动健康",
    "auto.api.get.api.rotation.regimes": "轮动环境",
    "auto.api.get.api.beta-gate": "Beta Gate 状态",
    "auto.api.get.api.beta-gate.configs": "Beta Gate 配置",
    "auto.api.get.api.beta-gate.decisions": "Beta Gate 决策",
    "auto.api.get.api.beta-gate.universe": "Beta Gate 标的池",
    "auto.api.get.api.beta-gate.health": "Beta Gate 健康",
    "auto.api.get.api.beta-gate.version.compare": "Beta Gate 版本对比",
    "auto.api.get.api.hedge.pairs": "对冲组合",
    "auto.api.get.api.hedge.pairs.all_effectiveness": "对冲有效性",
    "auto.api.get.api.hedge.correlations": "相关性记录",
    "auto.api.get.api.hedge.snapshots": "对冲快照",
    "auto.api.get.api.hedge.snapshots.latest": "最新对冲快照",
    "auto.api.get.api.hedge.alerts": "对冲预警",
    "auto.api.get.api.hedge.alerts.active": "当前对冲预警",
    "auto.api.get.api.hedge.actions": "对冲动作",
    "auto.api.get.api.hedge.health": "对冲健康",
    "auto.api.get.api.asset-analysis.pool-summary": "资产池概览",
    "auto.api.get.api.filter.indicators": "筛选指标",
    "auto.api.get.api.filter.health": "筛选健康",
    "auto.api.get.api.equity": "股票研究入口",
    "auto.api.get.api.asset-analysis": "资产分析入口",
    "auto.api.get.api.asset-analysis.weight-configs": "资产权重配置",
    "auto.api.get.api.asset-analysis.current-weight": "当前资产权重",
    "auto.api.get.api.fund.rank": "基金排行",
    "auto.api.get.api.sentiment.index.recent": "近期情绪指数",
    "auto.api.get.api.sentiment.index.range": "情绪指数区间",
    "auto.api.get.api.sentiment.health": "情绪健康",
    "auto.api.get.api.ai.me.logs": "我的 AI 日志",
    "auto.api.get.api.prompt": "Prompt 总览",
    "auto.api.get.api.prompt.templates": "Prompt 模板",
    "auto.api.get.api.prompt.templates.categories": "Prompt 分类",
    "auto.api.get.api.prompt.chains": "Prompt 链路",
    "auto.api.get.api.prompt.chains.execution_modes": "链路执行模式",
    "auto.api.get.api.prompt.logs.recent": "近期 Prompt 日志",
    "auto.api.get.api.prompt.chat.providers": "Chat Provider",
    "auto.api.get.api.prompt.chat.models": "Chat 模型",
    "auto.api.get.api.ai.me.providers": "我的 AI Provider",
    "auto.api.get.api.data-center": "数据中心状态",
    "auto.api.get.api.data-center.news": "新闻数据",
    "auto.api.get.api.data-center.market-thermometer.history": "市场温度历史",
    "auto.api.get.api.data-center.market-thermometer.me": "我的市场温度阈值",
    "auto.api.get.api.health": "系统健康",
    "auto.api.get.api.ready": "系统就绪检查",
    "auto.api.get.api.system.celery.health": "Celery 健康",
    "auto.api.get.api.policy.status": "政策状态",
    "auto.api.get.api.policy": "政策总览",
    "auto.api.get.api.policy.audit.queue": "政策审核队列",
    "auto.api.get.api.policy.ingestion-config": "政策采集配置",
    "auto.api.get.api.policy.sentiment-gate-config": "政策情绪闸门",
    "auto.api.get.api.policy.rss.sources": "RSS 来源",
    "auto.api.get.api.policy.rss.logs": "RSS 日志",
    "auto.api.get.api.policy.rss.keywords": "RSS 关键词",
    "auto.api.get.api.regime": "环境导航",
    "auto.api.get.api.regime.health": "环境引擎健康",
    "auto.api.get.api.pulse": "当前战术脉搏",
    "auto.api.get.api.alpha.universes": "Alpha 标的池",
    "auto.api.get.api.alpha.ops.inference.overview": "Alpha 推理概览",
    "auto.api.get.api.alpha.ops.qlib-data.overview": "Qlib 数据概览",
    "auto.api.get.api.signal.health": "信号健康",
    "auto.api.get.api.signal.unified.pending": "待处理统一信号",
    "auto.api.get.api.factor.configs": "因子配置",
    "auto.api.get.api.factor.all-configs": "全部因子配置",
    "auto.api.get.api.factor.all-factors": "全部因子",
    "auto.api.get.api.factor.definitions.all_active": "当前启用因子",
    "auto.api.get.api.factor.health": "因子健康",
    "auto.api.get.api.backtest.backtests.statistics": "回测统计",
    "auto.api.get.api.audit": "复盘审计总览",
    "auto.api.get.api.audit.execution-links": "执行关联",
    "auto.api.get.api.audit.health": "审计健康",
    "auto.api.get.api.audit.failure-counter": "失败计数",
    "auto.api.get.api.audit.metrics": "审计指标",
    "auto.api.get.api.realtime": "实时状态",
    "auto.api.get.api.events": "事件总览",
    "auto.api.get.api.events.query": "事件查询",
    "auto.api.get.api.events.metrics": "事件指标",
    "auto.api.get.api.events.status": "事件状态",
    "auto.api.get.api.share": "分享总览",
    "auto.api.get.api.share.links": "分享链接",
    "auto.api.get.api.terminal": "终端能力总览",
    "auto.api.get.api.terminal.commands": "终端指令",
    "auto.api.get.api.ai": "AI 总览",
    "auto.api.get.api.ai-capability": "AI 能力目录",
    "auto.api.get.api.system": "系统总览",
    "auto.api.get.api.system.list": "系统任务列表",
    "auto.api.get.api.prompt.chat.providers": "Chat 服务商",
    "param.api.get.api.signal.pk.validate": "信号校验详情",
    "param.api.get.api.strategy.script-configs.pk": "策略脚本配置详情",
    "param.api.get.api.strategy.assignments.pk": "策略绑定详情",
    "param.api.get.api.beta-gate.decisions.pk": "Beta Gate 决策详情",
    "param.api.get.api.audit.decision-traces.str.request_id": "决策链路详情",
    "param.api.get.api.rotation.assets.code.detail": "轮动资产详情",
    "param.api.get.api.share.links.pk.stats": "分享统计详情",
    "param.api.get.api.ai.me.providers.pk": "AI 服务商详情",
    "param.api.get.api.alpha-triggers.triggers.by-regime.regime": "Alpha 触发器 / 按环境 / 详情",
    "param.api.get.api.alpha-triggers.triggers.pk": "Alpha 触发器 / 详情",
    "param.api.get.api.alpha-triggers.candidates.pk": "Alpha 候选 / 详情",
    "param.api.get.api.agent-runtime.tasks.pk": "任务详情",
    "param.api.get.api.agent-runtime.tasks.pk.artifacts": "任务产物",
    "param.api.get.api.agent-runtime.tasks.pk.timeline": "任务时间线",
    "param.api.get.api.agent-runtime.proposals.pk": "提案详情",
    "param.api.get.api.dashboard.position.str.asset_code": "标的持仓详情",
    "param.api.get.api.ai-capability.capabilities.str.capability_key": "AI 能力详情",
    "param.api.get.api.ai-capability.capabilities.pk": "AI 能力详情",
}


WORD_REPLACEMENTS = (
    ("With Prices", "含价格"),
    ("Decision Rhythm", "决策节奏"),
    ("Decision", "决策"),
    ("Workspace", "工作台"),
    ("Dashboard", "仪表盘"),
    ("Account", "账户"),
    ("Portfolio", "组合"),
    ("Portfolios", "组合"),
    ("Positions", "持仓"),
    ("Transactions", "交易"),
    ("Strategy", "策略"),
    ("Strategies", "策略"),
    ("Execution", "执行"),
    ("Rotation", "轮动"),
    ("Recommendation", "建议"),
    ("Signals", "信号"),
    ("Signal", "信号"),
    ("Ai Capability", "AI 能力"),
    ("Capabilities", "能力"),
    ("Capability", "能力"),
    ("Ai", "AI"),
    ("Policy", "政策"),
    ("Rss", "RSS"),
    ("Qlib", "Qlib"),
    ("Universes", "标的池"),
    ("Universe", "标的池"),
    ("Inference", "推理"),
    ("Overview", "概览"),
    ("Definitions", "定义"),
    ("Configs", "配置"),
    ("Config", "配置"),
    ("Pending", "待处理"),
    ("Query", "查询"),
    ("Links", "链接"),
    ("Risk", "风险"),
    ("Health", "健康"),
    ("Status", "状态"),
    ("Summary", "概览"),
    ("Statistics", "统计"),
    ("Validate", "校验"),
    ("Terminal", "终端"),
    ("System", "系统"),
    ("Regime", "环境"),
    ("Pulse", "脉搏"),
    ("Audit", "审计"),
    ("Events", "事件"),
    ("Realtime", "实时"),
    ("Share", "分享"),
    ("Current", "当前"),
    ("Assignment", "绑定"),
    ("Trace", "链路"),
    ("Detail", "详情"),
    ("Stats", "统计"),
    ("Script", "脚本"),
    ("List", "列表"),
    ("All", "全部"),
    ("Ic", "IC"),
    ("Me", "我的"),
    ("Data Center", "数据中心"),
    ("Market Thermometer", "市场温度"),
    ("News", "新闻"),
    ("Prompt", "Prompt"),
    ("Templates", "模板"),
    ("Logs", "日志"),
    ("Recent", "近期"),
    ("Providers", "Provider"),
    ("Provider", "Provider"),
    ("Assets", "资产"),
    ("Asset", "资产"),
    ("Fund", "基金"),
    ("Sector", "板块"),
    ("Sentiment", "情绪"),
    ("Filter", "筛选"),
    ("Factor", "因子"),
    ("Backtest", "回测"),
    ("Hedge", "对冲"),
    ("Alerts", "预警"),
    ("Active", "当前"),
    ("Metrics", "指标"),
)

HOME_DASHBOARD_PANEL_TITLES = {
    "regime-status": "一、市场周期象限",
    "pulse-alerts": "二、战术脉搏预警",
    "account-positions": "三、账户与持仓",
    "alpha-ranking": "四、Alpha 排行",
    "task-monitor": "五、任务监控",
}

DAILY_WORKFLOW_STEPS: tuple[dict[str, str], ...] = (
    {
        "screen_key": "command-center.overview",
        "label": "今日总览",
        "role": "先看系统、市场、账户和任务是否有异常。",
    },
    {
        "screen_key": "macro-regime.overview",
        "label": "环境判断",
        "role": "确认 Regime、政策状态和市场温度，避免在错误环境中下注。",
    },
    {
        "screen_key": "policy.workbench",
        "label": "政策热点",
        "role": "检查政策、热点和情绪事件是否改变行动边界。",
    },
    {
        "screen_key": "macro-regime.pulse",
        "label": "战术脉搏",
        "role": "识别短期转折、过热和风险提示。",
    },
    {
        "screen_key": "command-center.decision-flow",
        "label": "决策流程",
        "role": "按环境、信号、约束、候选、执行准备和复盘完成当天判断。",
    },
    {
        "screen_key": "research.signals",
        "label": "信号池",
        "role": "查看有效信号、统一信号和待处理信号。",
    },
    {
        "screen_key": "research.alpha",
        "label": "Alpha 候选",
        "role": "查看 Alpha 排名、来源状态，并在需要时触发已确认的推理任务。",
    },
    {
        "screen_key": "research.asset-lab",
        "label": "资产研究",
        "role": "补充资产池、基金、板块、情绪和筛选器信息。",
    },
    {
        "screen_key": "execution.accounts",
        "label": "账户组合",
        "role": "检查账户健康、组合、持仓、流水和执行成本。",
    },
    {
        "screen_key": "macro-regime.strategy",
        "label": "策略仓位",
        "role": "核对策略、仓位规则、绑定关系和执行记录。",
    },
    {
        "screen_key": "macro-regime.rotation",
        "label": "轮动配置",
        "role": "查看轮动信号、配置建议和账户轮动设置。",
    },
    {
        "screen_key": "macro-regime.risk-controls",
        "label": "风控约束",
        "role": "检查决策节奏、Beta Gate、对冲和主动风控提醒。",
    },
    {
        "screen_key": "execution.events",
        "label": "事件监控",
        "role": "确认盘中事件、实时状态和运行指标。",
    },
    {
        "screen_key": "execution.audit",
        "label": "复盘审计",
        "role": "回看操作日志、决策痕迹、审计健康和失败计数。",
    },
    {
        "screen_key": "execution.share",
        "label": "分享观察",
        "role": "查看分享链接、观察者协作和访问记录。",
    },
)

BUSINESS_CONTEXTS: dict[str, dict[str, Any]] = {
    "command-center.overview": {
        "objective": "用最短路径确认今天是否有必要进入完整投研流程。",
        "decision_output": "今日总览结论：环境、脉搏、账户、Alpha 和任务是否有异常。",
        "checkpoints": [
            "先看市场周期象限和战术脉搏是否冲突。",
            "再看账户持仓和 Alpha 排名是否需要进一步研究。",
            "最后看任务监控是否影响数据可信度。",
        ],
    },
    "macro-regime.overview": {
        "objective": "判断当前宏观环境是否允许下注，避免和 Regime/Policy 过滤器冲突。",
        "decision_output": "环境判断结论：可行动、观察、降风险或暂停。",
        "checkpoints": [
            "确认增长/通胀象限和政策档位。",
            "检查市场温度、风险状态和核心仪表盘摘要。",
            "如果环境和信号不一致，优先进入风险约束或脉搏检查。",
        ],
    },
    "policy.workbench": {
        "objective": "确认政策事件、热点和情绪是否改变行动边界。",
        "decision_output": "政策结论：维持原计划、提高关注、延后执行或收紧仓位。",
        "checkpoints": [
            "先看政策状态和审核项。",
            "再看 RSS、热点和情绪事件。",
            "只把会影响仓位、轮动或风险约束的事件带入决策流程。",
        ],
    },
    "macro-regime.pulse": {
        "objective": "识别短期战术转折，补充宏观慢变量无法覆盖的风险提示。",
        "decision_output": "脉搏结论：确认、背离、过热、修复数据或继续观察。",
        "checkpoints": [
            "先读取当前 Pulse 和市场温度。",
            "需要时执行已确认的市场温度重算或输入同步。",
            "把过热、转折和数据缺口带入每日决策流程。",
        ],
    },
    "command-center.decision-flow": {
        "objective": "按固定顺序把环境、信号、约束、候选和复盘串成一个可审计判断。",
        "decision_output": "当天行动结论：执行、等待、修复数据、降风险或复盘记录。",
        "checkpoints": [
            "按第一步到第六步顺序检查，不跳过风险约束。",
            "如数据缺口影响判断，先执行已确认的数据就绪度修复。",
            "最终结论必须能回溯到环境、信号和约束。",
        ],
    },
    "research.signals": {
        "objective": "把有效信号整理为候选输入，而不是直接变成交易动作。",
        "decision_output": "信号结论：可研究候选、等待确认或剔除。",
        "checkpoints": [
            "先看有效信号，再看统一信号和待处理信号。",
            "关注信号强度、来源和失效条件。",
            "只有通过环境和风控约束的信号才进入候选。",
        ],
    },
    "research.alpha": {
        "objective": "从 Alpha 排名和来源状态中找到可研究候选，并维护推理数据可用性。",
        "decision_output": "Alpha 结论：候选名单、数据需刷新或推理需触发。",
        "checkpoints": [
            "先看 Alpha 排名和 Provider 状态。",
            "数据过期时先刷新 Qlib 运行数据。",
            "需要新候选时再触发已确认的批量推理。",
        ],
    },
    "research.asset-lab": {
        "objective": "补齐资产、基金、板块、情绪和筛选器证据，服务候选筛选。",
        "decision_output": "研究结论：候选资产、排除原因和进一步观察项。",
        "checkpoints": [
            "先看资产池和通用评分。",
            "再看基金、板块和情绪证据。",
            "筛选结果必须回到信号、Alpha 或账户约束中使用。",
        ],
    },
    "research.fund-sector": {
        "objective": "从基金和板块维度补充横向比较，帮助判断候选是否有更合适载体。",
        "decision_output": "基金板块结论：优先基金、优先板块、继续观察或排除。",
        "checkpoints": [
            "先看基金排行和基金池。",
            "再看板块状态和板块变化。",
            "基金或板块候选必须回到信号、Alpha 和风控约束中确认。",
        ],
    },
    "research.screening-sentiment": {
        "objective": "用筛选器和情绪指标过滤候选，避免把噪声当作交易理由。",
        "decision_output": "筛选情绪结论：通过、待观察、情绪过热或剔除。",
        "checkpoints": [
            "先看筛选指标和筛选器健康。",
            "再看近期情绪指数和情绪健康。",
            "筛选或情绪异常只作为风险提示，不直接生成交易动作。",
        ],
    },
    "execution.accounts": {
        "objective": "在执行前确认账户、组合、持仓、流水和成本都支持当前动作。",
        "decision_output": "执行前检查结论：可执行、资金不足、持仓冲突或需调整账户。",
        "checkpoints": [
            "先看账户健康和组合列表。",
            "再看持仓、交易流水和资金流水。",
            "执行前必须确认成本、现金和现有仓位不会破坏策略规则。",
        ],
    },
    "execution.trading-ledger": {
        "objective": "确认持仓、交易流水、资金流水和模拟交易结果已经正确反映执行动作。",
        "decision_output": "落账检查结论：执行已落账、流水异常、资金冲突或需回到复盘。",
        "checkpoints": [
            "先看持仓明细，再看交易流水和资金流水。",
            "如果来自模拟盘，核对模拟账户、成交和费用配置。",
            "发现落账异常时，进入复盘审计或账户参数屏处理。",
        ],
    },
    "execution.portfolio-performance": {
        "objective": "把账户和组合表现转换成可复盘的绩效、估值、净值和基准证据。",
        "decision_output": "绩效结论：表现正常、偏离基准、估值异常或需要检查记录。",
        "checkpoints": [
            "先看组合列表和账户绩效。",
            "再按账户或组合查看估值快照、估值时间线和净值曲线。",
            "偏离明显时，把证据带入复盘审计和策略仓位检查。",
        ],
    },
    "execution.account-settings": {
        "objective": "核对影响执行约束的账户参数、分类、币种、汇率、成本和观察权限。",
        "decision_output": "参数结论：可执行、成本需修正、汇率需更新或权限需调整。",
        "checkpoints": [
            "先看交易成本和宏观仓位参数。",
            "再看资产分类、币种、汇率和观察授权。",
            "参数异常时先修正配置，再回到执行或风控判断。",
        ],
    },
    "macro-regime.strategy": {
        "objective": "把环境判断映射到策略和仓位规则，避免临场随意加仓。",
        "decision_output": "策略结论：采用的策略、目标仓位和执行边界。",
        "checkpoints": [
            "先看策略清单和仓位规则。",
            "再核对绑定关系和执行记录。",
            "策略与环境不匹配时，返回环境或风控屏复核。",
        ],
    },
    "macro-regime.rotation": {
        "objective": "把轮动信号转换成配置建议，并核对账户轮动设置。",
        "decision_output": "轮动结论：配置建议、等待确认或不轮动。",
        "checkpoints": [
            "先看最新轮动建议。",
            "再看资产、模板和账户配置。",
            "只在环境、信号和风控都一致时进入执行准备。",
        ],
    },
    "macro-regime.risk-controls": {
        "objective": "在执行前检查节奏、Beta Gate、对冲和主动风控是否允许行动。",
        "decision_output": "风控结论：放行、降仓、对冲、冷却或禁止执行。",
        "checkpoints": [
            "先看决策节奏和冷却期。",
            "再看 Beta Gate、对冲快照和主动预警。",
            "风控不通过时，不进入执行动作。",
        ],
    },
    "macro-regime.beta-gate": {
        "objective": "单独核对 Beta Gate 是否允许当前市场暴露，避免组合暴露和市场状态冲突。",
        "decision_output": "Beta Gate 结论：放行、限制、禁止或需要版本复核。",
        "checkpoints": [
            "先看当前 Gate 状态和最近决策。",
            "再看配置、标的池和健康状态。",
            "版本或规则冲突时进入版本对比，不直接执行。",
        ],
    },
    "macro-regime.hedge": {
        "objective": "确认是否需要对冲、降风险或处理主动预警。",
        "decision_output": "对冲结论：无需对冲、需要对冲、预警处理或相关性复核。",
        "checkpoints": [
            "先看当前对冲预警和最新快照。",
            "再看对冲组合、相关性和有效性。",
            "对冲信号必须回到风控约束后再进入执行。",
        ],
    },
    "execution.events": {
        "objective": "确认盘中事件和实时状态是否改变执行时机。",
        "decision_output": "事件结论：正常执行、延迟、暂停或转入复核。",
        "checkpoints": [
            "先看事件状态和实时运行状态。",
            "再看指标和告警。",
            "重大事件必须反馈到政策、风险或复盘。",
        ],
    },
    "execution.audit": {
        "objective": "复盘已发生的动作和系统记录，保证决策可追踪。",
        "decision_output": "复盘结论：动作有效、需修正、需补记录或需排查异常。",
        "checkpoints": [
            "先看操作日志和审计健康。",
            "再看失败计数和链路记录。",
            "复盘发现的问题要回到策略、数据或风控修复。",
        ],
    },
    "execution.share": {
        "objective": "把可分享的观察和复盘材料交付给观察者，不暴露内部调试细节。",
        "decision_output": "分享结论：可分享、需脱敏、撤回或继续观察。",
        "checkpoints": [
            "先看分享链接和公开快照。",
            "再看访问记录和观察者协作。",
            "只分享业务结论，不分享原始 JSON 或内部接口。",
        ],
    },
    "ai-ops.providers": {
        "objective": "确认 AI 服务商、模型和用量日志是否支持当前 AI 辅助流程。",
        "decision_output": "AI 服务结论：可用、需切换服务商、配额不足或需要排查日志。",
        "checkpoints": [
            "先看我的 AI 服务商和可用模型。",
            "再看调用日志、配额和失败记录。",
            "AI 不可用时，不让决策流程依赖 AI 解释作为唯一证据。",
        ],
    },
    "api-library.market-thermometer": {
        "objective": "查看市场温度历史和个人阈值，确认环境与脉搏判断的数据基础。",
        "decision_output": "市场温度结论：正常、过热、过冷、阈值需调整或数据需同步。",
        "checkpoints": [
            "先看市场温度历史。",
            "再看个人阈值和最近数据更新时间。",
            "数据缺口需要先同步或重算，再回到环境判断。",
        ],
    },
}


TASK_GROUP_RULES: tuple[tuple[str, str], ...] = (
    ("auto.api.get.api.decision.context.", "01 决策步骤"),
    ("auto.api.get.api.decision.workspace.", "02 决策工作台"),
    ("auto.api.get.api.dashboard.", "03 今日信号"),
    ("auto.api.get.api.policy.rss", "04 RSS 采集"),
    ("auto.api.get.api.policy.audit", "03 政策审核"),
    ("auto.api.get.api.policy", "02 政策状态"),
    ("auto.api.get.api.regime", "01 环境状态"),
    ("auto.api.get.api.pulse", "02 战术脉搏"),
    ("auto.api.get.api.alpha-triggers.candidates.actionable", "01 候选池"),
    ("auto.api.get.api.alpha-triggers.candidates.watch-list", "02 观察列表"),
    ("auto.api.get.api.alpha-triggers.candidates", "01 候选池"),
    ("auto.api.get.api.alpha-triggers.triggers", "03 触发器"),
    ("auto.api.get.api.alpha-triggers.performance", "04 绩效"),
    ("auto.api.get.api.alpha.ops", "05 Alpha 运维"),
    ("auto.api.get.api.alpha", "02 Alpha 候选"),
    ("auto.api.get.api.signal", "01 信号检查"),
    ("auto.api.get.api.factor", "02 因子库"),
    ("auto.api.get.api.backtest", "03 回测记录"),
    ("auto.api.get.api.audit", "01 审计记录"),
    ("auto.api.get.api.events", "02 事件监控"),
    ("auto.api.get.api.realtime", "03 实时状态"),
    ("auto.api.get.api.share", "04 分享观察"),
    ("auto.api.get.api.account.profile", "01 账户状态"),
    ("auto.api.get.api.account.health", "01 账户状态"),
    ("auto.api.get.api.account.accounts", "02 账户组合"),
    ("auto.api.get.api.account.portfolios", "02 账户组合"),
    ("auto.api.get.api.account.positions", "03 持仓交易"),
    ("auto.api.get.api.account.transactions", "03 持仓交易"),
    ("auto.api.get.api.account.capital-flows", "03 持仓交易"),
    ("auto.api.get.api.account.assets", "04 资产参数"),
    ("auto.api.get.api.account.categories", "04 资产参数"),
    ("auto.api.get.api.account.currencies", "04 资产参数"),
    ("auto.api.get.api.account.exchange-rates", "04 资产参数"),
    ("auto.api.get.api.account.observer-grants", "05 仓位约束"),
    ("auto.api.get.api.account.trading-cost-configs", "05 仓位约束"),
    ("auto.api.get.api.account.macro-sizing-config", "05 仓位约束"),
    ("auto.api.get.api.account.volatility", "05 仓位约束"),
    ("auto.api.get.api.account.sizing-context", "05 仓位约束"),
    ("auto.api.get.api.simulated-trading", "06 模拟交易"),
    ("auto.api.get.api.strategy.strategies", "01 策略清单"),
    ("auto.api.get.api.strategy.position-rules", "02 仓位规则"),
    ("auto.api.get.api.strategy.rules", "02 仓位规则"),
    ("auto.api.get.api.strategy.assignments", "03 策略绑定"),
    ("auto.api.get.api.strategy.execution-logs", "04 执行记录"),
    ("auto.api.get.api.rotation.assets", "01 轮动资产"),
    ("auto.api.get.api.rotation.asset-classes", "01 轮动资产"),
    ("auto.api.get.api.rotation.signals", "02 轮动信号"),
    ("auto.api.get.api.rotation.recommendation", "03 配置建议"),
    ("auto.api.get.api.rotation.configs", "04 配置模板"),
    ("auto.api.get.api.rotation.templates", "04 配置模板"),
    ("auto.api.get.api.rotation.account-configs", "04 配置模板"),
    ("auto.api.get.api.decision-rhythm", "01 决策节奏"),
    ("auto.api.get.api.beta-gate", "02 Beta Gate"),
    ("auto.api.get.api.hedge", "03 对冲风控"),
    ("auto.api.get.api.filter", "01 筛选器"),
    ("auto.api.get.api.equity", "02 资产池"),
    ("auto.api.get.api.asset-analysis", "02 资产池"),
    ("auto.api.get.api.fund", "03 基金板块"),
    ("auto.api.get.api.sector", "03 基金板块"),
    ("auto.api.get.api.sentiment", "04 情绪"),
    ("auto.api.get.api.ai.me", "01 Provider"),
    ("auto.api.get.api.prompt.templates", "02 模板"),
    ("auto.api.get.api.prompt.chains", "03 链路"),
    ("auto.api.get.api.prompt.logs", "04 日志"),
    ("auto.api.get.api.prompt.chat", "05 模型"),
    ("auto.api.get.api.prompt", "02 模板"),
    ("auto.api.get.api.agent-runtime.health", "01 运行状态"),
    ("auto.api.get.api.agent-runtime.tasks.needs_attention", "02 待处理任务"),
    ("auto.api.get.api.agent-runtime.tasks", "03 任务队列"),
    ("auto.api.get.api.agent-runtime.proposals", "04 提案"),
    ("auto.api.get.api.agent-runtime", "01 运行状态"),
    ("auto.api.get.api.health", "01 健康检查"),
    ("auto.api.get.api.ready", "01 健康检查"),
    ("auto.api.get.api.system", "02 系统状态"),
    ("auto.api.get.api.setup", "03 初始化"),
    ("auto.api.get.api.data-center.market-thermometer", "02 市场温度"),
    ("auto.api.get.api.data-center.news", "03 新闻数据"),
    ("auto.api.get.api.data-center", "01 数据中心"),
    ("param.api.get.api.account", "07 条件查询"),
    ("param.api.get.api.simulated-trading", "07 条件查询"),
    ("param.api.get.api.strategy", "05 条件查询"),
    ("param.api.get.api.policy", "05 条件查询"),
    ("param.api.get.api.signal", "05 条件查询"),
    ("param.api.get.api.filter", "05 条件查询"),
    ("param.api.get.api.backtest", "05 条件查询"),
    ("param.api.get.api.audit", "05 条件查询"),
    ("param.api.get.api.fund", "05 条件查询"),
    ("param.api.get.api.factor", "05 条件查询"),
    ("param.api.get.api.rotation", "05 条件查询"),
    ("param.api.get.api.beta-gate", "05 条件查询"),
    ("param.api.get.api.hedge", "05 条件查询"),
    ("param.api.get.api.share", "05 条件查询"),
    ("param.api.get.api.prompt", "06 条件查询"),
    ("param.api.get.api.terminal", "06 条件查询"),
    ("param.api.get.api.ai-capability", "06 条件查询"),
    ("param.api.get.api", "09 条件查询"),
)

PRIMARY_ACTION_KEYS = {
    "dashboard.v1_summary",
    "dashboard.alpha_provider_status",
    "decision.funnel_context",
    "regime.current",
    "policy.workbench_summary",
    "data_center.market_thermometer",
    "policy.queue_summary",
    "policy.workbench_items",
    "auto.api.get.api.policy.status",
    "auto.api.get.api.policy.audit.queue",
    "regime.navigator",
    "regime.action",
    "auto.api.get.api.regime.health",
    "pulse.current",
    "signal.active",
    "signal.unified_summary",
    "alpha.scores",
    "alpha.providers_status",
    "auto.api.get.api.alpha-triggers.candidates.actionable",
    "auto.api.get.api.alpha-triggers.triggers.active",
    "auto.api.get.api.alpha-triggers.performance",
    "factor.definitions",
    "backtest.statistics",
    "backtest.backtests",
    "audit.operation_logs",
    "audit.decision_traces",
    "task_monitor.dashboard",
    "ai_capability.list",
    "terminal.chat_router",
    "terminal.session.start",
    "agent_runtime.needs_attention",
    "auto.api.get.api.decision.context.step1",
    "auto.api.get.api.decision.context.step2",
    "auto.api.get.api.decision.context.step3",
    "auto.api.get.api.decision.context.step4",
    "auto.api.get.api.decision.context.step5",
    "auto.api.get.api.decision.context.step6",
    "auto.api.get.api.decision.workspace.aggregated",
    "auto.api.get.api.dashboard.attention-items",
    "auto.api.get.api.dashboard.action-recommendation",
    "auto.api.get.api.dashboard.v1.alpha-decision-chain",
    "auto.api.get.api.account.profile",
    "auto.api.get.api.account.health",
    "auto.api.get.api.account.accounts",
    "auto.api.get.api.account.portfolios",
    "auto.api.get.api.account.positions",
    "auto.api.get.api.account.transactions",
    "auto.api.get.api.account.capital-flows",
    "auto.api.get.api.account.trading-cost-configs",
    "auto.api.get.api.account.macro-sizing-config",
    "auto.api.get.api.strategy.strategies",
    "auto.api.get.api.strategy.position-rules",
    "auto.api.get.api.strategy.assignments",
    "auto.api.get.api.rotation.recommendation",
    "auto.api.get.api.rotation.assets",
    "auto.api.get.api.rotation.signals.latest",
    "auto.api.get.api.beta-gate",
    "auto.api.get.api.beta-gate.decisions",
    "auto.api.get.api.beta-gate.health",
    "auto.api.get.api.hedge.snapshots.latest",
    "auto.api.get.api.hedge.alerts.active",
    "auto.api.get.api.hedge.health",
    "auto.api.get.api.asset-analysis.pool-summary",
    "auto.api.get.api.filter.indicators",
    "auto.api.get.api.filter.health",
    "auto.api.get.api.fund.rank",
    "auto.api.get.api.sector",
    "auto.api.get.api.sentiment.index.recent",
    "auto.api.get.api.sentiment.health",
    "auto.api.get.api.audit.health",
    "auto.api.get.api.events.status",
    "auto.api.get.api.events.metrics",
    "auto.api.get.api.realtime",
    "auto.api.get.api.share",
    "auto.api.get.api.share.links",
    "auto.api.get.api.ai.me.providers",
    "auto.api.get.api.ai.me.logs",
    "auto.api.get.api.prompt.templates",
    "auto.api.get.api.prompt.chat.providers",
    "auto.api.get.api.prompt.chat.models",
    "auto.api.get.api.agent-runtime.health",
    "auto.api.get.api.agent-runtime.tasks.needs_attention",
    "auto.api.get.api.terminal.commands",
    "auto.api.get.api.health",
    "auto.api.get.api.ready",
    "auto.api.get.api.system.celery.health",
    "auto.api.get.api.data-center",
    "auto.api.get.api.data-center.market-thermometer.history",
    "auto.api.get.api.data-center.market-thermometer.me",
}

REDUNDANT_SCREEN_ACTION_KEYS = {
    "ai-ops.capabilities": {
        "param.api.get.api.ai-capability.capabilities.pk",
    },
}

EXACT_TASK_GROUPS = {
    "dashboard.alpha_provider_status": "01 决策状态",
    "decision.funnel_context": "01 决策状态",
    "dashboard.v1_summary": "01 总览",
    "dashboard.regime_quadrant": "02 组合态势",
    "dashboard.equity_curve": "02 组合态势",
    "dashboard.signal_status": "03 信号状态",
    "regime.current": "01 环境状态",
    "policy.workbench_summary": "02 政策状态",
    "data_center.market_thermometer": "03 市场温度",
    "policy.queue_summary": "01 政策队列",
    "policy.workbench_items": "01 政策队列",
    "regime.navigator": "01 环境导航",
    "regime.action": "02 行动建议",
    "regime.navigator_history": "03 切换历史",
    "pulse.current": "01 当前脉搏",
    "pulse.history": "02 脉搏历史",
    "signal.active": "01 有效信号",
    "signal.stats": "02 信号统计",
    "signal.unified_summary": "03 统一信号",
    "alpha.scores": "01 Alpha 排名",
    "alpha.providers_status": "02 来源状态",
    "alpha.health": "03 Alpha 健康",
    "factor.definitions": "01 因子定义",
    "backtest.statistics": "01 回测统计",
    "backtest.backtests": "02 回测列表",
    "audit.operation_logs": "01 操作日志",
    "audit.decision_traces": "02 决策痕迹",
    "task_monitor.dashboard": "01 任务状态",
    "ai_capability.list": "01 能力清单",
    "terminal.capabilities": "02 终端权限",
    "ai_capability.stats": "03 能力统计",
    "terminal.commands_available": "02 指令清单",
    "terminal.commands_by_category": "03 指令分类",
    "agent_runtime.health": "01 运行状态",
    "agent_runtime.needs_attention": "02 待处理任务",
    "auto.api.get.api.alpha-triggers.candidates.actionable": "01 候选池",
    "auto.api.get.api.alpha-triggers.candidates.watch-list": "02 观察列表",
    "auto.api.get.api.alpha-triggers.triggers": "03 触发器",
    "auto.api.get.api.alpha-triggers.performance": "04 绩效",
    "auto.api.get.api.agent-runtime.health": "01 运行状态",
    "auto.api.get.api.agent-runtime.tasks.needs_attention": "02 待处理任务",
    "auto.api.get.api.agent-runtime.tasks": "03 任务队列",
    "auto.api.get.api.agent-runtime.proposals": "04 提案",
}


def _promoted_screen_for(action_key: str) -> str:
    if action_key in EXACT_SCREEN_RULES:
        return EXACT_SCREEN_RULES[action_key]
    for prefix, screen_key in ACTION_SCREEN_RULES:
        if action_key.startswith(prefix):
            return screen_key
    return ""


def _operator_label(action: dict[str, Any]) -> str:
    key = str(action.get("key") or "")
    if key in EXACT_LABELS:
        return EXACT_LABELS[key]
    label = str(action.get("label") or "")
    for old, new in WORD_REPLACEMENTS:
        label = label.replace(old, new)
    return _clean_operator_label(label)


def _clean_operator_label(label: str) -> str:
    label = label.replace("回测s", "记录")
    label = label.replace("Provider", "服务商")
    label = label.replace("My 策略", "我的策略")
    label = label.replace("All 当前", "当前")
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"([^/]+) / \1( / |$)", r"\1\2", label)
    label = re.sub(r"\b([A-Za-z]+)s\b", r"\1", label)
    return label


def _task_group(action_key: str) -> str:
    if action_key in EXACT_TASK_GROUPS:
        return EXACT_TASK_GROUPS[action_key]
    for prefix, group in TASK_GROUP_RULES:
        if action_key.startswith(prefix):
            return group
    return "常用任务"


def _sequence(action_key: str) -> int:
    group = _task_group(action_key)
    try:
        return int(group.split(" ", 1)[0]) * 100
    except (TypeError, ValueError):
        return 900


def _task_tier(action: dict[str, Any]) -> str:
    key = str(action.get("key") or "")
    group = str(action.get("task_group") or "")
    risk = str(action.get("risk") or "read")
    if str(action.get("source") or "") == "approved:operation":
        return "operation"
    if risk in {"write", "ai", "admin"}:
        return "operation"
    if key.startswith("param.") or "条件查询" in group:
        return "advanced"
    if key in PRIMARY_ACTION_KEYS:
        return "primary"
    return "support"


def _merge_approved_operation_actions(payload: dict[str, Any]) -> int:
    screen_by_key = {screen["key"]: screen for screen in payload["screens"]}
    action_by_key = {action["key"]: action for action in payload["actions"]}
    merged = 0
    for spec in APPROVED_OPERATION_ACTIONS:
        action = dict(spec)
        screen = screen_by_key.get(str(action["screen_key"]))
        if not screen:
            continue
        action["module_key"] = screen["module_key"]
        if action["key"] in action_by_key:
            action_by_key[action["key"]].update(action)
        else:
            payload["actions"].append(action)
            action_by_key[action["key"]] = action
        merged += 1
    return merged


def _normalize_special_action(action: dict[str, Any]) -> None:
    exact_view_type = EXACT_VIEW_TYPE_RULES.get(str(action.get("key") or ""))
    if exact_view_type:
        action["view_type"] = exact_view_type
    exact_view_model = EXACT_VIEW_MODEL_RULES.get(str(action.get("key") or ""))
    if exact_view_model:
        action["view_model"] = {
            **dict(action.get("view_model") or {}),
            **exact_view_model,
        }
    field_overrides = EXACT_FIELD_OVERRIDES.get(str(action.get("key") or ""))
    if field_overrides:
        for field in action.get("fields") or []:
            override = field_overrides.get(str(field.get("key") or ""))
            if override:
                field.update(override)
    if action.get("key") != "terminal.chat_router":
        return
    fields = action.get("fields") or []
    for field in fields:
        if field.get("key") == "message":
            field["label"] = "消息"
            field["default"] = "总结当前决策流程，并指出今天是否应该行动。"
            field["placeholder"] = "直接输入问题或任务，不需要写 JSON"


def _apply_workflow_metadata(payload: dict[str, Any]) -> None:
    screen_by_key = {screen["key"]: screen for screen in payload["screens"]}
    total = len(DAILY_WORKFLOW_STEPS)
    for index, step in enumerate(DAILY_WORKFLOW_STEPS):
        screen = screen_by_key.get(step["screen_key"])
        if not screen:
            continue
        previous_step = DAILY_WORKFLOW_STEPS[index - 1] if index > 0 else None
        next_step = DAILY_WORKFLOW_STEPS[index + 1] if index + 1 < total else None
        screen["workflow"] = {
            "name": "每日投研流程",
            "step": index + 1,
            "total": total,
            "label": step["label"],
            "role": step["role"],
            "previous": (
                {
                    "key": previous_step["screen_key"],
                    "label": previous_step["label"],
                }
                if previous_step
                else {}
            ),
            "next": (
                {
                    "key": next_step["screen_key"],
                    "label": next_step["label"],
                }
                if next_step
                else {}
            ),
        }


def _apply_business_context_metadata(payload: dict[str, Any]) -> None:
    screen_by_key = {screen["key"]: screen for screen in payload["screens"]}
    for screen_key, context in BUSINESS_CONTEXTS.items():
        screen = screen_by_key.get(screen_key)
        if not screen:
            continue
        screen["business_context"] = {
            "objective": str(context.get("objective") or ""),
            "decision_output": str(context.get("decision_output") or ""),
            "checkpoints": [
                str(item)
                for item in context.get("checkpoints", [])
                if str(item).strip()
            ][:6],
        }


def _apply_default_business_context_metadata(payload: dict[str, Any]) -> None:
    actions_by_screen: dict[str, list[dict[str, Any]]] = {}
    for action in payload.get("actions", []):
        actions_by_screen.setdefault(str(action.get("screen_key") or ""), []).append(action)

    output_by_view = {
        "datagrid": "可筛选、可翻页、可打开明细的业务列表。",
        "detail": "当前对象或当前任务的结构化摘要。",
        "status": "当前状态、异常信号和后续检查方向。",
        "message": "可读的业务说明或交互结果。",
        "queue_workbench": "队列状态、待处理事项和下一步处理方向。",
    }
    for screen in payload.get("screens", []):
        context = dict(screen.get("business_context") or {})
        if context.get("objective") or context.get("decision_output") or context.get("checkpoints"):
            continue
        actions = actions_by_screen.get(str(screen.get("key") or ""), [])
        checkpoints: list[str] = []
        if any(str(action.get("task_tier")) == "primary" for action in actions):
            checkpoints.append("先按主流程任务读取本屏关键判断。")
        if any(str(action.get("task_tier")) == "support" for action in actions):
            checkpoints.append("发现矛盾或缺口时展开支撑检查。")
        if any(str(action.get("task_tier")) == "advanced" for action in actions):
            checkpoints.append("需要定位单条记录时再使用条件查询。")
        if any(str(action.get("task_tier")) == "operation" for action in actions):
            checkpoints.append("写入或 AI 交互只在证据明确后执行，并接受确认。")
        if not checkpoints:
            checkpoints.append("当前屏暂无已发布任务，等待 metadata 提升后进入主菜单。")
        screen["business_context"] = {
            "objective": str(screen.get("summary") or screen.get("label") or ""),
            "decision_output": output_by_view.get(
                str(screen.get("view_type") or ""),
                "当前工作区的业务结果和下一步操作。",
            ),
            "checkpoints": checkpoints[:6],
        }


def _prune_empty_screens(payload: dict[str, Any]) -> int:
    """Remove navigable screens that have no approved content."""

    action_screen_keys = {
        str(action.get("screen_key") or "")
        for action in payload.get("actions", [])
        if str(action.get("screen_key") or "").strip()
    }
    default_screen = str(payload.get("default_screen") or "")
    kept: list[dict[str, Any]] = []
    removed = 0
    for screen in payload.get("screens", []):
        screen_key = str(screen.get("key") or "")
        has_dashboard = bool(screen.get("dashboard_panels") or [])
        if screen_key != default_screen and screen_key not in action_screen_keys and not has_dashboard:
            removed += 1
            continue
        kept.append(screen)
    payload["screens"] = kept
    return removed


def _prune_redundant_screen_actions(payload: dict[str, Any]) -> int:
    """Drop duplicated screen actions when a row-backed business-key route exists."""

    if not REDUNDANT_SCREEN_ACTION_KEYS:
        return 0

    kept: list[dict[str, Any]] = []
    removed = 0
    for action in payload.get("actions", []):
        screen_key = str(action.get("screen_key") or "")
        action_key = str(action.get("key") or "")
        redundant_keys = REDUNDANT_SCREEN_ACTION_KEYS.get(screen_key, set())
        if action_key in redundant_keys:
            removed += 1
            continue
        kept.append(action)
    payload["actions"] = kept
    return removed


def promote_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    for module in payload.get("modules", []):
        if module.get("key") == "api-library":
            module["label"] = "系统工具"
            module["summary"] = "系统运行、数据中心和低频条件查询工具。"

    screen_by_key = {screen["key"]: screen for screen in payload["screens"]}
    for screen_key, spec in SCREEN_SPECS.items():
        if screen_key in screen_by_key:
            screen_by_key[screen_key].update(spec)
        else:
            payload["screens"].append({**spec, "dashboard_panels": []})
            screen_by_key[screen_key] = payload["screens"][-1]
    home_screen = screen_by_key.get("command-center.overview")
    if home_screen:
        for panel in home_screen.get("dashboard_panels", []) or []:
            title = HOME_DASHBOARD_PANEL_TITLES.get(str(panel.get("key") or ""))
            if title:
                panel["title"] = title
    _apply_workflow_metadata(payload)
    _apply_business_context_metadata(payload)
    approved_operation_actions = _merge_approved_operation_actions(payload)

    promoted = 0
    for action in payload["actions"]:
        action_key = str(action.get("key") or "")
        if action_key not in EXACT_SCREEN_RULES and str(action.get("source")) not in {
            "api-collector:candidate",
            "api-collector:parameterized-candidate",
            "approved:smoke-promoted",
            "approved:parameterized-promoted",
        }:
            continue
        screen_key = _promoted_screen_for(action_key)
        if not screen_key:
            continue
        spec = SCREEN_SPECS.get(screen_key) or screen_by_key.get(screen_key)
        if not spec:
            continue
        action["screen_key"] = screen_key
        action["module_key"] = spec["module_key"]
        action["label"] = _operator_label(action)
        risk = str(action.get("risk") or "read")
        suffix = "需确认" if risk == "write" else ("交互" if risk == "ai" else "查看")
        action["description"] = f"{spec['summary']}（{suffix}）"
        source = str(action.get("source"))
        action["source"] = (
            "approved:parameterized-promoted"
            if source in {"api-collector:parameterized-candidate", "approved:parameterized-promoted"}
            else "approved:smoke-promoted"
        )
        action["task_group"] = _task_group(action_key)
        action["sequence"] = _sequence(action_key)
        if spec["view_type"] in {"datagrid", "detail", "status"} and str(action.get("view_type")) == "auto":
            action["view_type"] = spec["view_type"]
        _normalize_special_action(action)
        promoted += 1

    for action in payload["actions"]:
        action_key = str(action.get("key") or "")
        if not action.get("task_group"):
            action["task_group"] = _task_group(action_key)
        if "sequence" not in action:
            action["sequence"] = _sequence(action_key)
        action["task_tier"] = _task_tier(action)
    pruned_redundant_actions = _prune_redundant_screen_actions(payload)
    _apply_default_business_context_metadata(payload)
    pruned_empty_screens = _prune_empty_screens(payload)

    coverage = dict(payload.get("coverage_summary") or {})
    coverage["business_promoted_actions"] = promoted
    coverage["approved_operation_actions"] = approved_operation_actions
    coverage["pruned_redundant_screen_actions"] = pruned_redundant_actions
    coverage["pruned_empty_screens"] = pruned_empty_screens
    payload["coverage_summary"] = coverage
    return payload, promoted


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote TUI tool actions into user-task screens.")
    parser.add_argument(
        "path",
        nargs="?",
        default="config/tui/published/tui_operation_graph.published.json",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    path = (root / args.path).resolve()
    output = (root / args.output).resolve() if args.output else path
    payload = json.loads(path.read_text(encoding="utf-8"))
    promoted_payload, promoted = promote_payload(payload)
    validated = validate_tui_metadata(promoted_payload)
    output.write_text(
        json.dumps(compact_tui_metadata_payload(validated), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "path": str(output), "business_promoted_actions": promoted}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
