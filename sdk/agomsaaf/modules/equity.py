"""
AgomSAAF SDK - Equity 个股分析模块

提供个股分析相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from agomsaaf.modules.base import BaseModule


class EquityModule(BaseModule):
    """
    个股分析模块

    提供股票评分、推荐、分析等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Equity 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/equity")

    def get_stock_score(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取股票评分

        Args:
            stock_code: 股票代码（如 000001.SZ）
            as_of_date: 评分日期（None 表示最新）

        Returns:
            股票评分信息，包括综合评分、各维度分数

        Raises:
            NotFoundError: 当股票不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> score = client.equity.get_stock_score("000001.SZ")
            >>> print(f"综合评分: {score['overall_score']}")
            >>> print(f"估值分数: {score['valuation_score']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"stocks/{stock_code}/score/", params=params)

    def list_stocks(
        self,
        sector: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取股票列表

        Args:
            sector: 行业过滤（可选）
            min_score: 最低评分过滤（可选）
            max_score: 最高评分过滤（可选）
            limit: 返回数量限制

        Returns:
            股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> stocks = client.equity.list_stocks(
            ...     sector="银行",
            ...     min_score=60
            ... )
            >>> for stock in stocks:
            ...     print(f"{stock['code']}: {stock['name']}")
        """
        params: dict[str, Any] = {"limit": limit}

        if sector is not None:
            params["sector"] = sector
        if min_score is not None:
            params["min_score"] = min_score
        if max_score is not None:
            params["max_score"] = max_score

        response = self._get("stocks/", params=params)
        results = response.get("results", response)
        return results

    def get_stock_detail(self, stock_code: str) -> dict[str, Any]:
        """
        获取股票详情

        Args:
            stock_code: 股票代码

        Returns:
            股票详情信息

        Raises:
            NotFoundError: 当股票不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> detail = client.equity.get_stock_detail("000001.SZ")
            >>> print(f"股票名称: {detail['name']}")
            >>> print(f"行业: {detail['sector']}")
        """
        return self._get(f"stocks/{stock_code}/")

    def get_recommendations(
        self,
        regime: Optional[str] = None,
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
            >>> client = AgomSAAFClient()
            >>> recs = client.equity.get_recommendations(regime="Recovery")
            >>> for stock in recs:
            ...     print(f"{stock['code']}: {stock['reason']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if regime is not None:
            params["regime"] = regime

        response = self._get("recommendations/", params=params)
        results = response.get("results", response)
        return results

    def analyze_stock(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        分析股票

        返回股票的详细分析，包括基本面、技术面、估值等。

        Args:
            stock_code: 股票代码
            as_of_date: 分析日期（None 表示最新）

        Returns:
            股票分析结果

        Example:
            >>> client = AgomSAAFClient()
            >>> analysis = client.equity.analyze_stock("000001.SZ")
            >>> print(f"基本面分析: {analysis['fundamental']}")
            >>> print(f"技术面分析: {analysis['technical']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"stocks/{stock_code}/analyze/", params=params)

    def get_sector_stocks(self, sector: str) -> list[dict[str, Any]]:
        """
        获取行业股票列表

        Args:
            sector: 行业名称

        Returns:
            该行业的股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> stocks = client.equity.get_sector_stocks("银行")
            >>> for stock in stocks:
            ...     print(f"{stock['code']}: {stock['name']}")
        """
        return self._get(f"sectors/{sector}/stocks/")

    def get_financials(
        self,
        stock_code: str,
        report_type: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        获取财务数据

        Args:
            stock_code: 股票代码
            report_type: 报告类型（annual/quarterly）
            limit: 返回数量限制

        Returns:
            财务数据列表

        Example:
            >>> client = AgomSAAFClient()
            >>> financials = client.equity.get_financials("000001.SZ")
            >>> for f in financials:
            ...     print(f"{f['report_date']}: 营收 {f['revenue']}")
        """
        params: dict[str, Any] = {"report_type": report_type, "limit": limit}
        response = self._get(f"stocks/{stock_code}/financials/", params=params)
        results = response.get("results", response)
        return results

    def get_valuation(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取估值数据

        Args:
            stock_code: 股票代码
            as_of_date: 估值日期（None 表示最新）

        Returns:
            估值数据，包括 PE、PB、PS 等指标

        Example:
            >>> client = AgomSAAFClient()
            >>> valuation = client.equity.get_valuation("000001.SZ")
            >>> print(f"PE: {valuation['pe']}")
            >>> print(f"PB: {valuation['pb']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"stocks/{stock_code}/valuation/", params=params)
