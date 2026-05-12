"""AgomTradePro MCP Tools - Asset Analysis 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_asset_analysis_tools(server: FastMCP) -> None:
    @server.tool()
    def asset_multidim_screen(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.asset_analysis.multidim_screen(payload)

    @server.tool()
    def get_asset_weight_configs() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.asset_analysis.get_weight_configs()

    @server.tool()
    def get_asset_current_weight() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.asset_analysis.get_current_weight()

    @server.tool()
    def asset_pool_screen(asset_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.asset_analysis.screen_asset_pool(asset_type, payload)

    @server.tool()
    def asset_pool_summary(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.asset_analysis.pool_summary(payload)
