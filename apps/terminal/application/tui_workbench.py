"""Published-metadata driven TUI workbench contracts and view models."""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from html import unescape
from html.parser import HTMLParser
from math import ceil
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

from apps.ai_provider.application.query_services import has_user_personal_providers
from apps.alpha_trigger.application.query_services import (
    has_alpha_candidates,
    has_alpha_triggers,
)
from apps.asset_analysis.application.asset_name_service import resolve_asset_names
from apps.beta_gate.application.query_services import (
    has_beta_gate_configs,
    has_beta_gate_decisions,
    has_beta_gate_universe_snapshots,
)
from apps.config_center.application.query_services import has_qlib_training_runs
from apps.dashboard.application.query_services import has_dashboard_alpha_history
from apps.decision_rhythm.application.query_services import (
    has_active_cooldowns,
    has_decision_quotas,
    has_recent_decision_requests,
)
from apps.task_monitor.application.query_services import has_recent_task_failures
from apps.terminal.application.tui_audit import (
    TuiTerminalAuditSink,
    action_requires_audit,
    build_tui_audit_record,
    verified_reauth_evidence,
)
from apps.terminal.domain.interfaces import (
    TerminalAuditRepository,
    TuiActionExecutor,
    TuiMetadataRepository,
)

VISIBLE_RUNTIME_RISKS = {"read", "ai", "write"}
ADMIN_RUNTIME_RISKS = {"admin"}
USER_HIDDEN_SCREEN_ACTION_KEYS = {
    "param.api.get.api.dashboard.position.str.asset_code",
    "param.api.get.api.valuation.snapshot.str.snapshot_id",
    "param.api.get.api.decision.workspace.plans.str.plan_id",
    "param.api.get.api.audit.indicator-performance.str.indicator_code",
    "param.api.get.api.system.status.str.task_id",
}
USER_CONDITIONAL_SCREEN_ACTIONS = {
    "param.api.get.api.ai.me.providers.pk": lambda user: has_user_personal_providers(user),
    "param.api.get.api.dashboard.alpha.history.int.run_id": lambda user: has_dashboard_alpha_history(
        user
    ),
    "auto.api.get.api.decision-rhythm.quotas.by-period": lambda _user: has_decision_quotas(),
    "param.api.get.api.decision-rhythm.cooldowns.by-asset.asset_code": lambda _user: has_active_cooldowns(),
    "auto.api.get.api.decision-rhythm.cooldowns.remaining-hours": lambda _user: has_active_cooldowns(),
    "param.api.get.api.decision-rhythm.requests.pk": lambda _user: has_recent_decision_requests(),
    "param.api.get.api.beta-gate.configs.pk": lambda _user: has_beta_gate_configs(),
    "param.api.get.api.beta-gate.decisions.pk": lambda _user: has_beta_gate_decisions(),
    "param.api.get.api.beta-gate.universe.pk": lambda _user: has_beta_gate_universe_snapshots(),
    "param.api.get.api.alpha-triggers.triggers.by-regime.regime": lambda _user: has_alpha_triggers(),
    "param.api.get.api.alpha-triggers.triggers.pk": lambda _user: has_alpha_triggers(),
    "param.api.get.api.alpha-triggers.candidates.pk": lambda _user: has_alpha_candidates(),
    "auto.api.get.api.system.statistics": lambda _user: has_recent_task_failures(),
    "config_center.training_run_detail": lambda _user: has_qlib_training_runs(),
}
HTML_TAG_PATTERN = re.compile(r"</?\s*[a-zA-Z][a-zA-Z0-9:-]*(?:\s+[^<>]*)?>")
ESCAPED_HTML_TAG_PATTERN = re.compile(r"&lt;/?\s*[a-zA-Z][a-zA-Z0-9:-]*")
ASSET_CODE_PATTERN = re.compile(
    r"^(?:\d{6}(?:\.(?:SH|SZ|BJ|OF))?|(?:SH|SZ|BJ)\d{6})$",
    re.IGNORECASE,
)
ASSET_CODE_FIELDS = {"asset_code", "stock_code", "code", "symbol", "fund_code"}
ASSET_NAME_FIELDS = ("asset_name", "stock_name", "fund_name", "name")
ROW_IDENTIFIER_FIELDS = {
    "id",
    "pk",
    "account_id",
    "portfolio_id",
    "asset_code",
    "fund_code",
    "code",
    "symbol",
    "capability_key",
    "strategy_id",
    "strategy",
    "event_id",
    "summary_id",
    "report_id",
    "validation_id",
    "log_id",
    "request_id",
    "task_id",
    "provider_id",
    "snapshot_id",
    "run_id",
    "plan_id",
    "short_code",
    "task_name",
    "period",
    "sector_code",
}

FIELD_LABELS = {
    "account": "账户",
    "account_id": "账户ID",
    "account_name": "账户名称",
    "account_type": "账户类型",
    "action": "动作",
    "action_required": "需要行动",
    "actionable": "可操作",
    "ai_provider_available": "AI服务可用",
    "allocation_effect": "配置效应",
    "annual_return": "年化收益",
    "annualized_return": "年化收益",
    "answer_chain_visibility": "回答链可见性",
    "active": "启用",
    "aggregate_step": "聚合步骤",
    "amount": "金额",
    "asof_date": "日期",
    "asset": "资产",
    "attribution_method": "归因方法",
    "auto_approve_threshold": "自动通过阈值",
    "asset_code": "标的代码",
    "asset_name": "标的名称",
    "available_cash": "可用现金",
    "balance": "余额",
    "band": "区间",
    "base_currency": "基准币种",
    "benchmark_name": "基准名称",
    "benchmark_return": "基准收益",
    "backend_reachable": "后端可达",
    "backtest_id": "回测ID",
    "blocked_reason": "阻塞原因",
    "broker_reachable": "Broker可达",
    "buy_condition_expr": "买入条件",
    "buy_price_expr": "买入价格表达式",
    "cash": "现金",
    "cash_balance": "现金余额",
    "causation_id": "因果ID",
    "category": "分类",
    "checked_at": "检查时间",
    "client_id": "客户端ID",
    "code": "代码",
    "commission_rate": "佣金率",
    "commission_rate_buy": "买入佣金率",
    "commission_rate_sell": "卖出佣金率",
    "commission_rate_wan": "万分佣金率",
    "component": "组件",
    "config": "配置",
    "config_id": "配置ID",
    "children_count": "子项数量",
    "condition_json": "条件",
    "confirmation_required": "需要确认",
    "current_step": "当前步骤",
    "rbac_role": "角色",
    "correlation_id": "关联ID",
    "confidence": "置信度",
    "created_by": "创建人",
    "count": "数量",
    "created_at": "创建时间",
    "currency": "币种",
    "current_regime": "当前环境",
    "daily_quota_limit": "每日配额上限",
    "data_freshness": "数据时效",
    "date": "日期",
    "calculated_at": "计算时间",
    "cache_count": "缓存数量",
    "change_20d": "20日变化",
    "change_5d": "5日变化",
    "default_model": "默认模型",
    "decision_id": "决策ID",
    "description": "说明",
    "detail": "详情",
    "dimension": "维度",
    "direction": "方向",
    "display_label": "显示标签",
    "display_name": "显示名称",
    "drawdown_pct": "回撤率",
    "effective_date": "生效日期",
    "enabled": "启用",
    "error": "错误",
    "env": "环境",
    "event_id": "事件ID",
    "evidence_url": "证据链接",
    "execution_mode": "执行模式",
    "expected_volatility": "预期波动",
    "fallback_used": "已使用降级",
    "external_id": "外部ID",
    "extract_content": "提取正文",
    "fetch_interval_hours": "抓取间隔小时",
    "fetched_at": "抓取时间",
    "filters_available": "可用滤波器",
    "finished_at": "完成时间",
    "from_currency": "源币种",
    "fund_name": "基金名称",
    "full_path": "完整路径",
    "human_readable_invalidation": "证伪条件",
    "id": "ID",
    "generated_at": "生成时间",
    "growth_momentum_z": "增长动量Z值",
    "hedge_recommendation": "对冲建议",
    "initial_capital": "初始资金",
    "invested_ratio": "已投资比例",
    "invested_value": "已投资市值",
    "ip_address": "IP地址",
    "is_active": "是否启用",
    "has_ai_config": "已配置 AI",
    "has_script_config": "已配置脚本",
    "invalidated": "已失效",
    "is_base": "是否基准",
    "is_healthy": "是否健康",
    "is_stale": "是否过期",
    "inflation_momentum_z": "通胀动量Z值",
    "interaction_effect": "交互效应",
    "key": "键",
    "label": "标签",
    "last_check": "最近检查",
    "last_error": "最近错误",
    "latest_index_date": "最近指数日期",
    "last_snapshot_at": "最近快照时间",
    "last_used_at": "最近使用时间",
    "level": "等级",
    "logic_desc": "逻辑说明",
    "lesson_learned": "复盘经验",
    "message": "消息",
    "max_drawdown": "最大回撤",
    "max_pe": "最大PE",
    "max_tokens": "最大Token数",
    "max_turnover": "最大换手",
    "name": "名称",
    "market_value": "市值",
    "metadata": "元数据",
    "mcp_client_id": "MCP客户端ID",
    "min_commission": "最低佣金",
    "min_drawdown": "最小回撤",
    "min_pe": "最小PE",
    "model_artifact_hash": "模型产物哈希",
    "model_id": "模型ID",
    "module": "模块",
    "observed_at": "观测时间",
    "occurred_at": "发生时间",
    "owner_id": "所有者ID",
    "password": "访问密码",
    "parent": "上级",
    "path": "路径",
    "pending_tasks_count": "待处理任务",
    "next": "下一页",
    "normal_sla_hours": "普通SLA小时",
    "override": "覆盖值",
    "p23_sla_hours": "P2/P3 SLA小时",
    "period_days": "周期天数",
    "page": "页码",
    "page_size": "每页行数",
    "previous": "上一页",
    "precision": "精度",
    "priority": "优先级",
    "profit_loss": "盈亏",
    "portfolio": "组合",
    "portfolio_id": "组合ID",
    "portfolio_type": "组合类型",
    "portfolio_return": "组合收益",
    "position_size_expr": "仓位规模表达式",
    "position_limit_pct": "持仓上限率",
    "price": "价格",
    "performance": "绩效",
    "provider_type": "服务商类型",
    "prompt_template": "Prompt模板",
    "pulse_contribution": "脉搏贡献",
    "published_at": "发布时间",
    "provider_id": "数据源ID",
    "pk": "记录ID",
    "queue": "队列",
    "rank": "排名",
    "rate": "汇率",
    "rebalance_frequency": "再平衡频率",
    "ratio": "比例",
    "records_count": "记录数量",
    "recommended_sectors": "推荐板块",
    "regime_accuracy": "环境准确率",
    "regime_contribution": "环境贡献",
    "regime_context": "环境上下文",
    "regime_name": "环境名称",
    "reasoning": "原因说明",
    "report_id": "报告ID",
    "regime": "环境",
    "request_id": "请求ID",
    "requires_password": "需要密码",
    "requires_mcp": "需要MCP",
    "requires_confirmation": "需要确认",
    "result": "结果",
    "return_7d": "7日收益",
    "return_30d": "30日收益",
    "regime_fit_score": "环境匹配评分",
    "risk_level": "风险等级",
    "risk_score": "风险评分",
    "risk_tolerance": "风险承受度",
    "rule_name": "规则名称",
    "rule_type": "规则类型",
    "runtime_seconds": "运行秒数",
    "schema_version": "结构版本",
    "scope_label": "范围",
    "score": "评分",
    "selection_effect": "选股效应",
    "sell_condition_expr": "卖出条件",
    "sell_price_expr": "卖出价格表达式",
    "share_level": "分享等级",
    "share_link": "分享链接",
    "sharpe_ratio": "夏普比率",
    "service": "服务",
    "signal": "信号",
    "slippage_rate": "滑点率",
    "sort_order": "排序",
    "source": "来源",
    "source_range_end": "来源区间结束",
    "source_range_start": "来源区间开始",
    "scale_score": "规模评分",
    "start_date": "开始日期",
    "stamp_duty_rate": "印花税率",
    "stamp_duty_rate_qian": "千分印花税率",
    "started_at": "开始时间",
    "status": "状态",
    "status_display": "状态文本",
    "stop_loss_expr": "止损表达式",
    "stop_loss_pct": "止损率",
    "success": "成功",
    "successful_accesses": "成功访问次数",
    "short_code": "短码",
    "snapshot": "快照",
    "subtitle": "副标题",
    "summary": "说明",
    "symbol": "符号",
    "system_prompt": "系统提示词",
    "task": "任务",
    "task_domain": "任务域",
    "task_domain_display": "任务域标签",
    "temperature": "温度",
    "template_content": "模板内容",
    "theme": "主题",
    "timestamp": "时间",
    "title": "标题",
    "to_currency": "目标币种",
    "total_accesses": "总访问次数",
    "total_capital_inflow": "累计资金流入",
    "total_capital_outflow": "累计资金流出",
    "total_cost": "总成本",
    "total_pnl": "总盈亏",
    "total_pnl_pct": "总盈亏率",
    "total_trades": "总交易次数",
    "top_n": "候选数量",
    "total": "合计",
    "total_assets": "总资产",
    "total_score": "总评分",
    "total_return": "总收益",
    "total_return_pct": "总收益率",
    "transfer_fee_rate": "过户费率",
    "type": "类型",
    "underlying_index": "跟踪指数",
    "unit": "单位",
    "unique_visitors": "独立访问者",
    "universe": "标的范围",
    "updated_at": "更新时间",
    "url": "链接",
    "user": "用户",
    "username": "用户名",
    "auto_trading_enabled": "自动交易启用",
    "capability_key": "能力标识",
    "version": "版本",
    "fund_code": "基金代码",
    "inception_date": "起始日期",
    "last_trade_date": "最近交易日期",
    "net_capital_flow": "净资金流",
    "net_value": "净值",
    "input_payload": "输入参数",
    "rules_count": "规则数量",
    "steps_count": "步骤数量",
    "proposals_count": "提案数量",
    "artifacts_count": "产物数量",
    "timeline_events_count": "时间线事件数量",
    "triggered": "已触发",
    "watch": "观察",
    "watch_indicators": "观察指标",
    "candidate": "候选",
    "by_type": "按类型",
    "by_status": "按状态",
    "by_direction": "按方向",
    "investable": "可投资",
    "performance_score": "绩效评分",
    "prohibited": "禁投",
    "take_profit_expr": "止盈表达式",
    "value": "值",
    "winning_trades": "盈利交易次数",
    "win_rate": "胜率",
    "weight": "权重",
    "weights": "权重",
    "visibility": "可见性",
    "worker": "执行节点",
}

FIELD_TOKEN_LABELS = {
    "account": "账户",
    "accounts": "账户",
    "action": "动作",
    "aggregate": "聚合",
    "active": "启用",
    "alpha": "Alpha",
    "amount": "金额",
    "answer": "回答",
    "artifact": "产物",
    "asset": "资产",
    "assets": "资产",
    "accuracy": "准确率",
    "audit": "审计",
    "auto": "自动",
    "base": "基准",
    "balance": "余额",
    "band": "区间",
    "backend": "后端",
    "benchmark": "基准",
    "benefiting": "受益",
    "blocked": "阻塞",
    "bond": "债券",
    "broker": "Broker",
    "builtin": "内置",
    "buy": "买入",
    "capability": "能力",
    "capital": "资金",
    "cash": "现金",
    "category": "分类",
    "causation": "因果",
    "checked": "检查",
    "client": "客户端",
    "code": "代码",
    "commission": "佣金",
    "component": "组件",
    "composite": "综合",
    "condition": "条件",
    "config": "配置",
    "confirmation": "确认",
    "commodity": "商品",
    "contribution": "贡献",
    "content": "内容",
    "context": "上下文",
    "correlation": "关联",
    "confidence": "置信度",
    "count": "数量",
    "created": "创建",
    "currency": "币种",
    "current": "当前",
    "data": "数据",
    "daily": "每日",
    "date": "日期",
    "default": "默认",
    "decision": "决策",
    "decisions": "决策",
    "description": "说明",
    "dimension": "维度",
    "direction": "方向",
    "distribution": "分布",
    "display": "显示",
    "disabled": "停用",
    "enabled": "启用",
    "error": "错误",
    "event": "事件",
    "evidence": "证据",
    "effective": "生效",
    "equity": "权益",
    "execution": "执行",
    "expr": "表达式",
    "expected": "预期",
    "extreme": "极端",
    "external": "外部",
    "extract": "提取",
    "factor": "因子",
    "fallback": "降级",
    "fetch": "抓取",
    "fetched": "抓取",
    "finished": "完成",
    "from": "源",
    "fund": "基金",
    "full": "完整",
    "freshness": "时效",
    "generated": "生成",
    "gate": "闸门",
    "growth": "增长",
    "group": "组",
    "has": "已配置",
    "health": "健康",
    "healthy": "健康",
    "human": "可读",
    "id": "ID",
    "indicator": "指标",
    "initial": "初始",
    "investable": "可投资",
    "invested": "已投资",
    "invalidation": "证伪",
    "inflation": "通胀",
    "interaction": "交互",
    "is": "是否",
    "key": "键",
    "label": "标签",
    "learned": "经验",
    "level": "等级",
    "lesson": "复盘",
    "liquidity": "流动性",
    "limit": "上限",
    "logic": "逻辑",
    "links": "链接",
    "message": "消息",
    "market": "市场",
    "max": "最大",
    "mcp": "MCP",
    "metadata": "元数据",
    "min": "最小",
    "model": "模型",
    "module": "模块",
    "momentum": "动量",
    "movement": "变化",
    "name": "名称",
    "observed": "观测",
    "occurred": "发生",
    "operator": "运算符",
    "order": "顺序",
    "owner": "所有者",
    "outside": "外部",
    "only": "仅",
    "parent": "上级",
    "path": "路径",
    "pending": "待处理",
    "params": "参数",
    "portfolio": "组合",
    "position": "持仓",
    "positions": "持仓",
    "probability": "概率",
    "pct": "率",
    "percent": "比例",
    "precision": "精度",
    "priority": "优先级",
    "prompt": "提示词",
    "published": "发布",
    "price": "价格",
    "profit": "盈利",
    "performance": "绩效",
    "policy": "政策",
    "prohibited": "禁投",
    "queue": "队列",
    "quotas": "配额",
    "rank": "排名",
    "ranked": "排名",
    "rate": "率",
    "readable": "可读",
    "reachable": "可达",
    "rebalance": "再平衡",
    "records": "记录",
    "required": "需要",
    "requires": "需要",
    "role": "角色",
    "regime": "环境",
    "recommended": "推荐",
    "report": "报告",
    "request": "请求",
    "requested": "请求",
    "requests": "请求",
    "return": "收益",
    "route": "路由",
    "loss": "亏损",
    "runtime": "运行",
    "seconds": "秒数",
    "sell": "卖出",
    "score": "评分",
    "scope": "范围",
    "sentiment": "情绪",
    "signal": "信号",
    "sort": "排序",
    "source": "来源",
    "sources": "来源",
    "stable": "稳定",
    "stamp": "印花",
    "status": "状态",
    "stocks": "股票",
    "short": "短",
    "snapshot": "快照",
    "started": "开始",
    "strategy": "策略",
    "styles": "风格",
    "subtitle": "副标题",
    "system": "系统",
    "task": "任务",
    "tasks": "任务",
    "template": "模板",
    "threshold": "阈值",
    "theme": "主题",
    "time": "时间",
    "timestamp": "时间",
    "title": "标题",
    "to": "目标",
    "tokens": "Token",
    "top": "前列",
    "trends": "趋势",
    "transition": "切换",
    "transitioning": "切换中",
    "transfer": "过户",
    "transaction": "交易",
    "transactions": "交易",
    "turnover": "换手",
    "total": "合计",
    "type": "类型",
    "underlying": "跟踪",
    "unsafe": "受限",
    "unit": "单位",
    "updated": "更新",
    "url": "链接",
    "user": "用户",
    "username": "用户名",
    "value": "值",
    "version": "版本",
    "domain": "域",
    "visibility": "可见性",
    "volatility": "波动",
    "visitor": "访问者",
    "visitors": "访问者",
    "warning": "预警",
    "warnings": "预警",
    "winning": "盈利",
    "weight": "权重",
    "weights": "权重",
    "worker": "执行节点",
    "workflow": "流程",
}

STATUS_LABELS = {
    "OK": "正常",
    "EMPTY": "暂无数据",
    "REDIRECT": "跳转",
    "ERROR": "错误",
}

VALUE_LABELS = {
    "active": "启用",
    "degraded": "降级",
    "disabled": "禁用",
    "draft": "草稿",
    "enabled": "启用",
    "error": "错误",
    "expired": "已过期",
    "failed": "失败",
    "fresh": "最新",
    "healthy": "健康",
    "high": "高",
    "inactive": "停用",
    "low": "低",
    "market": "市场",
    "medium": "中",
    "moderate": "中等",
    "ok": "正常",
    "overheat": "过热",
    "pending": "待处理",
    "password_invalid": "密码错误",
    "password_required": "需要密码",
    "ready": "就绪",
    "recession": "衰退",
    "recovery": "复苏",
    "regime": "环境引擎",
    "revoked": "已撤销",
    "running": "运行中",
    "safe": "安全",
    "stagflation": "滞胀",
    "stable": "稳定",
    "success": "成功",
    "system": "系统",
    "warning": "预警",
    "filter api": "筛选服务",
    "buy": "买入",
}
EMBEDDED_VALUE_LABELS = {
    "overheat": "过热",
    "recession": "衰退",
    "recovery": "复苏",
    "stagflation": "滞胀",
}
FIELD_VALUE_LABELS = {
    "account_type": {
        "real": "实盘",
        "simulated": "模拟",
    },
    "portfolio_type": {
        "real": "实盘",
        "simulated": "模拟",
    },
    "rbac_role": {
        "admin": "管理员",
        "observer": "观察者",
        "owner": "所有者",
        "viewer": "查看者",
    },
    "risk_tolerance": {
        "aggressive": "激进",
        "conservative": "保守",
        "moderate": "中等",
    },
    "share_level": {
        "snapshot": "快照",
    },
    "task_domain": {
        "research": "研究",
    },
    "task_domain_display": {
        "research": "研究",
    },
    "visibility": {
        "private": "私密",
        "public": "公开",
    },
}


class _PlainTextHTMLParser(HTMLParser):
    """Extract readable text from legacy HTML/HTMX fragments."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self._parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self._parts).splitlines():
            collapsed = re.sub(r"\s+", " ", line).strip()
            if collapsed:
                lines.append(collapsed)
        return "\n".join(lines)


class TuiWorkbenchRegistry:
    """Compatibility facade for the first TUI workbench endpoints."""

    def __init__(self, metadata_repository: TuiMetadataRepository) -> None:
        self._service = TuiWorkbenchService(metadata_repository=metadata_repository)

    def list_modules(self, *, user: Any | None = None) -> dict[str, Any]:
        """Return the legacy registry shape using the published catalog."""

        catalog = self._service.get_catalog(user=user)
        return {
            "version": "tui-workbench.v2",
            "default_module": catalog["default_screen"].split(".")[0],
            "interaction_model": catalog["interaction_model"],
            "principles": catalog["principles"],
            "groups": [
                {
                    "key": group["key"],
                    "label": group["label"].upper(),
                    "modules": group["modules"],
                }
                for group in catalog["groups"]
            ],
        }

    def get_module_snapshot(self, module_key: str, *, user: Any | None = None) -> dict[str, Any]:
        """Return a legacy snapshot mapped from the first screen in a module."""

        catalog = self._service.get_catalog(user=user)
        screen_key = catalog["default_screen"]
        for group in catalog["groups"]:
            for module in group["modules"]:
                if module["key"] == module_key and module.get("screens"):
                    screen_key = module["screens"][0]["key"]
                    break
        screen = self._service.get_screen(
            screen_key,
            include_technical_actions=True,
            user=user,
        )
        return {
            "version": "tui-workbench.v2",
            "module": screen["module"],
            "layout": screen["layout"],
            "blocks": screen["blocks"],
            "actions": screen["actions"],
        }


class TuiWorkbenchService:
    """Application service for metadata-published TUI catalog and actions."""

    def __init__(
        self,
        *,
        metadata_repository: TuiMetadataRepository,
        action_executor: TuiActionExecutor | None = None,
        audit_repository: TerminalAuditRepository | None = None,
        require_audit_sink: bool = False,
        registry_key: str = "default",
    ) -> None:
        self.metadata_repository = metadata_repository
        self.action_executor = action_executor
        self.audit_sink = (
            TuiTerminalAuditSink(audit_repository) if audit_repository is not None else None
        )
        self.require_audit_sink = require_audit_sink
        self.registry_key = registry_key

    def get_catalog(self, *, user: Any | None = None) -> dict[str, Any]:
        """Return grouped modules and screens from published metadata only."""

        metadata = self._metadata()
        actions = self._screen_visible_actions(metadata, user=user)
        actions_by_screen = self._actions_by_screen(actions)
        screens_by_module = self._screens_by_module(metadata)
        groups: list[dict[str, Any]] = []

        for group in metadata["groups"]:
            group_modules = []
            for module in metadata["modules"]:
                if module["group"] != group["key"]:
                    continue
                screens = []
                for screen in screens_by_module.get(module["key"], []):
                    screen_actions = actions_by_screen.get(screen["key"], [])
                    if not screen_actions and screen["key"] != metadata["default_screen"]:
                        continue
                    screens.append(self._screen_summary(screen, screen_actions))
                if not screens:
                    continue
                group_modules.append(
                    {
                        **self._module_summary(module),
                        "screens": screens,
                        "action_count": sum(screen["action_count"] for screen in screens),
                    }
                )
            if group_modules:
                groups.append(
                    {"key": group["key"], "label": group["label"], "modules": group_modules}
                )

        return {
            "version": metadata["version"],
            "registry_key": metadata.get("registry_key", self.registry_key),
            "interaction_model": metadata.get(
                "interaction_model", "published-metadata-to-pc-tools"
            ),
            "default_screen": metadata["default_screen"],
            "principles": metadata.get("principles", []),
            "stats": self._catalog_stats(metadata, actions),
            "groups": groups,
            "modules": [self._module_summary(module) for module in metadata["modules"]],
        }

    def get_screen(
        self,
        screen_key: str,
        *,
        include_technical_actions: bool = False,
        user: Any | None = None,
    ) -> dict[str, Any]:
        """Return a renderable screen contract from published metadata."""

        metadata = self._metadata()
        screen = (
            self._screen_by_key(metadata).get(screen_key)
            or self._screen_by_key(metadata)[metadata["default_screen"]]
        )
        module = self._module_by_key(metadata)[screen["module_key"]]
        actions = [
            action
            for action in self._screen_visible_actions(
                metadata,
                user=user,
                include_technical=include_technical_actions,
            )
            if action["screen_key"] == screen["key"]
        ]
        return {
            "version": metadata["version"],
            "screen": self._screen_summary(screen, actions),
            "module": self._module_summary(module),
            "layout": {
                "type": "pc-tools-workbench",
                "regions": ("module_tree", "workspace", "inspector", "status_bar", "raw_drawer"),
                "default_view": screen["view_type"],
            },
            "blocks": [
                {
                    "type": "screen-context",
                    "title": self._operator_text(screen["label"]),
                    "body": self._operator_text(screen["summary"]),
                    "status": screen.get("status", "online"),
                },
                {
                    "type": "actions",
                    "title": "任务",
                    "items": [
                        self._action_payload(
                            action,
                            include_technical=include_technical_actions,
                        )
                        for action in actions
                    ],
                },
            ],
            "actions": [
                self._action_payload(
                    action,
                    include_technical=include_technical_actions,
                )
                for action in actions
            ],
        }

    def run_action(
        self,
        *,
        action_key: str,
        params: dict[str, Any],
        user: Any,
        session: Any | None = None,
        confirmed: bool = False,
        confirmation: dict[str, Any] | None = None,
        reauth: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one published action and return a business-first view model."""

        if self.action_executor is None:
            raise ValueError("TUI action executor is not configured")

        action = self._action_by_key(action_key, user=user)
        if action is None:
            raise KeyError(action_key)
        if str(action["risk"]) not in self._allowed_runtime_risks(user):
            raise PermissionError(
                "Only read/AI/confirmed write actions are enabled in this TUI surface"
            )
        self._ensure_tui_audit_sink(action)
        resolved_params = self._apply_default_field_values(action, params or {})
        missing_fields = self._missing_required_fields(action, resolved_params)
        if missing_fields:
            result = self._missing_required_fields_payload(action, missing_fields)
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="rejected_missing_fields",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result
        if self._requires_confirmation(action) and not confirmed:
            result = self._confirmation_required_payload(action)
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="blocked_confirmation_required",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result
        if self._requires_password(action) and not self._reauth_verified(user, reauth):
            result = self._password_challenge_required_payload(action, attempted=bool(reauth))
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="blocked_reauth_failed" if reauth else "blocked_reauth_required",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth,
                result=result,
            )
            return result

        reauth_evidence = (
            verified_reauth_evidence(reauth) if self._requires_password(action) else reauth
        )
        method = str(action["method"]).upper()
        try:
            endpoint, request_params = self._bind_endpoint_params(
                endpoint=str(action["endpoint"]),
                params=resolved_params,
            )
            result = self.action_executor.execute(
                method=method,
                endpoint=endpoint,
                params=request_params if method == "GET" else {},
                body=request_params if method != "GET" else {},
                user=user,
                session=session,
            )
            status_code = int(result.get("status_code", 200))
            payload = result.get("payload")
            view_model = self._to_view_model(
                action=action,
                payload=payload,
                status_code=status_code,
                request_params=request_params,
            )
            envelope = {
                "version": "tui-workbench.v2",
                "action": self._action_payload(action),
                "confirmation_required": False,
                "response": {
                    "status_code": status_code,
                },
                "view_model": view_model,
                "debug": {
                    "raw_available": bool(action.get("raw_debug", True)),
                    "raw_response": payload if action.get("raw_debug", True) else None,
                },
            }
        except Exception as exc:
            self._append_tui_audit(
                action,
                resolved_params,
                user=user,
                session=session,
                outcome="failed_exception",
                confirmation_evidence=confirmation,
                reauth_evidence=reauth_evidence,
                error=str(exc),
            )
            raise

        self._append_tui_audit(
            action,
            resolved_params,
            user=user,
            session=session,
            outcome=(
                "succeeded" if 200 <= int(envelope["response"]["status_code"]) < 400 else "failed"
            ),
            confirmation_evidence=confirmation,
            reauth_evidence=reauth_evidence,
            result=envelope,
        )
        return envelope

    def _apply_default_field_values(
        self,
        action: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = dict(params or {})
        for field in action.get("fields") or []:
            key = str(field.get("key") or "").strip()
            if not key:
                continue
            default = self._resolved_field_default(action, field)
            if default in (None, ""):
                continue
            if resolved.get(key) in (None, ""):
                resolved[key] = default
        return resolved

    def _confirmation_required_payload(self, action: dict[str, Any]) -> dict[str, Any]:
        message = f"此操作会修改系统状态：{action['label']}。确认后才会执行。"
        view_model = self._message_model(action, message, 409)
        view_model["status"] = "待确认"
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action),
            "confirmation_required": True,
            "confirmation": {
                "title": "确认操作",
                "message": message,
                "confirm_label": "确认执行",
                "cancel_label": "取消",
            },
            "response": {"status_code": 409},
            "view_model": view_model,
            "debug": {"raw_available": False, "raw_response": None},
        }

    def _password_challenge_required_payload(
        self, action: dict[str, Any], *, attempted: bool = False
    ) -> dict[str, Any]:
        message = (
            "密码验证未通过，请重新输入当前登录用户密码。"
            if attempted
            else f"此操作需要重新验证身份：{action['label']}。"
        )
        view_model = self._message_model(action, message, 401)
        view_model["status"] = "需要密码"
        view_model["sections"] = [
            {
                "title": "身份验证",
                "rows": [],
                "body": [message, "验证通过前不会执行后端动作。"],
            }
        ]
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action),
            "confirmation_required": False,
            "password_challenge_required": True,
            "password_challenge": {
                "challenge_id": str(action.get("key") or ""),
                "message": message,
                "field": {
                    "key": "password",
                    "label": "密码",
                    "input_type": "password",
                    "required": True,
                },
            },
            "response": {"status_code": 401},
            "view_model": view_model,
            "debug": {"raw_available": False, "raw_response": None},
        }

    def _missing_required_fields(
        self, action: dict[str, Any], params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for field in action.get("fields") or []:
            if not field.get("required"):
                continue
            key = str(field.get("key") or "")
            if not key:
                continue
            if field.get("default") not in (None, ""):
                continue
            value = params.get(key)
            if value in (None, "") or (isinstance(value, list) and not value):
                missing.append(self._field_payload(field))
        return missing

    def _missing_required_fields_payload(
        self, action: dict[str, Any], missing_fields: list[dict[str, Any]]
    ) -> dict[str, Any]:
        labels = [str(field.get("label") or field.get("key") or "") for field in missing_fields]
        message = f"执行“{action['label']}”前需要补充参数：{', '.join(labels)}。"
        view_model = self._message_model(action, message, 400)
        view_model["status"] = "需要参数"
        view_model["sections"] = [
            {
                "title": "需要补充参数",
                "rows": [
                    {
                        "label": str(field.get("label") or field.get("key") or ""),
                        "value": str(
                            field.get("placeholder")
                            or f"请输入{field.get('label') or field.get('key')}"
                        ),
                    }
                    for field in missing_fields
                ],
                "body": [
                    "在左侧任务表单填写后再执行。",
                    "如果当前表格已有对应记录，可先选中一行，再按 F9 进入任务区使用“从选中行填参”，或用右侧“选中行可做”自动填参。",
                ],
            }
        ]
        return {
            "version": "tui-workbench.v2",
            "action": self._action_payload(action),
            "confirmation_required": False,
            "response": {"status_code": 400},
            "view_model": view_model,
            "missing_fields": missing_fields,
            "debug": {"raw_available": False, "raw_response": None},
        }

    def _bind_endpoint_params(
        self, *, endpoint: str, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Substitute reviewed path placeholders and leave the rest as query/body params."""

        bound = "/" + endpoint.lstrip("/")
        remaining = dict(params)

        def replace_converter(match: re.Match[str]) -> str:
            name = match.group("name")
            return self._pop_path_value(remaining, name)

        def replace_braced(match: re.Match[str]) -> str:
            name = match.group("name")
            return self._pop_path_value(remaining, name)

        def replace_colon(match: re.Match[str]) -> str:
            name = match.group("name")
            return f"/{self._pop_path_value(remaining, name)}"

        bound = re.sub(
            r"<(?:(?P<converter>[a-zA-Z_][a-zA-Z0-9_]*):)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>",
            replace_converter,
            bound,
        )
        bound = re.sub(r"\{(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\}", replace_braced, bound)
        bound = re.sub(r"/:(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)", replace_colon, bound)
        if re.search(r"(<[^>]+>|\{[^}]+\}|/:[a-zA-Z_][a-zA-Z0-9_]*)", bound):
            raise ValueError("Action requires path parameters before it can run")
        return bound, remaining

    def _pop_path_value(self, params: dict[str, Any], name: str) -> str:
        value = params.pop(name, None)
        if value in (None, ""):
            raise ValueError(f"Missing required path parameter: {name}")
        text = str(value).strip()
        if "/" in text or "?" in text or "#" in text:
            raise ValueError(f"Unsafe path parameter: {name}")
        return text

    def _metadata(self) -> dict[str, Any]:
        return self.metadata_repository.load_published(self.registry_key)

    def _allowed_runtime_risks(self, user: Any | None) -> set[str]:
        allowed = set(VISIBLE_RUNTIME_RISKS)
        if self._is_admin_user(user):
            allowed |= ADMIN_RUNTIME_RISKS
        return allowed

    def _is_admin_user(self, user: Any | None) -> bool:
        if user is None:
            return False
        if bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
            return True
        role = str(getattr(user, "rbac_role", "") or "").strip().lower()
        if role == "admin":
            return True
        profile = getattr(user, "account_profile", None)
        profile_role = str(getattr(profile, "rbac_role", "") or "").strip().lower()
        return profile_role == "admin"

    def _visible_actions(
        self, metadata: dict[str, Any], *, user: Any | None = None
    ) -> list[dict[str, Any]]:
        return [
            action
            for action in metadata["actions"]
            if str(action.get("risk")) in self._allowed_runtime_risks(user)
            and self._action_is_available_for_user(action, user=user)
        ]

    def _screen_visible_actions(
        self,
        metadata: dict[str, Any],
        *,
        user: Any | None = None,
        include_technical: bool = False,
    ) -> list[dict[str, Any]]:
        actions = self._visible_actions(metadata, user=user)
        if include_technical:
            return actions
        return [
            action
            for action in actions
            if str(action.get("key") or "") not in USER_HIDDEN_SCREEN_ACTION_KEYS
        ]

    def _action_is_available_for_user(
        self,
        action: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> bool:
        action_key = str(action.get("key") or "")
        predicate = USER_CONDITIONAL_SCREEN_ACTIONS.get(action_key)
        if predicate is not None:
            return bool(predicate(user))
        return True

    def _action_by_key(self, action_key: str, *, user: Any | None = None) -> dict[str, Any] | None:
        for action in self._visible_actions(self._metadata(), user=user):
            if action["key"] == action_key:
                return action
        return None

    def _requires_confirmation(self, action: dict[str, Any]) -> bool:
        if bool(action.get("confirmation_required")):
            return True
        risk = str(action.get("risk") or "").lower()
        method = str(action.get("method") or "GET").upper()
        return risk == "write" or (risk == "admin" and method != "GET")

    def _requires_password(self, action: dict[str, Any]) -> bool:
        return bool(action.get("requires_password"))

    def _reauth_verified(self, user: Any | None, reauth: dict[str, Any] | None) -> bool:
        if not isinstance(reauth, dict):
            return False
        if str(reauth.get("method") or "").lower() != "password":
            return False
        credential = str(reauth.get("credential") or "")
        if not credential:
            return False
        checker = getattr(user, "check_password", None)
        if not callable(checker):
            return False
        return bool(checker(credential))

    def _append_tui_audit(
        self,
        action: dict[str, Any],
        params: dict[str, Any],
        *,
        user: Any | None,
        session: Any | None,
        outcome: str,
        confirmation_evidence: dict[str, Any] | None = None,
        reauth_evidence: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        if not action_requires_audit(action) or self.audit_sink is None:
            return
        try:
            username = str(getattr(user, "username", "") or "anonymous")
            record = build_tui_audit_record(
                action,
                params,
                actor=username,
                outcome=outcome,
                confirmation_evidence=confirmation_evidence,
                reauth_evidence=reauth_evidence,
                result=result,
                error=error,
            )
            self.audit_sink.append(
                record,
                user_id=getattr(user, "id", None),
                username=username,
                session_id=self._session_id(session),
            )
        except Exception:
            if self.require_audit_sink:
                raise
            return

    def _ensure_tui_audit_sink(self, action: dict[str, Any]) -> None:
        if self.require_audit_sink and action_requires_audit(action) and self.audit_sink is None:
            raise RuntimeError(
                f"Audit sink is required for audit_required action: {action.get('key')}"
            )

    def _session_id(self, session: Any | None) -> str:
        if session is None:
            return ""
        return str(getattr(session, "session_key", "") or "")

    def _actions_by_screen(self, actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for action in actions:
            grouped.setdefault(action["screen_key"], []).append(action)
        return grouped

    def _screens_by_module(self, metadata: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for screen in metadata["screens"]:
            grouped.setdefault(screen["module_key"], []).append(screen)
        return grouped

    def _module_by_key(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {module["key"]: module for module in metadata["modules"]}

    def _screen_by_key(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {screen["key"]: screen for screen in metadata["screens"]}

    def _to_view_model(
        self,
        *,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._unwrap_payload(payload)
        forced_kind = self._view_model_path(action, "kind")
        if isinstance(data, dict) and self._is_endpoint_directory(data):
            return self._endpoint_directory_model(action, data, status_code)
        if forced_kind == "detail" and isinstance(data, dict):
            return self._detail_model(action, data, status_code)
        if forced_kind == "message":
            return {
                "kind": "message",
                "title": self._action_title(action),
                "status": self._status_label(status_code),
                "message": self._display_value(data),
                "raw_hint": "原始响应只在调试抽屉中查看。",
            }
        if forced_kind == "datagrid":
            if isinstance(data, list):
                return self._datagrid_model(
                    action, data, status_code, request_params=request_params
                )
            if isinstance(data, dict):
                rows_path = self._view_model_path(action, "rows_path")
                if not rows_path and self._looks_like_detail_payload(data):
                    return self._detail_model(action, data, status_code)
                explicit_value = self._value_at_path(data, rows_path) if rows_path else None
                list_value = (
                    explicit_value
                    if isinstance(explicit_value, list)
                    else self._find_list_value(data)
                )
                if list_value is not None:
                    return self._datagrid_model(
                        action,
                        list_value,
                        status_code,
                        envelope=data,
                        request_params=request_params,
                    )
        if isinstance(data, list):
            return self._datagrid_model(
                action, data, status_code, request_params=request_params
            )
        if isinstance(data, dict):
            html_text = self._dominant_html_text(data)
            if html_text:
                return self._message_model(action, html_text, status_code)
            if str(action.get("view_type")) in {"status", "detail", "queue_workbench"}:
                return self._detail_model(action, data, status_code)
            if str(action.get("view_type")) == "datagrid" and self._looks_like_detail_payload(data):
                return self._detail_model(action, data, status_code)
            rows_path = self._view_model_path(action, "rows_path")
            explicit_value = self._value_at_path(data, rows_path) if rows_path else None
            list_value = (
                explicit_value if isinstance(explicit_value, list) else self._find_list_value(data)
            )
            if list_value is not None:
                return self._datagrid_model(
                    action,
                    list_value,
                    status_code,
                    envelope=data,
                    request_params=request_params,
                )
            return self._detail_model(action, data, status_code)
        if self._looks_like_html(data):
            return self._message_model(action, self._html_to_text(str(data)), status_code)
        return {
            "kind": "message",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "message": self._display_value(data),
            "raw_hint": "原始响应只在调试抽屉中查看。",
        }

    def _action_title(self, action: dict[str, Any]) -> str:
        return self._operator_text(action.get("label") or "")

    def _unwrap_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            if "data" in payload and len(payload) <= 4:
                return payload.get("data")
        return payload

    def _view_model_path(self, action: dict[str, Any], key: str) -> str:
        view_model = action.get("view_model") or {}
        if not isinstance(view_model, dict):
            return ""
        return str(view_model.get(key) or "").strip()

    def _value_at_path(self, payload: Any, path: str) -> Any:
        if not path:
            return None
        current = payload
        for part in path.split("."):
            if not part:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if 0 <= index < len(current) else None
            else:
                return None
        return current

    def _find_list_value(self, payload: dict[str, Any]) -> list[Any] | None:
        candidates = self._list_candidates(payload)
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    def _list_candidates(self, value: Any, *, depth: int = 0) -> list[tuple[int, list[Any]]]:
        if depth > 3:
            return []
        if isinstance(value, list):
            return [(self._list_score(value, depth), value)]
        if not isinstance(value, dict):
            return []
        candidates: list[tuple[int, list[Any]]] = []
        for child in value.values():
            candidates.extend(self._list_candidates(child, depth=depth + 1))
        return candidates

    def _list_score(self, rows: list[Any], depth: int) -> int:
        if not rows:
            return 0
        sample = rows[:5]
        dict_rows = sum(1 for row in sample if isinstance(row, dict))
        scalar_rows = sum(1 for row in sample if not isinstance(row, (dict, list)))
        nested_penalty = depth * 4
        return dict_rows * 10 + scalar_rows * 4 + min(len(rows), 20) - nested_penalty

    def _datagrid_model(
        self,
        action: dict[str, Any],
        rows: list[Any],
        status_code: int,
        envelope: dict[str, Any] | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_list = self._message_list_text(rows)
        if message_list:
            return self._message_model(action, message_list, status_code)
        normalized_rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
        normalized_rows = self._filter_rows_for_action(action, normalized_rows)
        columns = self._columns_for_rows(normalized_rows)
        asset_name_map = self._asset_name_map_for_rows(normalized_rows)
        explicit_page_size = self._int_from_path(action, envelope, "page_size_path", default=0)
        request_limit = self._int_from_params(request_params, "limit", default=0)
        page_size = explicit_page_size or request_limit
        if str(action.get("intent")) == "list_ai_capabilities":
            total = len(normalized_rows)
        else:
            total = int(
                self._int_from_path(action, envelope, "total_path", default=0)
                or len(normalized_rows)
            )
        if page_size <= 0:
            page_size = len(normalized_rows) if self._view_model_path(action, "total_path") else 20
        page_size = max(1, page_size)
        explicit_page = self._int_from_path(action, envelope, "page_path", default=0)
        request_offset = self._int_from_params(request_params, "offset", default=0)
        page = explicit_page or max(1, (request_offset // page_size) + 1)
        pagination_mode = (
            "page"
            if explicit_page or self._view_model_path(action, "page_path")
            else "limit_offset"
            if self._view_model_path(action, "total_path")
            else "page"
        )
        return {
            "kind": "datagrid",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "columns": columns,
            "rows": [
                self._datagrid_row_payload(row, columns, asset_name_map)
                for row in normalized_rows[:page_size]
            ],
            "empty_message": self._empty_datagrid_message(action, total),
            "empty_guidance": self._empty_datagrid_guidance(action, total),
            "pager": {
                "page": page,
                "page_size": page_size,
                "offset": request_offset,
                "pagination_mode": pagination_mode,
                "total_rows": total,
                "total_pages": max(1, ceil(total / page_size)),
                "has_next": page * page_size < total,
                "has_previous": page > 1,
            },
        }

    def _datagrid_row_payload(
        self,
        row: dict[str, Any],
        columns: list[dict[str, str]],
        asset_name_map: dict[str, str],
    ) -> dict[str, str]:
        payload: dict[str, Any] = {}
        for column in columns:
            key = column["key"]
            display_value = self._display_row_value(row, key, asset_name_map)
            payload[key] = display_value
            raw_value = row.get(key)
            if self._should_preserve_raw_row_value(key, raw_value, display_value):
                payload[f"__raw_{key}"] = raw_value
        for key, value in row.items():
            normalized_key = str(key)
            if normalized_key.startswith("__"):
                normalized_key = normalized_key[2:]
            if normalized_key in payload or isinstance(value, (dict, list)):
                continue
            if not self._should_preserve_row_identifier(normalized_key):
                continue
            payload[normalized_key] = self._display_row_value(row, key, asset_name_map)
        return payload

    def _should_preserve_row_identifier(self, key: str) -> bool:
        normalized = str(key or "").strip().lower().replace("-", "_")
        return normalized in ROW_IDENTIFIER_FIELDS or normalized.endswith("_id")

    def _should_preserve_raw_row_value(
        self,
        key: str,
        raw_value: Any,
        display_value: str,
    ) -> bool:
        if raw_value in (None, "") or isinstance(raw_value, (dict, list)):
            return False
        normalized = str(key or "").strip().lower().replace("-", "_")
        if not (
            self._should_preserve_row_identifier(normalized)
            or normalized == "code"
            or normalized.endswith("_code")
        ):
            return False
        return str(raw_value) != str(display_value)

    def _filter_rows_for_action(
        self, action: dict[str, Any], rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if str(action.get("intent")) != "list_ai_capabilities":
            return rows
        safe_values = {"safe", "read", "low", "readonly", "无风险", "安全"}
        filtered: list[dict[str, Any]] = []
        for row in rows:
            capability_key = str(row.get("capability_key") or row.get("key") or "")
            if capability_key.startswith("api."):
                continue
            risk = str(row.get("risk_level") or row.get("risk") or "").strip().lower()
            confirmation = row.get("requires_confirmation")
            if isinstance(confirmation, str):
                needs_confirmation = confirmation.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "是",
                }
            else:
                needs_confirmation = bool(confirmation)
            if risk in safe_values and not needs_confirmation:
                filtered.append(self._operator_ai_capability_row(row))
        return filtered

    def _operator_ai_capability_row(self, row: dict[str, Any]) -> dict[str, Any]:
        capability_key = str(row.get("capability_key") or row.get("key") or "")
        curated = {
            "builtin.market_regime": {
                "name": "市场环境判断",
                "summary": "查看当前市场环境、政策档位和基础行动边界。",
            },
            "builtin.system_status": {
                "name": "系统状态",
                "summary": "检查系统健康、就绪状态和基础运行情况。",
            },
            "terminal_command.market_temperature": {
                "name": "市场温度",
                "summary": "查看市场温度、风险区间和过热提示。",
            },
        }.get(capability_key, {})
        return {
            "__capability_key": capability_key,
            "name": curated.get("name") or self._clean_operator_text(row.get("name")),
            "summary": curated.get("summary") or self._clean_operator_text(row.get("summary")),
            "category": self._display_value(row.get("category")),
            "risk_level": self._display_value(row.get("risk_level")),
            "requires_confirmation": self._display_value(row.get("requires_confirmation")),
        }

    def _clean_operator_text(self, value: Any) -> str:
        text = self._display_value(value)
        text = re.sub(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/api/[^\s，。；;]*", "内部接口", text)
        text = re.sub(r"\bAPI endpoint:\s*", "能力入口：", text, flags=re.IGNORECASE)
        text = text.replace("_", " ")
        return text.strip()

    def _operator_text(self, value: Any) -> str:
        """Remove security/compiler jargon from operator-facing labels."""

        text = self._clean_operator_text(value)
        replacements = {
            "自动批准的只读": "已发布的",
            "只读详情工具": "详情工具",
            "只读决策上下文": "决策上下文",
            "只读宏观环境": "宏观环境",
            "只读研究": "研究",
            "只读账户": "账户",
            "只读执行": "执行",
            "只读系统健康": "系统健康",
            "只读": "可查看",
            "直接读取": "直接打开",
            "读取业务视图": "打开业务视图",
            "Beta Gate": "Beta 闸门",
            "Regime": "宏观象限",
            "AI Provider": "AI 服务商",
            "Provider": "服务商",
            "Prompt": "提示词",
            "Chat": "对话",
            "Templates": "模板",
            "Template": "模板",
            "Chains": "链路",
            "Chain": "链路",
            "Logs": "日志",
            "Log": "日志",
            "Assignments": "绑定",
            "Assignment": "绑定",
            "Execution": "执行",
            "Strategy": "策略",
            "Runtime": "运行时",
            "Workflow": "流程",
            "funnel": "漏斗",
            "Conflict": "冲突",
            "Context": "上下文",
            "Params": "参数",
            "Reasoning": "原因说明",
            "Freshness": "时效",
            "Benchmark": "基准",
            "Excess": "超额",
            "Accuracy": "准确率",
            "Records": "记录",
            "Composite": "综合",
            "Liquidity": "流动性",
            "Actionable": "可操作",
            "Aggregated": "汇总",
            "TopStocks": "前列股票",
            "IcTrends": "IC趋势",
            "Top10": "前10",
            "TopRanked": "前列排名",
            "RequestedTrade": "请求交易",
            "PendingRequests": "待处理请求",
            "LessonLearned": "复盘经验",
            "SelectionEffect": "选股效应",
            "RecommendedSectors": "推荐板块",
            "BenefitingStyles": "受益风格",
            "TransitionTarget": "切换目标",
            "TransitionProbability": "切换概率",
            "RiskBudget": "风险预算",
            "PerTrade": "单笔交易",
            "Source": "来源",
            "Keyword": "关键词",
            "Config": "配置",
            "Model": "模型",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\bTop-down\b", "自上而下", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBottom-up\b", "自下而上", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBUY\b", "买入", text)
        text = re.sub(r"\bSELL\b", "卖出", text)
        text = re.sub(r"\bmoderate\b", "中等", text, flags=re.IGNORECASE)
        text = re.sub(r"\bhigh\b", "高", text, flags=re.IGNORECASE)
        text = re.sub(r"\bmedium\b", "中", text, flags=re.IGNORECASE)
        text = re.sub(r"\blow\b", "低", text, flags=re.IGNORECASE)
        text = re.sub(r"\bdelta\b", "调仓差额", text, flags=re.IGNORECASE)
        text = text.replace("绑定s", "绑定")
        text = re.sub(r"\bBy\b", "按", text)
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        return text.strip()

    def _detail_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        fields = self._detail_fields(payload)
        if self._looks_like_password_challenge(status_code, payload):
            fields.append(
                {
                    "key": "operator_hint",
                    "label": "操作提示",
                    "value": "请在当前屏使用“公开分享 / 验证访问”动作输入密码后重试。",
                }
            )
        nested = [
            {"key": key, "label": self._humanize(key), "count": len(value)}
            for key, value in payload.items()
            if isinstance(value, list) and not self._is_technical_detail_field(str(key), value)
        ]
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": self._status_label(status_code, payload),
            "fields": fields,
            "nested": nested,
        }

    def _message_model(
        self, action: dict[str, Any], message: str, status_code: int
    ) -> dict[str, Any]:
        normalized_message = self._operator_text(message)
        return {
            "kind": "message",
            "title": self._action_title(action),
            "status": self._status_label(status_code, {"detail": normalized_message}),
            "message": normalized_message,
            "sections": self._message_sections(normalized_message),
            "raw_hint": "原始响应只在调试抽屉中查看。",
        }

    def _message_list_text(self, rows: list[Any]) -> str:
        if not rows or len(rows) > 12:
            return ""
        if any(isinstance(row, (dict, list, tuple, set)) for row in rows):
            return ""
        messages = [str(row).strip() for row in rows if str(row).strip()]
        if len(messages) != len(rows):
            return ""
        if not any(self._looks_like_message_line(message) for message in messages):
            return ""
        return "\n".join(messages)

    def _looks_like_message_line(self, value: str) -> bool:
        text = str(value or "").strip()
        if len(text) >= 12:
            return True
        return any(marker in text for marker in ("，", "。", "：", ":", "；", " ", "无法", "跳过"))

    def _message_sections(self, message: str) -> list[dict[str, Any]]:
        lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for line in lines:
            inline_heading = self._split_inline_heading(line)
            if inline_heading is not None:
                heading, remainder = inline_heading
                current = {"title": heading, "rows": [], "body": []}
                sections.append(current)
                if remainder:
                    label, value = self._split_message_row(remainder)
                    if label:
                        current["rows"].append({"label": label, "value": value})
                    else:
                        current["body"].append(remainder)
                continue
            if self._is_section_heading(line):
                current = {"title": line, "rows": [], "body": []}
                sections.append(current)
                continue
            if current is None:
                current = {"title": "摘要", "rows": [], "body": []}
                sections.append(current)
            label, value = self._split_message_row(line)
            if label:
                current["rows"].append({"label": label, "value": value})
            else:
                current["body"].append(line)
        return sections[:12]

    def _split_inline_heading(self, line: str) -> tuple[str, str] | None:
        text = line.strip()
        prefix_match = re.match(r"^(阶段\s*\d+\s*[：:])", text)
        if not prefix_match:
            return None
        remainder_text = text[prefix_match.end() :]
        split_match = re.search(
            r"(当前|本阶段|只回答|系统级|若要|工作台|统一|该列表|计划|当前账户|配置建议|轮动信号|推荐偏好)",
            remainder_text,
        )
        if not split_match:
            return None
        heading = f"{prefix_match.group(1)}{remainder_text[: split_match.start()]}".strip()
        remainder = remainder_text[split_match.start() :].strip()
        if not remainder:
            return None
        return heading, remainder

    def _is_section_heading(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) > 36:
            return False
        if stripped.startswith(("阶段", "第")) and ("：" in stripped or ":" in stripped):
            return True
        if stripped.startswith(("📉", "💓", "🏛", "⚠", "✅", "📌")):
            return True
        return bool(re.match(r"^[一二三四五六七八九十]+、", stripped))

    def _split_message_row(self, line: str) -> tuple[str, str]:
        for separator in ("：", ":"):
            if separator in line:
                label, value = line.split(separator, 1)
                if 1 <= len(label.strip()) <= 18 and value.strip():
                    return label.strip(), self._display_value(value.strip())
        return "", ""

    def _is_endpoint_directory(self, payload: dict[str, Any]) -> bool:
        endpoints = payload.get("endpoints")
        if isinstance(endpoints, dict):
            values = [value for value in endpoints.values() if isinstance(value, str)]
            return bool(values) and all(self._is_internal_api_path(value) for value in values)
        if not isinstance(endpoints, list) or not endpoints:
            return self._looks_like_internal_path_directory(payload)
        values = [value for value in endpoints if isinstance(value, str)]
        return bool(values) and all(self._is_internal_api_path(value) for value in values)

    def _endpoint_directory_model(
        self, action: dict[str, Any], payload: dict[str, Any], status_code: int
    ) -> dict[str, Any]:
        raw_endpoints = payload.get("endpoints")
        if isinstance(raw_endpoints, dict):
            endpoint_count = len(raw_endpoints)
        elif isinstance(raw_endpoints, list):
            endpoint_count = len([value for value in raw_endpoints if isinstance(value, str)])
        else:
            endpoint_count = len(self._internal_path_directory_values(payload))
        message = str(payload.get("message") or action["label"]).strip()
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": self._status_label(status_code),
            "fields": [
                {
                    "key": "service",
                    "label": "服务",
                    "value": self._display_value(message),
                },
                {
                    "key": "capability_count",
                    "label": "已登记能力",
                    "value": f"{endpoint_count} 项",
                },
                {
                    "key": "operator_hint",
                    "label": "操作提示",
                    "value": "请从左侧业务任务进入具体操作；内部接口路径只在调试抽屉中查看。",
                },
            ],
            "nested": [],
        }

    def _looks_like_internal_path_directory(self, payload: dict[str, Any]) -> bool:
        values = self._internal_path_directory_values(payload)
        return bool(values) and all(self._is_internal_api_path(value) for value in values)

    def _internal_path_directory_values(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key, value in payload.items():
            if key == "message":
                continue
            if isinstance(value, str):
                values.append(value)
                continue
            if value in (None, ""):
                continue
            return []
        return values

    def _dominant_html_text(self, payload: dict[str, Any]) -> str:
        html_keys = {
            "body",
            "content",
            "html",
            "markup",
            "partial",
            "rendered",
            "template",
        }
        scalar_values = [
            (str(key), value)
            for key, value in payload.items()
            if not isinstance(value, (dict, list))
        ]
        html_values = [
            self._html_to_text(str(value))
            for key, value in scalar_values
            if key.lower() in html_keys and self._looks_like_html(value)
        ]
        if len(scalar_values) == 1 and not html_values:
            only_value = scalar_values[0][1]
            if self._looks_like_html(only_value):
                html_values.append(self._html_to_text(str(only_value)))
        return "\n".join(value for value in html_values if value).strip()

    def _detail_fields(
        self,
        payload: dict[str, Any],
        *,
        prefix: str = "",
        depth: int = 0,
        limit: int = 24,
    ) -> list[dict[str, str]]:
        fields: list[dict[str, str]] = []
        for key, value in payload.items():
            if len(fields) >= limit:
                break
            field_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, list):
                continue
            if self._is_technical_detail_field(field_key, value):
                continue
            if isinstance(value, dict):
                if depth < 1:
                    fields.extend(
                        self._detail_fields(
                            value,
                            prefix=field_key,
                            depth=depth + 1,
                            limit=limit - len(fields),
                        )
                    )
                else:
                    fields.append(
                        {
                            "key": field_key,
                            "label": self._humanize(field_key),
                            "value": f"{len(value)} 个字段",
                        }
                    )
                continue
            fields.append(
                {
                    "key": field_key,
                    "label": self._humanize(field_key),
                    "value": self._display_value_for_key(field_key, value, payload),
                }
            )
        return fields[:limit]

    def _is_technical_detail_field(self, key: str, value: Any) -> bool:
        normalized = str(key or "").strip().lower()
        if normalized == "endpoints" or normalized.startswith("endpoints."):
            return True
        if normalized in {"success", "ok"} and isinstance(value, bool):
            return True
        if isinstance(value, str) and self._is_internal_api_path(value):
            return True
        return False

    def _looks_like_detail_payload(self, payload: dict[str, Any]) -> bool:
        business_items = [
            (str(key or "").strip().lower(), value)
            for key, value in payload.items()
            if str(key or "").strip().lower() not in {"success", "ok", "status", "message"}
        ]
        if not business_items:
            return False
        if len(business_items) == 1 and isinstance(business_items[0][1], dict):
            return True
        list_keys = [key for key, value in business_items if isinstance(value, list)]
        scalar_count = sum(1 for _, value in business_items if not isinstance(value, (dict, list)))
        nested_dict_count = sum(1 for _, value in business_items if isinstance(value, dict))
        has_identifier = any(
            key in {"id", "pk", "name", "title", "code"} for key, _ in business_items
        )
        collection_list_keys = {"results", "items", "data", "records"}
        if len(list_keys) > 1:
            if (
                has_identifier
                and scalar_count >= 3
                and not any(key in collection_list_keys for key in list_keys)
            ):
                return True
            return False
        if len(list_keys) == 1:
            list_key = list_keys[0]
            if list_key in collection_list_keys:
                return False
            if scalar_count >= 1 and any(
                key in {"status", "service", "module"} for key, _ in business_items
            ):
                return True
            return has_identifier and scalar_count >= 2
        if scalar_count >= 3:
            return True
        if nested_dict_count >= 2:
            return True
        return has_identifier and (scalar_count + nested_dict_count) >= 2

    def _asset_name_map_for_rows(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        codes: set[str] = set()
        for row in rows[:200]:
            if self._asset_name_from_row(row):
                continue
            for key, value in row.items():
                if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
                    codes.update(self._asset_lookup_keys(value))
        return resolve_asset_names(sorted(codes)) if codes else {}

    def _display_row_value(
        self,
        row: dict[str, Any],
        key: str,
        asset_name_map: dict[str, str],
    ) -> str:
        value = row.get(key)
        if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
            name = self._asset_name_from_row(row) or self._resolved_asset_name(
                value, asset_name_map
            )
            return self._display_asset_code(value, name)
        contextual = self._field_value_label(key, value)
        if contextual is not None:
            return contextual
        return self._display_value(value)

    def _display_value_for_key(
        self, key: str, value: Any, payload: dict[str, Any] | None = None
    ) -> str:
        if self._is_asset_code_field(key) and self._looks_like_asset_code(value):
            name = self._asset_name_from_row(payload or {})
            if not name:
                lookup_keys = self._asset_lookup_keys(value)
                name = self._resolved_asset_name(
                    value,
                    resolve_asset_names(lookup_keys) if lookup_keys else {},
                )
            return self._display_asset_code(value, name)
        contextual = self._field_value_label(key, value)
        if contextual is not None:
            return contextual
        return self._display_value(value)

    def _field_value_label(self, key: str, value: Any) -> str | None:
        if value is None or isinstance(value, (bool, dict, list)):
            return None
        normalized_key = str(key or "").strip().lower().replace("-", "_").split(".")[-1]
        value_labels = FIELD_VALUE_LABELS.get(normalized_key)
        if not value_labels:
            return None
        normalized_value = str(value).strip().lower()
        if not normalized_value:
            return None
        return value_labels.get(normalized_value)

    def _is_asset_code_field(self, key: str) -> bool:
        last_part = str(key or "").strip().lower().replace("-", "_").split(".")[-1]
        return last_part in ASSET_CODE_FIELDS

    def _looks_like_asset_code(self, value: Any) -> bool:
        if value is None or isinstance(value, bool):
            return False
        text = str(value).strip().upper()
        return bool(ASSET_CODE_PATTERN.match(text))

    def _asset_lookup_keys(self, value: Any) -> list[str]:
        text = str(value or "").strip().upper()
        if not text or not self._looks_like_asset_code(text):
            return []
        keys = [text]
        prefixed = re.match(r"^(SH|SZ|BJ)(\d{6})$", text)
        if prefixed:
            keys.append(f"{prefixed.group(2)}.{prefixed.group(1)}")
            keys.append(prefixed.group(2))
        elif "." in text:
            keys.append(text.split(".", 1)[0])
        return list(dict.fromkeys(keys))

    def _asset_name_from_row(self, row: dict[str, Any]) -> str:
        for key in ASSET_NAME_FIELDS:
            value = str(row.get(key) or "").strip()
            if value:
                return value
        return ""

    def _resolved_asset_name(self, value: Any, asset_name_map: dict[str, str]) -> str:
        for key in self._asset_lookup_keys(value):
            name = str(asset_name_map.get(key) or "").strip()
            if name:
                return name
        return ""

    def _display_asset_code(self, value: Any, name: str) -> str:
        code = self._display_value(value)
        clean_name = str(name or "").strip()
        if not clean_name or clean_name.upper() == str(value or "").strip().upper():
            return code
        if clean_name in code:
            return code
        return f"{code} {clean_name}"

    def _columns_for_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        keys: list[str] = []
        for row in rows[:12]:
            for key, value in row.items():
                if str(key).startswith("__"):
                    continue
                if key not in keys and not isinstance(value, (dict, list)):
                    keys.append(key)
        if not keys and rows:
            keys = [key for key in rows[0].keys() if not str(key).startswith("__")][:6]
        return [{"key": key, "label": self._humanize(key)} for key in keys[:8]]

    def _display_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, (dict, list)):
            return f"{len(value)} 项" if isinstance(value, list) else f"{len(value)} 个字段"
        text = str(value)
        if self._looks_like_html(text):
            return self._html_to_text(text)
        if self._is_internal_api_path(text):
            return "内部接口路径（调试抽屉查看）"
        return VALUE_LABELS.get(text.strip().lower(), text)

    def _is_internal_api_path(self, value: str) -> bool:
        text = str(value or "").strip()
        if text.startswith("/api/") or text.startswith("api/"):
            return True
        parsed = urlparse(text)
        return parsed.path.startswith("/api/")

    def _looks_like_html(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return False
        return bool(HTML_TAG_PATTERN.search(text) or ESCAPED_HTML_TAG_PATTERN.search(text))

    def _html_to_text(self, value: str) -> str:
        parser = _PlainTextHTMLParser()
        parser.feed(unescape(value))
        parser.close()
        text = parser.text()
        if not text:
            text = HTML_TAG_PATTERN.sub(" ", unescape(value))
            text = re.sub(r"\s+", " ", text).strip()
        text = self._translate_embedded_value_labels(text)
        return text[:4000]

    def _translate_embedded_value_labels(self, text: str) -> str:
        result = text
        for source, target in EMBEDDED_VALUE_LABELS.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.IGNORECASE)
        return result

    def _status_label(self, status_code: int, payload: Any | None = None) -> str:
        if 200 <= int(status_code) < 300:
            return STATUS_LABELS["OK"]
        if 300 <= int(status_code) < 400:
            return STATUS_LABELS["REDIRECT"]
        if self._looks_like_password_challenge(status_code, payload):
            return "需要密码"
        if self._looks_like_empty_state(status_code, payload):
            return STATUS_LABELS["EMPTY"]
        return STATUS_LABELS["ERROR"]

    def _looks_like_password_challenge(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 401 or not isinstance(payload, dict):
            return False
        if bool(payload.get("requires_password")):
            return True
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and "密码" in value:
                return True
        return False

    def _looks_like_empty_state(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 404 or not isinstance(payload, dict):
            return False
        detail = payload.get("detail")
        if not isinstance(detail, str):
            return False
        normalized = detail.strip().lower()
        if not normalized:
            return False
        empty_markers = (
            "没有",
            "暂无",
            "not found",
            "does not have",
            "missing",
            "不存在",
            "未配置",
        )
        return any(marker in normalized for marker in empty_markers)

    def _catalog_stats(
        self, metadata: dict[str, Any], visible_actions: list[dict[str, Any]]
    ) -> dict[str, int]:
        stats = {
            "actions": len(visible_actions),
            "published_actions": len(metadata["actions"]),
            "hidden_by_risk": len(metadata["actions"]) - len(visible_actions),
        }
        coverage = metadata.get("coverage_summary") or {}
        deferred = coverage.get("deferred") if isinstance(coverage, dict) else {}
        if isinstance(coverage, dict):
            for key in (
                "safe_read_evidence",
                "direct_safe_read_candidates",
                "parameterized_safe_read_candidates",
                "added_safe_api_actions",
                "added_parameterized_api_actions",
                "smoke_total",
                "smoke_ok",
                "smoke_needs_input",
                "smoke_error",
                "smoke_pruned_auto_actions",
                "business_promoted_actions",
                "approved_operation_actions",
            ):
                try:
                    stats[key] = int(coverage.get(key, 0))
                except (TypeError, ValueError):
                    stats[key] = 0
        if isinstance(deferred, dict):
            for key, value in deferred.items():
                try:
                    stats[f"deferred_{key}"] = int(value)
                except (TypeError, ValueError):
                    stats[f"deferred_{key}"] = 0
        return stats

    def _module_summary(self, module: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": module["key"],
            "label": self._operator_text(module["label"]),
            "group": module["group"],
            "summary": self._operator_text(module["summary"]),
            "status": module.get("status", "online"),
        }

    def _screen_summary(
        self, screen: dict[str, Any], actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "key": screen["key"],
            "label": self._operator_text(screen["label"]),
            "module_key": screen["module_key"],
            "group": screen["group"],
            "summary": self._operator_text(screen["summary"]),
            "view_type": screen["view_type"],
            "status": screen.get("status", "online"),
            "default_action_key": screen.get("default_action_key", ""),
            "action_count": len(actions),
            "dashboard_panels": list(screen.get("dashboard_panels") or []),
            "workflow": dict(screen.get("workflow") or {}),
            "business_context": self._screen_business_context(screen, actions),
        }

    def _screen_business_context(
        self, screen: dict[str, Any], actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return explicit business context or derive an operator-facing fallback."""

        explicit = dict(screen.get("business_context") or {})
        if (
            explicit.get("objective")
            or explicit.get("decision_output")
            or explicit.get("checkpoints")
        ):
            explicit["objective"] = self._operator_text(explicit.get("objective", ""))
            explicit["decision_output"] = self._operator_text(explicit.get("decision_output", ""))
            explicit["checkpoints"] = [
                self._operator_text(item) for item in explicit.get("checkpoints") or []
            ]
            return explicit

        view_type = str(screen.get("view_type") or "")
        inferred_tiers = [self._runtime_action_tier(action) for action in actions]
        primary_count = sum(1 for tier in inferred_tiers if tier == "primary")
        support_count = sum(1 for tier in inferred_tiers if tier == "support")
        advanced_count = sum(1 for tier in inferred_tiers if tier == "advanced")
        operation_count = sum(1 for tier in inferred_tiers if tier == "operation")

        output_by_view = {
            "datagrid": "可筛选、可翻页、可打开明细的业务列表。",
            "detail": "当前对象或当前任务的结构化摘要。",
            "status": "当前状态、异常信号和后续检查方向。",
            "message": "可读的业务说明或交互结果。",
            "queue_workbench": "队列状态、待处理事项和下一步处理方向。",
        }
        checkpoints = []
        if primary_count:
            checkpoints.append("先按主流程任务读取本屏关键判断。")
        if support_count:
            checkpoints.append("发现矛盾或缺口时展开支撑检查。")
        if advanced_count:
            checkpoints.append("需要定位单条记录时再使用条件查询。")
        if operation_count:
            checkpoints.append("写入或 AI 交互只在证据明确后执行，并接受确认。")
        if not checkpoints:
            checkpoints.append("当前屏暂无已发布任务，等待 metadata 提升后进入主菜单。")

        return {
            "objective": str(screen.get("summary") or screen.get("label") or ""),
            "decision_output": output_by_view.get(view_type, "当前工作区的业务结果和下一步操作。"),
            "checkpoints": checkpoints,
        }

    def _runtime_action_tier(self, action: dict[str, Any]) -> str:
        tier = str(action.get("task_tier") or "").lower()
        if tier in {"primary", "support", "advanced", "operation"}:
            return tier
        risk = str(action.get("risk") or "read").lower()
        if risk in {"write", "ai", "admin"}:
            return "operation"
        key = str(action.get("key") or "")
        group = str(action.get("task_group") or "")
        if key.startswith("param.") or "条件查询" in group:
            return "advanced"
        return "primary"

    def _action_payload(
        self, action: dict[str, Any], *, include_technical: bool = False
    ) -> dict[str, Any]:
        payload = {
            "key": action["key"],
            "ui_key": self._action_ui_key(action),
            "label": self._operator_text(action["label"]),
            "intent": action["intent"],
            "screen_key": action["screen_key"],
            "view_type": action["view_type"],
            "risk": action["risk"],
            "confirmation_required": self._requires_confirmation(action),
            "fields": [
                self._field_payload(field, action=action) for field in action.get("fields") or []
            ],
            "description": self._operator_text(action.get("description", "")),
            "task_group": self._operator_text(action.get("task_group", "")),
            "task_tier": action.get("task_tier", ""),
            "sequence": int(action.get("sequence", 999)),
        }
        if include_technical:
            payload.update(
                {
                    "method": action["method"],
                    "endpoint": action["endpoint"],
                    "module_key": action["module_key"],
                    "source": action.get("source", "published"),
                    "raw_debug": bool(action.get("raw_debug", True)),
                    "view_model": dict(action.get("view_model") or {}),
                }
            )
        return payload

    def _action_ui_key(self, action: dict[str, Any]) -> str:
        digest = hashlib.sha1(str(action.get("key") or "").encode("utf-8")).hexdigest()[:10]
        return f"task-{digest}"

    def _int_from_path(
        self,
        action: dict[str, Any],
        envelope: dict[str, Any] | None,
        key: str,
        *,
        default: int,
    ) -> int:
        if not envelope:
            return default
        path = self._view_model_path(action, key)
        value = self._value_at_path(envelope, path) if path else None
        try:
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _int_from_params(
        self,
        params: dict[str, Any] | None,
        key: str,
        *,
        default: int,
    ) -> int:
        if not params:
            return default
        try:
            value = params.get(key)
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _field_payload(
        self, field: dict[str, Any], *, action: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = dict(field)
        key = str(payload.get("key") or "").strip()
        label = str(payload.get("label") or "").strip()
        canonical_label = key in FIELD_LABELS
        if canonical_label or self._is_technical_field_label(key=key, label=label):
            payload["label"] = self._humanize(key)
        resolved_default = (
            self._resolved_field_default(action, field) if action else payload.get("default")
        )
        if resolved_default not in (None, "") and payload.get("default") in (None, ""):
            payload["default"] = resolved_default
        placeholder = str(payload.get("placeholder") or "").strip()
        if payload.get("required") and (
            not placeholder
            or canonical_label
            or self._is_technical_placeholder(key=key, placeholder=placeholder)
        ):
            payload["placeholder"] = f"请输入{payload['label']}"
        return payload

    def _resolved_field_default(
        self,
        action: dict[str, Any] | None,
        field: dict[str, Any],
    ) -> Any:
        default = field.get("default")
        if default not in (None, ""):
            return default
        if not action or str(action.get("risk") or "") != "read":
            return default
        key = str(field.get("key") or "").strip().lower()
        input_type = str(field.get("input_type") or "").strip().lower()
        if input_type != "date":
            return default
        today = timezone.localdate()
        if key in {"start_date", "start"}:
            return (today - timedelta(days=30)).isoformat()
        if key in {"end_date", "end", "as_of_date", "as_of", "date"}:
            return today.isoformat()
        return default

    def _is_technical_field_label(self, *, key: str, label: str) -> bool:
        if not label:
            return True
        normalized_label = label.strip().lower().replace(" ", "_").replace("-", "_")
        normalized_key = key.strip().lower().replace("-", "_")
        return normalized_label in {
            normalized_key,
            "pk",
            "id",
            "str",
            "int",
            "uuid",
        }

    def _is_technical_placeholder(self, *, key: str, placeholder: str) -> bool:
        normalized = placeholder.strip().lower().replace(" ", "_").replace("-", "_")
        return normalized in {
            key.strip().lower().replace("-", "_"),
            f"input_{key.strip().lower().replace('-', '_')}",
            f"输入{key}",
        }

    def _empty_datagrid_message(self, action: dict[str, Any], total: int) -> str:
        if total > 0:
            return "当前页没有可显示记录。"
        return f"暂无{self._action_title(action)}数据。"

    def _empty_datagrid_guidance(self, action: dict[str, Any], total: int) -> list[str]:
        if total > 0:
            return [
                "当前页没有记录，但结果集仍有数据。",
                "使用 PgUp/PgDn 或调整页码后继续查看。",
            ]
        visible_fields = [
            self._field_payload(field)
            for field in action.get("fields") or []
            if field.get("input_type") != "hidden"
        ]
        guidance = [
            "先按 F5 刷新，确认不是临时数据延迟。",
        ]
        if visible_fields:
            labels = "、".join(
                str(field.get("label") or field.get("key") or "") for field in visible_fields[:4]
            )
            guidance.append(f"检查筛选条件：{labels}。")
            guidance.append(
                "如果当前表格已有对应记录，可选中一行后按 F9 进入任务区使用“从选中行填参”。"
            )
        else:
            guidance.append("如果这是初始化数据，先到相关配置或同步任务中补齐数据源。")
            guidance.append("也可以按 F9 定位任务区，搜索本屏可用的同步、检查或配置任务。")
        return guidance

    def _humanize(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        if normalized in FIELD_LABELS:
            return FIELD_LABELS[normalized]
        parts = [part for part in normalized.replace("-", "_").split(".") if part]
        labels = [self._humanize_part(part) for part in parts]
        return " / ".join(label for label in labels if label)

    def _humanize_part(self, value: str) -> str:
        if value in FIELD_LABELS:
            return FIELD_LABELS[value]
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value).replace("-", "_")
        tokens = [token for token in expanded.split("_") if token]
        if not tokens:
            return value
        translated = [
            FIELD_TOKEN_LABELS.get(
                token.lower(), token.upper() if token.lower() == "id" else token.title()
            )
            for token in tokens
        ]
        return "".join(translated)
