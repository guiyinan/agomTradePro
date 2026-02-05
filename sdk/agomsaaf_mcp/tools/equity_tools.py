"""
AgomSAAF MCP Tools - Equity 个股分析工具

提供个股分析相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server import Server

from agomsaaf import AgomSAAFClient


def register_equity_tools(server: Server) -> None:
    """注册 Equity 相关的 MCP 工具"""

    @server.tool()
    def get_stock_score(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取股票评分

        Args:
            stock_code: 股票代码（如 000001.SZ）
            as_of_date: 评分日期（ISO 格式，None 表示最新）

        Returns:
            股票评分信息

        Example:
            >>> score = get_stock_score("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.get_stock_score(stock_code, parsed_date)

    @server.tool()
    def list_stocks(
        sector: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取股票列表

        Args:
            sector: 行业过滤（可选）
            min_score: 最低评分过滤（可选）
            limit: 返回数量限制

        Returns:
            股票列表

        Example:
            >>> stocks = list_stocks(sector="银行", min_score=60)
        """
        client = AgomSAAFClient()
        return client.equity.list_stocks(sector=sector, min_score=min_score, limit=limit)

    @server.tool()
    def get_stock_detail(stock_code: str) -> dict[str, Any]:
        """
        获取股票详情

        Args:
            stock_code: 股票代码

        Returns:
            股票详情

        Example:
            >>> detail = get_stock_detail("000001.SZ")
        """
        client = AgomSAAFClient()
        return client.equity.get_stock_detail(stock_code)

    @server.tool()
    def get_stock_recommendations(
        regime: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取股票推荐

        Args:
            regime: 宏观象限过滤（可选）
            limit: 返回数量限制

        Returns:
            推荐股票列表

        Example:
            >>> recs = get_stock_recommendations(regime="Recovery")
        """
        client = AgomSAAFClient()
        return client.equity.get_recommendations(regime=regime, limit=limit)

    @server.tool()
    def analyze_stock(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        分析股票

        Args:
            stock_code: 股票代码
            as_of_date: 分析日期（ISO 格式，None 表示最新）

        Returns:
            股票分析结果

        Example:
            >>> analysis = analyze_stock("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.analyze_stock(stock_code, parsed_date)

    @server.tool()
    def get_stock_financials(
        stock_code: str,
        report_type: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        获取股票财务数据

        Args:
            stock_code: 股票代码
            report_type: 报告类型（annual/quarterly）
            limit: 返回数量限制

        Returns:
            财务数据列表

        Example:
            >>> financials = get_stock_financials("000001.SZ")
        """
        client = AgomSAAFClient()
        return client.equity.get_financials(stock_code, report_type, limit)

    @server.tool()
    def get_stock_valuation(
        stock_code: str,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取股票估值数据

        Args:
            stock_code: 股票代码
            as_of_date: 估值日期（ISO 格式，None 表示最新）

        Returns:
            估值数据

        Example:
            >>> valuation = get_stock_valuation("000001.SZ")
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.equity.get_valuation(stock_code, parsed_date)
