"""
AgomSAAF MCP Tools - Realtime 实时价格监控工具

提供实时价格监控相关的 MCP 工具。
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_realtime_tools(server: FastMCP) -> None:
    """注册 Realtime 相关的 MCP 工具"""

    @server.tool()
    def get_realtime_price(asset_code: str) -> dict[str, Any]:
        """
        获取实时价格

        Args:
            asset_code: 资产代码

        Returns:
            实时价格信息

        Example:
            >>> price = get_realtime_price("000001.SH")
        """
        client = AgomSAAFClient()
        return client.realtime.get_price(asset_code)

    @server.tool()
    def get_multiple_realtime_prices(asset_codes: list[str]) -> dict[str, dict[str, Any]]:
        """
        批量获取实时价格

        Args:
            asset_codes: 资产代码列表

        Returns:
            资产代码到价格信息的字典

        Example:
            >>> prices = get_multiple_realtime_prices(["000001.SH", "000002.SZ"])
        """
        client = AgomSAAFClient()
        return client.realtime.get_multiple_prices(asset_codes)

    @server.tool()
    def get_price_history(
        asset_code: str,
        period: str = "1d",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取价格历史

        Args:
            asset_code: 资产代码
            period: 时间周期（1m/5m/15m/30m/60m/1d/1w/1M）
            limit: 返回数量限制

        Returns:
            价格历史列表

        Example:
            >>> history = get_price_history("000001.SH", period="1d", limit=30)
        """
        client = AgomSAAFClient()
        return client.realtime.get_price_history(asset_code, period, limit)

    @server.tool()
    def get_market_summary() -> dict[str, Any]:
        """
        获取市场概况

        Returns:
            市场概况，包括主要指数、涨跌统计、成交额等

        Example:
            >>> summary = get_market_summary()
        """
        client = AgomSAAFClient()
        return client.realtime.get_market_summary()

    @server.tool()
    def get_sector_realtime_performance() -> list[dict[str, Any]]:
        """
        获取板块实时表现

        Returns:
            板块表现列表

        Example:
            >>> sectors = get_sector_realtime_performance()
        """
        client = AgomSAAFClient()
        return client.realtime.get_sector_performance()

    @server.tool()
    def get_top_movers(
        direction: str = "up",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        获取涨幅榜/跌幅榜

        Args:
            direction: 方向（up/down）
            limit: 返回数量限制

        Returns:
            涨跌幅榜列表

        Example:
            >>> top_gainers = get_top_movers(direction="up")
        """
        client = AgomSAAFClient()
        return client.realtime.get_top_movers(direction, limit)

    @server.tool()
    def list_price_alerts(
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取价格预警列表

        Args:
            status: 预警状态过滤（active/triggered/inactive）
            limit: 返回数量限制

        Returns:
            预警列表

        Example:
            >>> alerts = list_price_alerts(status="active")
        """
        client = AgomSAAFClient()
        return client.realtime.list_alerts(status=status, limit=limit)

    @server.tool()
    def create_price_alert(
        asset_code: str,
        condition: str,
        threshold: float,
        message: str | None = None,
    ) -> dict[str, Any]:
        """
        创建价格预警

        Args:
            asset_code: 资产代码
            condition: 触发条件（above/below/cross_up/cross_down）
            threshold: 阈值
            message: 预警消息（可选）

        Returns:
            创建的预警信息

        Example:
            >>> alert = create_price_alert(
            ...     asset_code="000001.SH",
            ...     condition="above",
            ...     threshold=10.0,
            ...     message="价格突破10元"
            ... )
        """
        client = AgomSAAFClient()
        return client.realtime.create_alert(asset_code, condition, threshold, message)

    @server.tool()
    def delete_price_alert(alert_id: int) -> None:
        """
        删除预警

        Args:
            alert_id: 预警 ID

        Example:
            >>> delete_price_alert(1)
        """
        client = AgomSAAFClient()
        client.realtime.delete_alert(alert_id)

