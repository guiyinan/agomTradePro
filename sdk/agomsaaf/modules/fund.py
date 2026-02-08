from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Fund 基金分析模块

提供基金分析相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule


class FundModule(BaseModule):
    """
    基金分析模块

    提供基金评分、推荐、分析等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Fund 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        # Backend fund endpoints are served under /fund/api/*
        super().__init__(client, "/fund/api")

    def get_fund_score(
        self,
        fund_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取基金评分

        Args:
            fund_code: 基金代码（如 000001.OF）
            as_of_date: 评分日期（None 表示最新）

        Returns:
            基金评分信息，包括综合评分、各维度分数

        Raises:
            NotFoundError: 当基金不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> score = client.fund.get_fund_score("000001.OF")
            >>> print(f"综合评分: {score['overall_score']}")
            >>> print(f"业绩分数: {score['performance_score']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"funds/{fund_code}/score/", params=params)

    def list_funds(
        self,
        fund_type: Optional[str] = None,
        min_score: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取基金列表

        Args:
            fund_type: 基金类型过滤（equity/bond/mixed/ETF 等）
            min_score: 最低评分过滤（可选）
            limit: 返回数量限制

        Returns:
            基金列表

        Example:
            >>> client = AgomSAAFClient()
            >>> funds = client.fund.list_funds(fund_type="equity")
            >>> for fund in funds:
            ...     print(f"{fund['code']}: {fund['name']}")
        """
        params: dict[str, Any] = {"limit": limit}

        if fund_type is not None:
            params["fund_type"] = fund_type
        if min_score is not None:
            params["min_score"] = min_score

        response = self._get("funds/", params=params)
        results = response.get("results", response)
        return results

    def get_fund_detail(self, fund_code: str) -> dict[str, Any]:
        """
        获取基金详情

        Args:
            fund_code: 基金代码

        Returns:
            基金详情信息

        Raises:
            NotFoundError: 当基金不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> detail = client.fund.get_fund_detail("000001.OF")
            >>> print(f"基金名称: {detail['name']}")
            >>> print(f"基金类型: {detail['fund_type']}")
        """
        return self._get(f"funds/{fund_code}/")

    def get_recommendations(
        self,
        regime: Optional[str] = None,
        fund_type: Optional[str] = None,
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
            >>> client = AgomSAAFClient()
            >>> recs = client.fund.get_recommendations(
            ...     regime="Recovery",
            ...     fund_type="equity"
            ... )
            >>> for fund in recs:
            ...     print(f"{fund['code']}: {fund['reason']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if regime is not None:
            params["regime"] = regime
        if fund_type is not None:
            params["fund_type"] = fund_type

        response = self._get("recommendations/", params=params)
        results = response.get("results", response)
        return results

    def analyze_fund(
        self,
        fund_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        分析基金

        返回基金的详细分析，包括业绩、风险、持仓等。

        Args:
            fund_code: 基金代码
            as_of_date: 分析日期（None 表示最新）

        Returns:
            基金分析结果

        Example:
            >>> client = AgomSAAFClient()
            >>> analysis = client.fund.analyze_fund("000001.OF")
            >>> print(f"业绩分析: {analysis['performance']}")
            >>> print(f"风险分析: {analysis['risk']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"funds/{fund_code}/analyze/", params=params)

    def get_nav_history(
        self,
        fund_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取基金净值历史

        Args:
            fund_code: 基金代码
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            limit: 返回数量限制

        Returns:
            净值历史列表

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> navs = client.fund.get_nav_history(
            ...     fund_code="000001.OF",
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31)
            ... )
            >>> for nav in navs:
            ...     print(f"{nav['date']}: {nav['nav']}")
        """
        params: dict[str, Any] = {"limit": limit}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()

        response = self._get(f"funds/{fund_code}/nav-history/", params=params)
        results = response.get("results", response)
        return results

    def get_holdings(
        self,
        fund_code: str,
        as_of_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """
        获取基金持仓

        Args:
            fund_code: 基金代码
            as_of_date: 持仓日期（None 表示最新）

        Returns:
            持仓列表

        Example:
            >>> client = AgomSAAFClient()
            >>> holdings = client.fund.get_holdings("000001.OF")
            >>> for h in holdings:
            ...     print(f"{h['stock_code']}: {h['weight']:.2%}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        response = self._get(f"funds/{fund_code}/holdings/", params=params)
        results = response.get("results", response)
        return results

    def get_performance(
        self,
        fund_code: str,
        period: str = "1y",
    ) -> dict[str, Any]:
        """
        获取基金业绩

        Args:
            fund_code: 基金代码
            period: 统计周期（1m/3m/6m/1y/3y/5y/ytd/inception）

        Returns:
            业绩数据，包括收益率、波动率、夏普比率等

        Example:
            >>> client = AgomSAAFClient()
            >>> perf = client.fund.get_performance("000001.OF", period="1y")
            >>> print(f"近一年收益: {perf['return']:.2%}")
            >>> print(f"夏普比率: {perf['sharpe']:.2f}")
        """
        return self._get(f"funds/{fund_code}/performance/", params={"period": period})
