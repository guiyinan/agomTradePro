"""
AgomTradePro SDK - Market Data 统一数据源模块

提供行情、资金流向、新闻、交叉校验、Provider 健康检查等功能。
"""

from typing import Any, Optional

from .base import BaseModule


class MarketDataModule(BaseModule):
    """
    市场数据统一接入层模块

    封装 /api/market-data/ 下的所有端点，支持多数据源自动 failover。
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/market-data")

    # ------------------------------------------------------------------
    # 实时行情
    # ------------------------------------------------------------------

    def get_realtime_quotes(
        self,
        codes: list[str],
    ) -> list[dict[str, Any]]:
        """
        获取实时行情快照

        Args:
            codes: 股票代码列表（Tushare 格式，如 000001.SZ）

        Returns:
            行情快照列表

        Example:
            >>> client = AgomTradeProClient()
            >>> quotes = client.market_data.get_realtime_quotes(["000001.SZ", "600000.SH"])
            >>> for q in quotes:
            ...     print(f"{q['stock_code']}: {q['price']}")
        """
        response = self._get("quotes/", params={"codes": ",".join(codes)})
        return response.get("data", response) if isinstance(response, dict) else response

    # ------------------------------------------------------------------
    # 资金流向
    # ------------------------------------------------------------------

    def get_capital_flows(
        self,
        code: str,
        period: str = "5d",
    ) -> list[dict[str, Any]]:
        """
        获取个股资金流向

        Args:
            code: 股票代码
            period: 时间范围（默认 5d）

        Returns:
            资金流向列表

        Example:
            >>> flows = client.market_data.get_capital_flows("000001.SZ")
        """
        response = self._get("capital-flows/", params={"code": code, "period": period})
        return response.get("data", response) if isinstance(response, dict) else response

    def sync_capital_flow(
        self,
        stock_code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """
        同步个股资金流向到数据库

        Args:
            stock_code: 股票代码
            period: 时间范围

        Returns:
            同步结果（stock_code, synced_count, success, error_message）

        Example:
            >>> result = client.market_data.sync_capital_flow("000001.SZ")
            >>> print(f"同步 {result['synced_count']} 条")
        """
        return self._post("capital-flows/sync/", json={
            "stock_code": stock_code,
            "period": period,
        })

    # ------------------------------------------------------------------
    # 股票新闻
    # ------------------------------------------------------------------

    def get_stock_news(
        self,
        code: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取个股新闻

        Args:
            code: 股票代码
            limit: 最多返回条数

        Returns:
            新闻列表

        Example:
            >>> news = client.market_data.get_stock_news("000001.SZ", limit=5)
        """
        response = self._get("news/", params={"code": code, "limit": limit})
        return response.get("data", response) if isinstance(response, dict) else response

    def ingest_stock_news(
        self,
        stock_code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        采集个股新闻到数据库

        Args:
            stock_code: 股票代码
            limit: 最多采集条数

        Returns:
            采集结果（fetched_count, new_count, data_sufficient, success）

        Example:
            >>> result = client.market_data.ingest_stock_news("000001.SZ")
            >>> print(f"新增 {result['new_count']} 条新闻")
        """
        return self._post("news/ingest/", json={
            "stock_code": stock_code,
            "limit": limit,
        })

    # ------------------------------------------------------------------
    # Provider 健康 / 交叉校验
    # ------------------------------------------------------------------

    def get_provider_health(self) -> list[dict[str, Any]]:
        """
        获取所有数据源 Provider 健康状态

        Returns:
            Provider 状态列表（provider_name, capability, is_healthy, consecutive_failures 等）

        Example:
            >>> statuses = client.market_data.get_provider_health()
            >>> for s in statuses:
            ...     print(f"{s['provider_name']} {s['capability']}: {'OK' if s['is_healthy'] else 'FAIL'}")
        """
        response = self._get("providers/health/")
        return response.get("data", response) if isinstance(response, dict) else response

    def cross_validate(
        self,
        codes: list[str],
    ) -> dict[str, Any]:
        """
        交叉校验多数据源行情

        从主/备数据源分别获取行情并比对偏差。

        Args:
            codes: 股票代码列表

        Returns:
            校验结果（quotes_count, validation: {total_checked, matches, deviations, alerts, is_clean}）

        Example:
            >>> result = client.market_data.cross_validate(["000001.SZ"])
            >>> v = result.get("validation")
            >>> if v and v["is_clean"]:
            ...     print("数据源一致")
        """
        response = self._get("cross-validate/", params={"codes": ",".join(codes)})
        return response.get("data", response) if isinstance(response, dict) else response
