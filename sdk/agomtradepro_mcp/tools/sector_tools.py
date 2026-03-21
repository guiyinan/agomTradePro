"""
AgomTradePro MCP Tools - Sector 板块分析工具

提供板块分析相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_sector_tools(server: FastMCP) -> None:
    """注册 Sector 相关的 MCP 工具"""

    @server.tool()
    def list_sectors(limit: int = 50) -> list[dict[str, Any]]:
        """
        获取板块列表

        Args:
            limit: 返回数量限制

        Returns:
            板块列表

        Example:
            >>> sectors = list_sectors()
        """
        client = AgomTradeProClient()
        return client.sector.list_sectors(limit=limit)

    @server.tool()
    def get_sector_score(
        sector_name: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取板块评分

        Args:
            sector_name: 板块名称
            as_of_date: 评分日期（ISO 格式，None 表示最新）

        Returns:
            板块评分信息

        Example:
            >>> score = get_sector_score("银行")
        """
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.sector.get_sector_score(sector_name, parsed_date)

    @server.tool()
    def get_sector_recommendations(
        regime: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        获取板块推荐

        Args:
            regime: 宏观象限过滤（可选）
            limit: 返回数量限制

        Returns:
            推荐板块列表

        Example:
            >>> recs = get_sector_recommendations(regime="Recovery")
        """
        client = AgomTradeProClient()
        return client.sector.get_recommendations(regime=regime, limit=limit)

    @server.tool()
    def analyze_sector(
        sector_name: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        分析板块

        Args:
            sector_name: 板块名称
            as_of_date: 分析日期（ISO 格式，None 表示最新）

        Returns:
            板块分析结果

        Example:
            >>> analysis = analyze_sector("银行")
        """
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.sector.analyze_sector(sector_name, parsed_date)

    @server.tool()
    def get_sector_stocks(
        sector_name: str,
        order_by: str = "score",
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        获取板块内股票列表

        Args:
            sector_name: 板块名称
            order_by: 排序方式（score/market_cap/change）
            limit: 返回数量限制

        Returns:
            板块内股票列表

        Example:
            >>> stocks = get_sector_stocks("银行", order_by="score")
        """
        client = AgomTradeProClient()
        return client.sector.get_sector_stocks(sector_name, order_by=order_by, limit=limit)

    @server.tool()
    def get_hot_sectors(limit: int = 10) -> list[dict[str, Any]]:
        """
        获取热门板块

        Args:
            limit: 返回数量限制

        Returns:
            热门板块列表

        Example:
            >>> hot = get_hot_sectors()
        """
        client = AgomTradeProClient()
        return client.sector.get_hot_sectors(limit=limit)

    @server.tool()
    def compare_sectors(sector_names: list[str]) -> dict[str, Any]:
        """
        比较多个板块

        Args:
            sector_names: 板块名称列表

        Returns:
            板块比较结果

        Example:
            >>> comparison = compare_sectors(["银行", "地产", "医药"])
        """
        client = AgomTradeProClient()
        return client.sector.compare_sectors(sector_names)

