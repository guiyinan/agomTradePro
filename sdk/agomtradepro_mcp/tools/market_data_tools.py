"""
AgomTradePro MCP Tools - Market Data 市场数据工具

提供统一数据源接入层的 MCP 工具：行情、资金流向、新闻、交叉校验、Provider 健康检查。
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_market_data_tools(server: FastMCP) -> None:
    """注册 Market Data 相关的 MCP 工具"""

    # ------------------------------------------------------------------
    # 实时行情
    # ------------------------------------------------------------------

    @server.tool()
    def market_data_get_quotes(
        codes: str,
    ) -> list[dict[str, Any]]:
        """
        获取多只股票的实时行情快照（统一数据源层，自动 failover）

        通过统一数据源接入层获取行情，自动在东方财富、AKShare、Tushare 之间 failover。

        Args:
            codes: 逗号分隔的股票代码（Tushare 格式，如 000001.SZ,600000.SH）

        Returns:
            行情快照列表，每项包含 stock_code、price、change、change_pct、volume 等

        Example:
            >>> quotes = market_data_get_quotes("000001.SZ,600000.SH")
        """
        client = AgomTradeProClient()
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        return client.market_data.get_realtime_quotes(code_list)

    # ------------------------------------------------------------------
    # 资金流向
    # ------------------------------------------------------------------

    @server.tool()
    def market_data_get_capital_flows(
        code: str,
        period: str = "5d",
    ) -> list[dict[str, Any]]:
        """
        获取个股资金流向明细（主力/散户净流入）

        Args:
            code: 股票代码（如 000001.SZ）
            period: 时间范围（5d/10d/30d）

        Returns:
            资金流向列表，包含日期、主力净流入、散户净流入等

        Example:
            >>> flows = market_data_get_capital_flows("000001.SZ", period="10d")
        """
        client = AgomTradeProClient()
        return client.market_data.get_capital_flows(code, period=period)

    @server.tool()
    def market_data_sync_capital_flows(
        code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """
        同步个股资金流向到数据库

        Args:
            code: 股票代码（如 000001.SZ）
            period: 时间范围（5d/10d/30d）

        Returns:
            同步结果（synced_count, success, error_message）

        Example:
            >>> result = market_data_sync_capital_flows("000001.SZ")
        """
        client = AgomTradeProClient()
        return client.market_data.sync_capital_flow(code, period=period)

    # ------------------------------------------------------------------
    # 股票新闻
    # ------------------------------------------------------------------

    @server.tool()
    def market_data_get_stock_news(
        code: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取个股相关新闻

        Args:
            code: 股票代码（如 000001.SZ）
            limit: 最多返回条数

        Returns:
            新闻列表，包含标题、来源、发布时间等

        Example:
            >>> news = market_data_get_stock_news("000001.SZ", limit=5)
        """
        client = AgomTradeProClient()
        return client.market_data.get_stock_news(code, limit=limit)

    @server.tool()
    def market_data_ingest_news(
        code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        采集个股新闻到数据库（去重存储）

        Args:
            code: 股票代码（如 000001.SZ）
            limit: 最多采集条数

        Returns:
            采集结果（fetched_count, new_count, data_sufficient, success）

        Example:
            >>> result = market_data_ingest_news("000001.SZ")
        """
        client = AgomTradeProClient()
        return client.market_data.ingest_stock_news(code, limit=limit)

    # ------------------------------------------------------------------
    # Provider 健康 / 交叉校验
    # ------------------------------------------------------------------

    @server.tool()
    def market_data_provider_health() -> list[dict[str, Any]]:
        """
        获取所有数据源 Provider 健康状态

        Returns:
            Provider 状态列表，包含 provider_name、capability、is_healthy、
            consecutive_failures、avg_latency_ms 等

        Example:
            >>> statuses = market_data_provider_health()
            >>> for s in statuses:
            ...     print(f"{s['provider_name']}: {'健康' if s['is_healthy'] else '异常'}")
        """
        client = AgomTradeProClient()
        return client.market_data.get_provider_health()

    @server.tool()
    def market_data_cross_validate(
        codes: str,
    ) -> dict[str, Any]:
        """
        交叉校验多数据源行情一致性

        从主/备数据源分别获取指定股票行情并比对价格偏差（容差 1%，告警 5%）。

        Args:
            codes: 逗号分隔的股票代码（如 000001.SZ,600000.SH）

        Returns:
            校验结果：quotes_count, validation（含 total_checked, matches, deviations, alerts, is_clean）

        Example:
            >>> result = market_data_cross_validate("000001.SZ")
        """
        client = AgomTradeProClient()
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        return client.market_data.cross_validate(code_list)
