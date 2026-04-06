"""AgomTradePro MCP Tools - Data Center tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_data_center_tools(server: FastMCP) -> None:
    @server.tool()
    def data_center_get_quotes(asset_code: str) -> dict[str, Any]:
        """读取指定资产的最新行情快照。"""
        client = AgomTradeProClient()
        return client.data_center.get_latest_quotes(asset_code)

    @server.tool()
    def data_center_get_price_history(
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """读取指定资产的历史价格。"""
        client = AgomTradeProClient()
        return client.data_center.get_price_history(asset_code, start=start, end=end, limit=limit)

    @server.tool()
    def data_center_get_macro_series(
        indicator_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """读取指定宏观指标的标准化时序。"""
        client = AgomTradeProClient()
        return client.data_center.get_macro_series(
            indicator_code,
            start=start,
            end=end,
            limit=limit,
        )

    @server.tool()
    def data_center_get_capital_flows(
        asset_code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """读取指定资产的资金流数据。"""
        client = AgomTradeProClient()
        return client.data_center.get_capital_flows(asset_code, period=period)

    @server.tool()
    def data_center_sync_capital_flows(
        provider_id: int,
        asset_code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """同步指定资产的资金流事实。"""
        client = AgomTradeProClient()
        return client.data_center.sync_capital_flows(
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "period": period,
            }
        )

    @server.tool()
    def data_center_get_news(
        asset_code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """读取指定资产的新闻事实。"""
        client = AgomTradeProClient()
        return client.data_center.get_news(asset_code, limit=limit)

    @server.tool()
    def data_center_sync_news(
        provider_id: int,
        asset_code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """同步指定资产的新闻事实。"""
        client = AgomTradeProClient()
        return client.data_center.sync_news(
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "limit": limit,
            }
        )

    @server.tool()
    def get_data_center_provider_status() -> list[dict[str, Any]]:
        """获取数据中台全部 Provider 的运行状态。"""
        client = AgomTradeProClient()
        return client.data_center.get_provider_status()
