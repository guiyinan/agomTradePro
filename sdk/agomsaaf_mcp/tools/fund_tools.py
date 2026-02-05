"""
AgomSAAF MCP Tools - Fund 基金分析工具

提供基金分析相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server import Server

from agomsaaf import AgomSAAFClient


def register_fund_tools(server: Server) -> None:
    """注册 Fund 相关的 MCP 工具"""

    @server.tool()
    def get_fund_score(
        fund_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取基金评分

        Args:
            fund_code: 基金代码（如 000001.OF）
            as_of_date: 评分日期（ISO 格式，None 表示最新）

        Returns:
            基金评分信息

        Example:
            >>> score = get_fund_score("000001.OF")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.fund.get_fund_score(fund_code, parsed_date)

    @server.tool()
    def list_funds(
        fund_type: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取基金列表

        Args:
            fund_type: 基金类型过滤（equity/bond/mixed/ETF）
            min_score: 最低评分过滤（可选）
            limit: 返回数量限制

        Returns:
            基金列表

        Example:
            >>> funds = list_funds(fund_type="equity", min_score=60)
        """
        client = AgomSAAFClient()
        return client.fund.list_funds(fund_type=fund_type, min_score=min_score, limit=limit)

    @server.tool()
    def get_fund_detail(fund_code: str) -> dict[str, Any]:
        """
        获取基金详情

        Args:
            fund_code: 基金代码

        Returns:
            基金详情

        Example:
            >>> detail = get_fund_detail("000001.OF")
        """
        client = AgomSAAFClient()
        return client.fund.get_fund_detail(fund_code)

    @server.tool()
    def get_fund_recommendations(
        regime: str | None = None,
        fund_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取基金推荐

        Args:
            regime: 宏观象限过滤（可选）
            fund_type: 基金类型过滤（可选）
            limit: 返回数量限制

        Returns:
            推荐基金列表

        Example:
            >>> recs = get_fund_recommendations(regime="Recovery", fund_type="equity")
        """
        client = AgomSAAFClient()
        return client.fund.get_recommendations(regime=regime, fund_type=fund_type, limit=limit)

    @server.tool()
    def analyze_fund(
        fund_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        分析基金

        Args:
            fund_code: 基金代码
            as_of_date: 分析日期（ISO 格式，None 表示最新）

        Returns:
            基金分析结果

        Example:
            >>> analysis = analyze_fund("000001.OF")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.fund.analyze_fund(fund_code, parsed_date)

    @server.tool()
    def get_fund_performance(
        fund_code: str,
        period: str = "1y",
    ) -> dict[str, Any]:
        """
        获取基金业绩

        Args:
            fund_code: 基金代码
            period: 统计周期（1m/3m/6m/1y/3y/5y/ytd/inception）

        Returns:
            业绩数据

        Example:
            >>> perf = get_fund_performance("000001.OF", period="1y")
        """
        client = AgomSAAFClient()
        return client.fund.get_performance(fund_code, period)

    @server.tool()
    def get_fund_holdings(
        fund_code: str,
        as_of_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取基金持仓

        Args:
            fund_code: 基金代码
            as_of_date: 持仓日期（ISO 格式，None 表示最新）

        Returns:
            持仓列表

        Example:
            >>> holdings = get_fund_holdings("000001.OF")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.fund.get_holdings(fund_code, parsed_date)
