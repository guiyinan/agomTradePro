"""AgomTradePro MCP Server."""

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro_mcp.tools.account_tools import register_account_tools
from agomtradepro_mcp.tools.ai_provider_tools import register_ai_provider_tools
from agomtradepro_mcp.tools.alpha_tools import register_alpha_tools
from agomtradepro_mcp.tools.alpha_trigger_tools import register_alpha_trigger_tools
from agomtradepro_mcp.tools.asset_analysis_tools import register_asset_analysis_tools
from agomtradepro_mcp.tools.audit_tools import register_audit_tools
from agomtradepro_mcp.tools.backtest_tools import register_backtest_tools
from agomtradepro_mcp.tools.beta_gate_tools import register_beta_gate_tools
from agomtradepro_mcp.tools.dashboard_tools import register_dashboard_tools
from agomtradepro_mcp.tools.config_center_tools import register_config_center_tools
from agomtradepro_mcp.tools.decision_rhythm_tools import register_decision_rhythm_tools
from agomtradepro_mcp.tools.equity_tools import register_equity_tools
from agomtradepro_mcp.tools.events_tools import register_events_tools
from agomtradepro_mcp.tools.filter_tools import register_filter_tools
from agomtradepro_mcp.tools.fund_tools import register_fund_tools
from agomtradepro_mcp.tools.macro_tools import register_macro_tools
from agomtradepro_mcp.tools.market_data_tools import register_market_data_tools
from agomtradepro_mcp.tools.policy_tools import register_policy_tools
from agomtradepro_mcp.tools.prompt_tools import register_prompt_tools
from agomtradepro_mcp.tools.pulse_tools import register_pulse_tools
from agomtradepro_mcp.tools.realtime_tools import register_realtime_tools
from agomtradepro_mcp.tools.regime_tools import register_regime_tools
from agomtradepro_mcp.tools.rotation_tools import register_rotation_tools
from agomtradepro_mcp.tools.factor_tools import register_factor_tools
from agomtradepro_mcp.tools.hedge_tools import register_hedge_tools
from agomtradepro_mcp.tools.sector_tools import register_sector_tools
from agomtradepro_mcp.tools.sentiment_tools import register_sentiment_tools
from agomtradepro_mcp.tools.signal_tools import register_signal_tools
from agomtradepro_mcp.tools.simulated_trading_tools import register_simulated_trading_tools
from agomtradepro_mcp.tools.strategy_tools import register_strategy_tools
from agomtradepro_mcp.tools.task_monitor_tools import register_task_monitor_tools
from agomtradepro_mcp.tools.agent_task_tools import register_agent_task_tools
from agomtradepro_mcp.tools.agent_runtime_tools import register_agent_runtime_tools
from agomtradepro_mcp.tools.agent_proposal_tools import register_agent_proposal_tools
from agomtradepro_mcp.tools.decision_workflow_tools import register_decision_workflow_tools
from agomtradepro_mcp.rbac import (
    enforce_prompt_access,
    enforce_resource_access,
    wrap_tool_with_rbac,
    wrap_tool_with_rbac_and_audit,
)

# 创建 MCP 服务器实例
server = FastMCP("agomtradepro")


def register_all_tools() -> None:
    """注册所有 MCP 工具"""
    # Core modules
    register_regime_tools(server)
    register_signal_tools(server)
    register_macro_tools(server)
    register_policy_tools(server)
    register_backtest_tools(server)
    register_account_tools(server)

    # Extended modules
    register_simulated_trading_tools(server)
    register_equity_tools(server)
    register_fund_tools(server)
    register_sector_tools(server)
    register_strategy_tools(server)
    register_realtime_tools(server)

    # New modules: Factor + Rotation + Hedge
    register_factor_tools(server)
    register_rotation_tools(server)
    register_hedge_tools(server)

    # New module: Alpha 抽象层
    register_alpha_tools(server)

    # Governance + operation modules
    register_ai_provider_tools(server)
    register_prompt_tools(server)
    register_audit_tools(server)
    register_events_tools(server)
    register_decision_rhythm_tools(server)
    register_beta_gate_tools(server)
    register_alpha_trigger_tools(server)
    register_dashboard_tools(server)
    register_config_center_tools(server)
    register_asset_analysis_tools(server)
    register_sentiment_tools(server)
    register_task_monitor_tools(server)
    register_filter_tools(server)

    # Decision Workflow module
    register_decision_workflow_tools(server)

    # Market Data 统一数据源模块
    register_market_data_tools(server)

    # Agent Runtime task tools (M2)
    register_agent_task_tools(server)

    # Agent Runtime execution tools (unified AI execution)
    register_agent_runtime_tools(server)

    # Agent Proposal tools (M3)
    register_agent_proposal_tools(server)

    # Pulse + Navigator tools
    register_pulse_tools(server)


def apply_tool_rbac_guards() -> None:
    """Apply RBAC guards and audit logging to all registered tools."""
    manager = getattr(server, "_tool_manager", None)
    if manager is None:
        return
    tools = getattr(manager, "_tools", {})
    for name, tool_obj in tools.items():
        original = getattr(tool_obj, "fn", None)
        if original is None:
            continue
        # 使用带审计的 RBAC 包装器
        setattr(tool_obj, "fn", wrap_tool_with_rbac_and_audit(name, original))


@server.resource(
    "agomtradepro://regime/current",
    name="Current Regime",
    description="当前宏观象限状态",
    mime_type="text/plain",
)
def resource_regime_current() -> str:
    """读取当前宏观环境资源。"""
    enforce_resource_access("agomtradepro://regime/current")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    regime = client.regime.get_current()
    growth_line = regime.growth_indicator
    if regime.growth_value is not None:
        growth_line = f"{growth_line} ({regime.growth_value})"

    inflation_line = regime.inflation_indicator
    if regime.inflation_value is not None:
        inflation_line = f"{inflation_line} ({regime.inflation_value})"

    return f"""当前宏观环境: {regime.dominant_regime}
增长水平: {regime.growth_level}
通胀水平: {regime.inflation_level}
观测日期: {regime.observed_at}
增长指标: {growth_line}
通胀指标: {inflation_line}"""

@server.resource(
    "agomtradepro://policy/status",
    name="Policy Status",
    description="当前政策档位状态",
    mime_type="text/plain",
)
def resource_policy_status() -> str:
    """读取当前政策状态资源。"""
    enforce_resource_access("agomtradepro://policy/status")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    status = client.policy.get_status()
    recent_events_desc = "\n".join(
        f"  - {e.event_date}: {e.description}" for e in status.recent_events
    )
    return f"""当前政策档位: {status.current_gear}
观测日期: {status.observed_at}

最近事件:
{recent_events_desc or "  无"}"""

@server.prompt("analyze_macro_environment")
def prompt_analyze_macro_environment() -> str:
    """分析当前宏观环境并给出投资建议。"""
    enforce_prompt_access("analyze_macro_environment")
    return """请分析 AgomTradePro 系统的当前宏观环境：

1. 使用 get_current_regime 工具获取当前宏观象限
2. 根据象限判断适合投资的资产类别：
   - Recovery（复苏）：股票、商品、房地产
   - Overheat（过热）：债券、现金
   - Stagflation（滞胀）：商品、现金、黄金
   - Repression（衰退）：债券、股票
3. 使用 get_policy_status 检查当前政策档位
4. 结合宏观象限和政策档位，给出综合投资建议

请以结构化的方式呈现分析结果。"""

@server.prompt("check_signal_eligibility")
def prompt_check_signal_eligibility(asset_code: str, logic_desc: str) -> str:
    """检查投资信号是否符合准入条件。"""
    enforce_prompt_access("check_signal_eligibility")
    return f"""请检查以下投资信号是否符合准入条件：

资产代码：{asset_code}
投资逻辑：{logic_desc}

分析步骤：
1. 使用 get_current_regime 获取当前宏观象限
2. 使用 get_policy_status 获取当前政策档位
3. 使用 check_signal_eligibility 工具检查准入条件
4. 根据检查结果给出明确的准入/不准入建议

请详细说明准入或不准入的原因。"""

# ==========================================================================
# WP-M2-05: Context Resources
# ==========================================================================

def _format_context_snapshot(domain: str) -> str:
    """Fetch context snapshot via SDK and format as readable text."""
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    ctx = client.agent_context.get_context_snapshot(domain)

    regime = ctx.get("regime_summary", {})
    policy = ctx.get("policy_summary", {})
    portfolio = ctx.get("portfolio_summary", {})
    signals = ctx.get("active_signals_summary", {})
    decisions = ctx.get("open_decisions_summary", {})
    risk = ctx.get("risk_alerts_summary", {})
    tasks = ctx.get("task_health_summary", {})
    freshness = ctx.get("data_freshness_summary", {})

    lines = [
        f"Domain: {ctx.get('domain', domain)}",
        f"Generated: {ctx.get('generated_at', 'unknown')}",
        "",
        "--- Regime ---",
        f"  Status: {regime.get('status', 'unknown')}",
    ]
    if regime.get("status") == "ok":
        lines.append(f"  Dominant: {regime.get('dominant_regime')}")
        lines.append(f"  Growth: {regime.get('growth_level')}")
        lines.append(f"  Inflation: {regime.get('inflation_level')}")

    lines += [
        "",
        "--- Policy ---",
        f"  Status: {policy.get('status', 'unknown')}",
    ]
    if policy.get("status") == "ok":
        lines.append(f"  Gear: {policy.get('current_gear')}")

    lines += [
        "",
        "--- Portfolio ---",
        f"  Status: {portfolio.get('status', 'unknown')}",
    ]
    if portfolio.get("status") == "ok":
        lines.append(f"  Positions: {portfolio.get('position_count')}")

    lines += [
        "",
        "--- Active Signals ---",
        f"  Status: {signals.get('status', 'unknown')}",
        f"  Count: {signals.get('active_count', 0)}",
        "",
        "--- Tasks ---",
        f"  Active: {tasks.get('active_tasks', 0)}",
        f"  Needs Human: {tasks.get('needs_human', 0)}",
        f"  Failed: {tasks.get('failed_tasks', 0)}",
    ]

    return "\n".join(lines)


@server.resource(
    "agomtradepro://context/research/current",
    name="Research Context",
    description="当前研究域上下文快照",
    mime_type="text/plain",
)
def resource_context_research() -> str:
    """Research domain context snapshot."""
    enforce_resource_access("agomtradepro://context/research/current")
    return _format_context_snapshot("research")


@server.resource(
    "agomtradepro://context/monitoring/current",
    name="Monitoring Context",
    description="当前监控域上下文快照",
    mime_type="text/plain",
)
def resource_context_monitoring() -> str:
    """Monitoring domain context snapshot."""
    enforce_resource_access("agomtradepro://context/monitoring/current")
    return _format_context_snapshot("monitoring")


@server.resource(
    "agomtradepro://context/decision/current",
    name="Decision Context",
    description="当前决策域上下文快照",
    mime_type="text/plain",
)
def resource_context_decision() -> str:
    """Decision domain context snapshot."""
    enforce_resource_access("agomtradepro://context/decision/current")
    return _format_context_snapshot("decision")


@server.resource(
    "agomtradepro://context/execution/current",
    name="Execution Context",
    description="当前执行域上下文快照",
    mime_type="text/plain",
)
def resource_context_execution() -> str:
    """Execution domain context snapshot."""
    enforce_resource_access("agomtradepro://context/execution/current")
    return _format_context_snapshot("execution")


@server.resource(
    "agomtradepro://context/ops/current",
    name="Ops Context",
    description="当前运维域上下文快照",
    mime_type="text/plain",
)
def resource_context_ops() -> str:
    """Ops domain context snapshot."""
    enforce_resource_access("agomtradepro://context/ops/current")
    return _format_context_snapshot("ops")


# ==========================================================================
# WP-M2-06: Workflow Guide Prompts
# ==========================================================================

@server.prompt("run_research_workflow")
def prompt_run_research_workflow(focus: str = "macro_regime") -> str:
    """Run a research workflow: gather context, analyze, and produce findings."""
    enforce_prompt_access("run_research_workflow")
    return f"""Execute a research workflow with focus: {focus}

Steps:
1. Read resource agomtradepro://context/research/current to understand the current environment
2. Use start_research_task to create a tracked research task
3. Depending on focus:
   - macro_regime: Use get_current_regime + get_regime_history to analyze trends
   - factor_analysis: Use get_factor_top_stocks to identify opportunities
   - sector_scan: Use get_hot_sectors + analyze_sector to evaluate sectors
4. Summarize findings and any recommended actions
5. If actions are warranted, note them for a follow-up decision workflow

Important: Always check regime and policy status before making recommendations."""


@server.prompt("run_monitoring_workflow")
def prompt_run_monitoring_workflow(check_type: str = "full") -> str:
    """Run a monitoring workflow: check alerts, freshness, and anomalies."""
    enforce_prompt_access("run_monitoring_workflow")
    return f"""Execute a monitoring workflow (type: {check_type})

Steps:
1. Read resource agomtradepro://context/monitoring/current for current monitoring state
2. Use start_monitoring_task to create a tracked monitoring task
3. Check data freshness across all sources
4. Review any triggered price alerts (list_price_alerts)
5. Check sentiment gate state (get_sentiment_gate_state)
6. If check_type is 'full', also verify:
   - Market data provider health (market_data_provider_health)
   - Alpha provider status (get_alpha_provider_status)
7. Report any anomalies or stale data sources

Escalate to human if critical alerts are found."""


@server.prompt("run_decision_workflow")
def prompt_run_decision_workflow(decision_type: str = "signal_review") -> str:
    """Run a decision workflow: evaluate signals, check quotas, propose actions."""
    enforce_prompt_access("run_decision_workflow")
    return f"""Execute a decision workflow (type: {decision_type})

Steps:
1. Read resource agomtradepro://context/decision/current for decision context
2. Use start_decision_task to create a tracked decision task
3. Check decision quotas to ensure capacity exists
4. Depending on decision_type:
   - signal_review: List active signals, check eligibility, approve/reject
   - rebalance: Review portfolio vs target allocation, propose rebalance
   - position_sizing: Evaluate position rules, check risk limits
5. For any proposed action, verify:
   - Current regime allows the action
   - Policy gear does not block it
   - Beta gate passes
6. Present proposal for human approval if risk_level >= medium

CRITICAL: Never execute trades without explicit human approval."""


@server.prompt("run_execution_workflow")
def prompt_run_execution_workflow(action: str = "review_pending") -> str:
    """Run an execution workflow: execute approved proposals or review positions."""
    enforce_prompt_access("run_execution_workflow")
    return f"""Execute an execution workflow (action: {action})

Steps:
1. Read resource agomtradepro://context/execution/current for execution context
2. Use start_execution_task to create a tracked execution task
3. Depending on action:
   - review_pending: List tasks needing attention, review pending proposals
   - execute_approved: Find approved proposals, execute via simulated trading
   - position_check: Review open positions, check stop-loss/take-profit levels
4. For any trade execution:
   - Verify the proposal is still approved
   - Check trading cost estimates
   - Execute via simulated trading (never real trades)
5. Record execution results

CRITICAL: All executions go through simulated trading only."""


@server.prompt("run_ops_workflow")
def prompt_run_ops_workflow(scope: str = "health_check") -> str:
    """Run an ops workflow: system health, data sync, or audit review."""
    enforce_prompt_access("run_ops_workflow")
    return f"""Execute an ops workflow (scope: {scope})

Steps:
1. Read resource agomtradepro://context/ops/current for ops context
2. Use start_ops_task to create a tracked ops task
3. Depending on scope:
   - health_check: Check all system components
     * Agent task health (active, failed, needs_human counts)
     * Event bus status
     * AI provider availability
     * Data freshness across all sources
   - data_sync: Trigger data synchronization
     * Sync macro indicators
     * Refresh valuation data
     * Trigger RSS fetch for news
   - audit_review: Review recent audit records
     * Check audit summary
     * Run validation checks
     * Report any compliance issues
4. Summarize system status and any issues found

Escalate to human if system components are unhealthy."""


# 注册所有工具
register_all_tools()
apply_tool_rbac_guards()


def _get_default_portfolio_id(client: Any) -> int | None:
    """Get default portfolio id from env or first available portfolio."""
    configured = os.getenv("AGOMTRADEPRO_DEFAULT_PORTFOLIO_ID")
    if configured:
        try:
            return int(configured)
        except ValueError:
            pass

    portfolios = client.account.get_portfolios(limit=1)
    if portfolios:
        return portfolios[0].id
    return None


@server.resource(
    "agomtradepro://account/summary",
    name="Account Summary",
    description="默认投资组合摘要",
    mime_type="text/plain",
)
def resource_account_summary() -> str:
    """默认组合摘要（用于 Agent 自动读取上下文）。"""
    enforce_resource_access("agomtradepro://account/summary")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    portfolio_id = _get_default_portfolio_id(client)
    if portfolio_id is None:
        return "未找到可用投资组合。"

    portfolio = client.get(f"api/account/portfolios/{portfolio_id}/")
    stats = client.get(f"api/account/portfolios/{portfolio_id}/statistics/")

    return f"""默认组合ID: {portfolio_id}
组合名称: {portfolio.get('name')}
总市值: {portfolio.get('total_value')}
持仓数: {stats.get('position_count')}
未实现盈亏: {stats.get('total_pnl')}
未实现盈亏(%): {stats.get('total_pnl_pct')}
净资金流: {stats.get('net_capital_flow')}"""


@server.resource(
    "agomtradepro://account/positions",
    name="Account Positions",
    description="默认投资组合持仓快照",
    mime_type="text/plain",
)
def resource_account_positions() -> str:
    """默认组合持仓快照。"""
    enforce_resource_access("agomtradepro://account/positions")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    portfolio_id = _get_default_portfolio_id(client)
    if portfolio_id is None:
        return "未找到可用投资组合。"

    payload = client.get("api/account/positions/", params={"portfolio_id": portfolio_id, "limit": 20})
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not rows:
        return f"组合 {portfolio_id} 当前无持仓。"

    lines = []
    for row in rows[:20]:
        if row.get("is_closed"):
            continue
        lines.append(
            f"{row.get('asset_code')} | 持仓: {row.get('shares')} | 成本: {row.get('avg_cost')} | "
            f"现价: {row.get('current_price')} | 盈亏: {row.get('unrealized_pnl')}"
        )

    if not lines:
        return f"组合 {portfolio_id} 当前无未平仓持仓。"

    return f"默认组合ID: {portfolio_id}\n" + "\n".join(lines)


@server.resource(
    "agomtradepro://account/recent-transactions",
    name="Recent Transactions",
    description="默认投资组合最近交易",
    mime_type="text/plain",
)
def resource_account_recent_transactions() -> str:
    """默认组合最近交易。"""
    enforce_resource_access("agomtradepro://account/recent-transactions")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    portfolio_id = _get_default_portfolio_id(client)
    if portfolio_id is None:
        return "未找到可用投资组合。"

    payload = client.get("api/account/transactions/", params={"limit": 20})
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    rows = [r for r in rows if r.get("portfolio") == portfolio_id]

    if not rows:
        return f"组合 {portfolio_id} 暂无交易记录。"

    lines = [
        f"{r.get('traded_at')} | {r.get('action')} {r.get('asset_code')} {r.get('shares')} @ {r.get('price')}"
        for r in rows[:20]
    ]
    return f"默认组合ID: {portfolio_id}\n" + "\n".join(lines)


async def list_resources() -> list[dict[str, Any]]:
    """列出所有可用资源（兼容旧测试脚本）。"""
    resources = await server.list_resources()
    return [
        {
            "uri": str(r.uri),
            "name": r.name,
            "description": r.description,
            "mime_type": getattr(r, "mime_type", getattr(r, "mimeType", None)),
        }
        for r in resources
    ]


async def read_resource(uri: str) -> str:
    """读取资源内容（兼容旧测试脚本）。"""
    contents = await server.read_resource(uri)
    first = next(iter(contents), None)
    if first is None:
        return ""
    return getattr(first, "text", str(first))


async def list_prompts() -> list[dict[str, Any]]:
    """列出所有 prompt（兼容旧测试脚本）。"""
    prompts = await server.list_prompts()
    return [
        {
            "name": p.name,
            "description": p.description,
            "arguments": [
                {
                    "name": arg.name,
                    "description": arg.description,
                    "required": arg.required,
                }
                for arg in (p.arguments or [])
            ],
        }
        for p in prompts
    ]


async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> str:
    """读取 prompt 内容（兼容旧测试脚本）。"""
    result = await server.get_prompt(name, arguments)
    if getattr(result, "messages", None):
        first_msg = result.messages[0]
        if first_msg.content and getattr(first_msg.content, "text", None):
            return first_msg.content.text
    return str(result)


def main() -> None:
    """MCP CLI 入口（同步包装，兼容 console scripts）"""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
