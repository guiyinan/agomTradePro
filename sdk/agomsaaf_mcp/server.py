"""AgomSAAF MCP Server."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf_mcp.tools.account_tools import register_account_tools
from agomsaaf_mcp.tools.alpha_tools import register_alpha_tools
from agomsaaf_mcp.tools.backtest_tools import register_backtest_tools
from agomsaaf_mcp.tools.equity_tools import register_equity_tools
from agomsaaf_mcp.tools.fund_tools import register_fund_tools
from agomsaaf_mcp.tools.macro_tools import register_macro_tools
from agomsaaf_mcp.tools.policy_tools import register_policy_tools
from agomsaaf_mcp.tools.realtime_tools import register_realtime_tools
from agomsaaf_mcp.tools.regime_tools import register_regime_tools
from agomsaaf_mcp.tools.rotation_tools import register_rotation_tools
from agomsaaf_mcp.tools.factor_tools import register_factor_tools
from agomsaaf_mcp.tools.hedge_tools import register_hedge_tools
from agomsaaf_mcp.tools.sector_tools import register_sector_tools
from agomsaaf_mcp.tools.signal_tools import register_signal_tools
from agomsaaf_mcp.tools.simulated_trading_tools import register_simulated_trading_tools
from agomsaaf_mcp.tools.strategy_tools import register_strategy_tools

# 创建 MCP 服务器实例
server = FastMCP("agomsaaf")


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


@server.resource(
    "agomsaaf://regime/current",
    name="Current Regime",
    description="当前宏观象限状态",
    mime_type="text/plain",
)
def resource_regime_current() -> str:
    """读取当前宏观环境资源。"""
    from agomsaaf import AgomSAAFClient

    client = AgomSAAFClient()
    regime = client.regime.get_current()
    return f"""当前宏观环境: {regime.dominant_regime}
增长水平: {regime.growth_level}
通胀水平: {regime.inflation_level}
观测日期: {regime.observed_at}
增长指标: {regime.growth_indicator} ({regime.growth_value})
通胀指标: {regime.inflation_indicator} ({regime.inflation_value})"""

@server.resource(
    "agomsaaf://policy/status",
    name="Policy Status",
    description="当前政策档位状态",
    mime_type="text/plain",
)
def resource_policy_status() -> str:
    """读取当前政策状态资源。"""
    from agomsaaf import AgomSAAFClient

    client = AgomSAAFClient()
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
    return """请分析 AgomSAAF 系统的当前宏观环境：

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
    return f"""请检查以下投资信号是否符合准入条件：

资产代码：{asset_code}
投资逻辑：{logic_desc}

分析步骤：
1. 使用 get_current_regime 获取当前宏观象限
2. 使用 get_policy_status 获取当前政策档位
3. 使用 check_signal_eligibility 工具检查准入条件
4. 根据检查结果给出明确的准入/不准入建议

请详细说明准入或不准入的原因。"""

# 注册所有工具
register_all_tools()


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
