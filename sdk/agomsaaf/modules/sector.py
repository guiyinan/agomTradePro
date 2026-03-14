from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Sector 板块分析模块

提供板块分析相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule


class SectorModule(BaseModule):
    """
    板块分析模块

    提供板块评分、推荐、分析等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Sector 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/sector")

    def list_sectors(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取板块列表

        Args:
            limit: 返回数量限制

        Returns:
            板块列表

        Example:
            >>> client = AgomSAAFClient()
            >>> sectors = client.sector.list_sectors()
            >>> for sector in sectors:
            ...     print(f"{sector['name']}: {sector['stock_count']}")
        """
        regime = self._resolve_current_regime()
        params: dict[str, Any] = {"top_n": limit}
        if regime:
            params["regime"] = regime
        response = self._get("rotation/", params=params)
        return response.get("top_sectors", [])

    def get_sector_score(
        self,
        sector_name: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取板块评分

        Args:
            sector_name: 板块名称
            as_of_date: 评分日期（None 表示最新）

        Returns:
            板块评分信息，包括综合评分、各维度分数

        Raises:
            NotFoundError: 当板块不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> score = client.sector.get_sector_score("银行")
            >>> print(f"综合评分: {score['overall_score']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"sectors/{sector_name}/score/", params=params)

    def get_sector_detail(self, sector_name: str) -> dict[str, Any]:
        """
        获取板块详情

        Args:
            sector_name: 板块名称

        Returns:
            板块详情信息

        Raises:
            NotFoundError: 当板块不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> detail = client.sector.get_sector_detail("银行")
            >>> print(f"股票数量: {detail['stock_count']}")
            >>> print(f"总市值: {detail['total_market_cap']}")
        """
        return self._get(f"sectors/{sector_name}/")

    def get_recommendations(
        self,
        regime: Optional[str] = None,
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
            >>> client = AgomSAAFClient()
            >>> recs = client.sector.get_recommendations(regime="Recovery")
            >>> for sector in recs:
            ...     print(f"{sector['name']}: {sector['reason']}")
        """
        params: dict[str, Any] = {"top_n": limit}
        if regime is not None:
            params["regime"] = regime

        response = self._get("rotation/", params=params)
        return response.get("top_sectors", [])

    def _resolve_current_regime(self) -> Optional[str]:
        response = self._client.get("/api/regime/current/")
        if isinstance(response, dict):
            payload = response.get("data", response)
            return payload.get("dominant_regime")
        return None

    def analyze_sector(
        self,
        sector_name: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        分析板块

        返回板块的详细分析，包括基本面、估值、资金流向等。

        Args:
            sector_name: 板块名称
            as_of_date: 分析日期（None 表示最新）

        Returns:
            板块分析结果

        Example:
            >>> client = AgomSAAFClient()
            >>> analysis = client.sector.analyze_sector("银行")
            >>> print(f"估值分析: {analysis['valuation']}")
            >>> print(f"资金流向: {analysis['fund_flow']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"sectors/{sector_name}/analyze/", params=params)

    def get_sector_stocks(
        self,
        sector_name: str,
        order_by: str = "score",
        limit: int = 50,
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
            >>> client = AgomSAAFClient()
            >>> stocks = client.sector.get_sector_stocks("银行", order_by="score")
            >>> for stock in stocks:
            ...     print(f"{stock['code']}: {stock['score']}")
        """
        params: dict[str, Any] = {"order_by": order_by, "limit": limit}
        response = self._get(f"sectors/{sector_name}/stocks/", params=params)
        results = response.get("results", response)
        return results

    def get_sector_performance(
        self,
        sector_name: str,
        period: str = "1m",
    ) -> dict[str, Any]:
        """
        获取板块业绩

        Args:
            sector_name: 板块名称
            period: 统计周期（1d/1w/1m/3m/6m/1y）

        Returns:
            板块业绩数据

        Example:
            >>> client = AgomSAAFClient()
            >>> perf = client.sector.get_sector_performance("银行", period="1m")
            >>> print(f"近一月涨跌: {perf['change']:.2%}")
        """
        return self._get(f"sectors/{sector_name}/performance/", params={"period": period})

    def compare_sectors(
        self,
        sector_names: list[str],
    ) -> dict[str, Any]:
        """
        比较多个板块

        Args:
            sector_names: 板块名称列表

        Returns:
            板块比较结果

        Example:
            >>> client = AgomSAAFClient()
            >>> comparison = client.sector.compare_sectors(["银行", "地产", "医药"])
            >>> for sector, data in comparison.items():
            ...     print(f"{sector}: 评分 {data['score']}")
        """
        data = {"sectors": sector_names}
        return self._post("compare/", json=data)

    def get_hot_sectors(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        获取热门板块

        Args:
            limit: 返回数量限制

        Returns:
            热门板块列表（按资金流入或涨幅排序）

        Example:
            >>> client = AgomSAAFClient()
            >>> hot = client.sector.get_hot_sectors()
            >>> for sector in hot:
            ...     print(f"{sector['name']}: {sector['change']:.2%}")
        """
        params: dict[str, Any] = {"limit": limit}
        response = self._get("hot-sectors/", params=params)
        results = response.get("results", response)
        return results
