"""AgomTradePro MCP Server."""

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro_mcp.agent_contracts import (
    AGENT_CONTRACT_STORE,
    AgentContractConfigurationError,
)
from agomtradepro_mcp.rbac import (
    enforce_prompt_access,
    enforce_resource_access,
    wrap_tool_with_rbac_and_audit,
)
from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.internal_handlers.alpha import (
    import_score_cache as _internal_handler_alpha_import_score_cache,
)
from agomtradepro_mcp.registry.internal_handlers.audit import (
    generate_attribution_report as _internal_handler_audit_generate_attribution_report,
)
from agomtradepro_mcp.registry.internal_handlers.audit import (
    start_threshold_validation as _internal_handler_audit_start_threshold_validation,
)
from agomtradepro_mcp.registry.internal_handlers.audit import (
    update_threshold_levels as _internal_handler_audit_update_threshold_levels,
)
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.read_handlers.config_center import (
    get_config_center_snapshot as _fallback_get_config_center_snapshot,
)
from agomtradepro_mcp.registry.runtime_handlers.common import (
    configure_legacy_tool_caller,
)
from agomtradepro_mcp.registry.runtime_handlers.registry import (
    OWNER_GOVERNED_HANDLERS,
    OWNER_LEGACY_TOOL_FALLBACKS,
)
from agomtradepro_mcp.tools.account_tools import register_account_tools
from agomtradepro_mcp.tools.agent_proposal_tools import register_agent_proposal_tools
from agomtradepro_mcp.tools.agent_runtime_tools import register_agent_runtime_tools
from agomtradepro_mcp.tools.agent_task_tools import register_agent_task_tools
from agomtradepro_mcp.tools.ai_provider_tools import register_ai_provider_tools
from agomtradepro_mcp.tools.alpha_tools import register_alpha_tools
from agomtradepro_mcp.tools.alpha_trigger_tools import register_alpha_trigger_tools
from agomtradepro_mcp.tools.asset_analysis_tools import register_asset_analysis_tools
from agomtradepro_mcp.tools.audit_tools import register_audit_tools
from agomtradepro_mcp.tools.backtest_tools import register_backtest_tools
from agomtradepro_mcp.tools.beta_gate_tools import register_beta_gate_tools
from agomtradepro_mcp.tools.config_center_tools import register_config_center_tools
from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES, register_core_tools
from agomtradepro_mcp.tools.dashboard_tools import register_dashboard_tools
from agomtradepro_mcp.tools.data_center_tools import register_data_center_tools
from agomtradepro_mcp.tools.decision_rhythm_tools import register_decision_rhythm_tools
from agomtradepro_mcp.tools.decision_workflow_tools import register_decision_workflow_tools
from agomtradepro_mcp.tools.equity_tools import register_equity_tools
from agomtradepro_mcp.tools.events_tools import register_events_tools
from agomtradepro_mcp.tools.factor_tools import register_factor_tools
from agomtradepro_mcp.tools.filter_tools import register_filter_tools
from agomtradepro_mcp.tools.fund_tools import register_fund_tools
from agomtradepro_mcp.tools.hedge_tools import register_hedge_tools
from agomtradepro_mcp.tools.policy_tools import register_policy_tools
from agomtradepro_mcp.tools.prompt_tools import register_prompt_tools
from agomtradepro_mcp.tools.pulse_tools import register_pulse_tools
from agomtradepro_mcp.tools.realtime_tools import register_realtime_tools
from agomtradepro_mcp.tools.regime_tools import register_regime_tools
from agomtradepro_mcp.tools.risk_center_tools import register_risk_center_tools
from agomtradepro_mcp.tools.rotation_tools import register_rotation_tools
from agomtradepro_mcp.tools.sector_tools import register_sector_tools
from agomtradepro_mcp.tools.sentiment_tools import register_sentiment_tools
from agomtradepro_mcp.tools.signal_tools import register_signal_tools
from agomtradepro_mcp.tools.simulated_trading_tools import register_simulated_trading_tools
from agomtradepro_mcp.tools.strategy_tools import register_strategy_tools
from agomtradepro_mcp.tools.task_monitor_tools import register_task_monitor_tools

logger = logging.getLogger(__name__)


def _build_welcome_message() -> str:
    """Build the server welcome/instructions text exposed during MCP initialize."""
    base_url = os.getenv("AGOMTRADEPRO_BASE_URL") or os.getenv(
        "AGOMTRADEPRO_API_BASE_URL",
        "http://127.0.0.1:8000",
    )
    role = os.getenv("AGOMTRADEPRO_MCP_ROLE", "viewer")

    try:
        contract = AGENT_CONTRACT_STORE.get_contract()
        return AGENT_CONTRACT_STORE.render_prompt(
            "startup_welcome",
            {
                "role": role,
                "base_url": base_url,
                "contract_version": contract["version"],
            },
        )
    except AgentContractConfigurationError:
        logger.exception("Failed to load the configured MCP startup contract")
        return (
            "[AgomTradePro MCP Safe Startup]\n"
            "Contract configuration is unavailable. Use capability Schema only, "
            "do not bypass confirmation, and allow simulated execution only."
        )


# 创建 MCP 服务器实例
server = FastMCP(
    "agomtradepro",
    instructions=_build_welcome_message(),
)

LEGACY_TOOL_REGISTRARS = (
    register_regime_tools,
    register_signal_tools,
    register_policy_tools,
    register_backtest_tools,
    register_account_tools,
    register_simulated_trading_tools,
    register_equity_tools,
    register_fund_tools,
    register_sector_tools,
    register_strategy_tools,
    register_realtime_tools,
    register_factor_tools,
    register_rotation_tools,
    register_hedge_tools,
    register_alpha_tools,
    register_ai_provider_tools,
    register_prompt_tools,
    register_audit_tools,
    register_events_tools,
    register_decision_rhythm_tools,
    register_beta_gate_tools,
    register_alpha_trigger_tools,
    register_dashboard_tools,
    register_config_center_tools,
    register_risk_center_tools,
    register_asset_analysis_tools,
    register_sentiment_tools,
    register_task_monitor_tools,
    register_filter_tools,
    register_decision_workflow_tools,
    register_data_center_tools,
    register_agent_task_tools,
    register_agent_runtime_tools,
    register_agent_proposal_tools,
    register_pulse_tools,
)


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


INTERNAL_LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    **OWNER_LEGACY_TOOL_FALLBACKS,
    "get_config_center_snapshot": _fallback_get_config_center_snapshot,
}

INTERNAL_GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    **OWNER_GOVERNED_HANDLERS,
    "audit_start_threshold_validation": _internal_handler_audit_start_threshold_validation,
    "audit_update_threshold_levels": _internal_handler_audit_update_threshold_levels,
    "audit_generate_attribution_report": _internal_handler_audit_generate_attribution_report,
    "alpha_import_score_cache": _internal_handler_alpha_import_score_cache,
}


def _call_registered_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    if tool_name in CORE_TOOL_NAMES:
        raise RuntimeError(f"Refusing to recursively dispatch to core tool: {tool_name}")

    manager = getattr(server, "_tool_manager", None)
    if manager is None:
        raise RuntimeError("MCP tool manager is not initialized")

    tools = getattr(manager, "_tools", {})
    tool_obj = tools.get(tool_name)
    if tool_obj is None:
        fallback = INTERNAL_LEGACY_TOOL_FALLBACKS.get(tool_name)
        if fallback is not None:
            return fallback(**arguments)
        raise KeyError(f"Legacy tool is not registered: {tool_name}")

    fn = getattr(tool_obj, "fn", None)
    if fn is None:
        raise RuntimeError(f"Registered tool has no callable fn: {tool_name}")
    return fn(**arguments)


def _call_internal_handler(handler_name: str, arguments: dict[str, Any]) -> Any:
    handler = INTERNAL_GOVERNED_HANDLERS.get(handler_name)
    if handler is None:
        raise KeyError(f"Internal governed handler is not registered: {handler_name}")
    return handler(**arguments)


configure_legacy_tool_caller(_call_registered_tool)


CORE_REGISTRY_LOADER = CapabilityRegistryLoader()
CORE_CAPABILITY_REGISTRY = CORE_REGISTRY_LOADER.build_registry()
CORE_DISPATCHER = CapabilityDispatcher(
    registry=CORE_CAPABILITY_REGISTRY,
    legacy_tool_caller=_call_registered_tool,
    internal_handler_caller=_call_internal_handler,
)
CORE_WORKFLOW_RUNS: dict[str, dict[str, Any]] = {}


def register_all_tools() -> None:
    """注册所有 MCP 工具"""
    global CORE_WORKFLOW_RUNS

    if _env_flag_enabled("AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS", default=True):
        CORE_WORKFLOW_RUNS = register_core_tools(
            server,
            dispatcher=CORE_DISPATCHER,
            welcome_message_factory=_build_welcome_message,
        )

    if _env_flag_enabled("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", default=False):
        for registrar in LEGACY_TOOL_REGISTRARS:
            registrar(server)


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
        tool_obj.fn = wrap_tool_with_rbac_and_audit(name, original)


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


@server.resource(
    "agomtradepro://welcome",
    name="Welcome Guide",
    description="AgomTradePro MCP 欢迎信息与首次连接指引",
    mime_type="text/plain",
)
def resource_welcome() -> str:
    """Read the MCP welcome guide."""
    enforce_resource_access("agomtradepro://welcome")
    return _build_welcome_message()


@server.resource(
    "agomtradepro://agent/contract",
    name="Agent Operating Contract",
    description="版本化的 Agent 运行契约、路由规则和结构化决策摘要契约",
    mime_type="application/json",
)
def resource_agent_contract() -> str:
    """Return the active versioned Agent operating contract."""
    enforce_resource_access("agomtradepro://agent/contract")
    return json.dumps(AGENT_CONTRACT_STORE.get_contract(), ensure_ascii=False, indent=2)


@server.resource(
    "agomtradepro://agent/playbooks",
    name="Agent Workflow Playbooks",
    description="版本化的 AgomTradePro 工作流 Playbook 目录",
    mime_type="application/json",
)
def resource_agent_playbooks() -> str:
    """Return the compact catalog of configured workflow playbooks."""
    enforce_resource_access("agomtradepro://agent/playbooks")
    return json.dumps(AGENT_CONTRACT_STORE.list_playbooks(), ensure_ascii=False, indent=2)


@server.prompt("agom_agent_contract")
def prompt_agent_contract(task_type: str = "general") -> str:
    """Load the active Agent contract and structured decision-summary rules."""
    enforce_prompt_access("agom_agent_contract")
    return AGENT_CONTRACT_STORE.render_agent_contract_prompt(task_type)


@server.prompt("analyze_macro_environment")
def prompt_analyze_macro_environment() -> str:
    """分析当前宏观环境并给出投资建议。"""
    enforce_prompt_access("analyze_macro_environment")
    return AGENT_CONTRACT_STORE.render_prompt("analyze_macro_environment")


@server.prompt("check_signal_eligibility")
def prompt_check_signal_eligibility(asset_code: str, logic_desc: str) -> str:
    """检查投资信号是否符合准入条件。"""
    enforce_prompt_access("check_signal_eligibility")
    return AGENT_CONTRACT_STORE.render_prompt(
        "check_signal_eligibility",
        {"asset_code": asset_code, "logic_desc": logic_desc},
    )


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
    ctx.get("open_decisions_summary", {})
    ctx.get("risk_alerts_summary", {})
    tasks = ctx.get("task_health_summary", {})
    ctx.get("data_freshness_summary", {})

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
    return AGENT_CONTRACT_STORE.render_prompt("run_research_workflow", {"focus": focus})


@server.prompt("run_monitoring_workflow")
def prompt_run_monitoring_workflow(check_type: str = "full") -> str:
    """Run a monitoring workflow: check alerts, freshness, and anomalies."""
    enforce_prompt_access("run_monitoring_workflow")
    return AGENT_CONTRACT_STORE.render_prompt(
        "run_monitoring_workflow",
        {"check_type": check_type},
    )


@server.prompt("run_decision_workflow")
def prompt_run_decision_workflow(decision_type: str = "signal_review") -> str:
    """Run a decision workflow: evaluate signals, check quotas, propose actions."""
    enforce_prompt_access("run_decision_workflow")
    return AGENT_CONTRACT_STORE.render_prompt(
        "run_decision_workflow",
        {"decision_type": decision_type},
    )


@server.prompt("run_execution_workflow")
def prompt_run_execution_workflow(action: str = "review_pending") -> str:
    """Run an execution workflow: execute approved proposals or review positions."""
    enforce_prompt_access("run_execution_workflow")
    return AGENT_CONTRACT_STORE.render_prompt("run_execution_workflow", {"action": action})


@server.prompt("run_ops_workflow")
def prompt_run_ops_workflow(scope: str = "health_check") -> str:
    """Run an ops workflow: system health, data sync, or audit review."""
    enforce_prompt_access("run_ops_workflow")
    return AGENT_CONTRACT_STORE.render_prompt("run_ops_workflow", {"scope": scope})


# 注册所有工具
register_all_tools()
apply_tool_rbac_guards()


def _get_default_account_id(client: Any) -> int | None:
    """Get default account id from env or first available unified account."""
    configured = os.getenv("AGOMTRADEPRO_DEFAULT_ACCOUNT_ID")
    if configured:
        try:
            return int(configured)
        except ValueError:
            pass

    accounts = client.account.list_accounts(limit=1)
    if accounts:
        account = accounts[0]
        account_id = account.get("account_id") or account.get("id")
        if account_id is not None:
            return int(account_id)
    return None


@server.resource(
    "agomtradepro://account/summary",
    name="Account Summary",
    description="默认账户摘要",
    mime_type="text/plain",
)
def resource_account_summary() -> str:
    """默认账户摘要（用于 Agent 自动读取上下文）。"""
    enforce_resource_access("agomtradepro://account/summary")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    account_id = _get_default_account_id(client)
    if account_id is None:
        return "未找到可用账户。"

    account = client.account.get_account(account_id)
    positions = client.account.get_account_positions(account_id)
    performance = client.account.get_account_performance(account_id)
    performance_summary = (
        performance.get("performance", {}) if isinstance(performance, dict) else {}
    )

    return f"""默认账户ID: {account_id}
账户名称: {account.get("account_name")}
账户类型: {account.get("account_type")}
总资产: {account.get("total_value")}
可用现金: {account.get("current_cash")}
持仓数: {len(positions)}
总交易数: {performance.get("total_trades") if isinstance(performance, dict) else None}
总收益率: {performance_summary.get("total_return")}
最大回撤: {performance_summary.get("max_drawdown")}"""


@server.resource(
    "agomtradepro://account/positions",
    name="Account Positions",
    description="默认账户持仓快照",
    mime_type="text/plain",
)
def resource_account_positions() -> str:
    """默认账户持仓快照。"""
    enforce_resource_access("agomtradepro://account/positions")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    account_id = _get_default_account_id(client)
    if account_id is None:
        return "未找到可用账户。"

    rows = client.account.get_account_positions(account_id)
    if not rows:
        return f"账户 {account_id} 当前无持仓。"

    lines = []
    for row in rows[:20]:
        lines.append(
            f"{row.get('asset_code')} | 持仓: {row.get('quantity')} | 成本: {row.get('avg_cost')} | "
            f"现价: {row.get('current_price')} | 盈亏: {row.get('unrealized_pnl')}"
        )

    if not lines:
        return f"账户 {account_id} 当前无持仓。"

    return f"默认账户ID: {account_id}\n" + "\n".join(lines)


@server.resource(
    "agomtradepro://account/recent-transactions",
    name="Recent Transactions",
    description="默认账户最近交易",
    mime_type="text/plain",
)
def resource_account_recent_transactions() -> str:
    """默认账户最近交易。"""
    enforce_resource_access("agomtradepro://account/recent-transactions")
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    account_id = _get_default_account_id(client)
    if account_id is None:
        return "未找到可用账户。"

    payload = client.get(f"api/account/accounts/{account_id}/trades/")
    rows = payload.get("trades", payload) if isinstance(payload, dict) else payload

    if not rows:
        return f"账户 {account_id} 暂无交易记录。"

    lines = [
        f"{r.get('execution_time')} | {r.get('action')} {r.get('asset_code')} {r.get('quantity')} @ {r.get('price')}"
        for r in rows[:20]
    ]
    return f"默认账户ID: {account_id}\n" + "\n".join(lines)


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
    text = getattr(first, "text", None)
    if text is not None:
        return str(text)
    content = getattr(first, "content", None)
    if content is not None:
        return str(content)
    return str(first)


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
