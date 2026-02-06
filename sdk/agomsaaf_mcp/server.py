"""
AgomSAAF MCP Server

MCP (Model Context Protocol) Server for AgomSAAF.
Provides AI-native tools for Claude Code and other AI agents.
"""

import asyncio
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

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
server = Server("agomsaaf")


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


# 注册所有工具
register_all_tools()


@server.list_resources()
async def list_resources() -> list[Any]:
    """列出所有可用的 MCP 资源"""
    return [
        {
            "uri": "agomsaaf://regime/current",
            "name": "Current Regime",
            "description": "当前宏观象限状态",
            "mime_type": "text/plain",
        },
        {
            "uri": "agomsaaf://policy/status",
            "name": "Policy Status",
            "description": "当前政策档位状态",
            "mime_type": "text/plain",
        },
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """读取 MCP 资源内容"""
    from agomsaaf import AgomSAAFClient

    client = AgomSAAFClient()

    if uri == "agomsaaf://regime/current":
        regime = client.regime.get_current()
        return f"""当前宏观环境: {regime.dominant_regime}
增长水平: {regime.growth_level}
通胀水平: {regime.inflation_level}
观测日期: {regime.observed_at}
增长指标: {regime.growth_indicator} ({regime.growth_value})
通胀指标: {regime.inflation_indicator} ({regime.inflation_value})"""

    elif uri == "agomsaaf://policy/status":
        status = client.policy.get_status()
        recent_events_desc = "\n".join(
            f"  - {e.event_date}: {e.description}" for e in status.recent_events
        )
        return f"""当前政策档位: {status.current_gear}
观测日期: {status.observed_at}

最近事件:
{recent_events_desc or "  无"}"""

    else:
        return f"Unknown resource: {uri}"


@server.list_prompts()
async def list_prompts() -> list[Any]:
    """列出所有可用的 Prompt 模板"""
    return [
        {
            "name": "analyze_macro_environment",
            "description": "分析当前宏观环境并给出投资建议",
            "arguments": [],
        },
        {
            "name": "check_signal_eligibility",
            "description": "检查投资信号是否符合准入条件",
            "arguments": [
                {
                    "name": "asset_code",
                    "description": "资产代码（如 000001.SH）",
                    "required": True,
                },
                {
                    "name": "logic_desc",
                    "description": "投资逻辑描述",
                    "required": True,
                },
            ],
        },
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> str:
    """获取 Prompt 模板内容"""
    if name == "analyze_macro_environment":
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

    elif name == "check_signal_eligibility":
        asset_code = arguments.get("asset_code", "") if arguments else ""
        logic_desc = arguments.get("logic_desc", "") if arguments else ""
        return f"""请检查以下投资信号是否符合准入条件：

资产代码：{asset_code}
投资逻辑：{logic_desc}

分析步骤：
1. 使用 get_current_regime 获取当前宏观象限
2. 使用 get_policy_status 获取当前政策档位
3. 使用 check_signal_eligibility 工具检查准入条件
4. 根据检查结果给出明确的准入/不准入建议

请详细说明准入或不准入的原因。"""

    else:
        return f"Unknown prompt: {name}"


async def main() -> None:
    """启动 MCP 服务器"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
