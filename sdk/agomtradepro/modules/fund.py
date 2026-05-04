"""
AgomTradePro SDK - Fund 基金分析模块

提供基金分析相关的 API 操作。
"""

from datetime import date, timedelta
from typing import Any

from ..exceptions import AgomTradeProAPIError
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
            client: AgomTradePro 客户端实例
        """
        super().__init__(client, "/api/fund")

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        """
        Normalize SDK input to the canonical backend fund code.

        The current fund API uses the local six-digit code. Keep accepting
        legacy SDK examples such as ``000001.OF`` by stripping the suffix.
        """
        normalized = fund_code.strip().upper()
        if normalized.endswith(".OF"):
            return normalized[:-3]
        return normalized

    def _filter_ranked_funds(
        self,
        ranked_funds: list[dict[str, Any]],
        *,
        fund_type: str | None,
        min_score: float | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Apply compatibility filters on top of canonical rank results."""
        filtered: list[dict[str, Any]] = []
        expected_type = fund_type.strip() if fund_type else None

        for fund in ranked_funds:
            total_score = fund.get("total_score")
            if min_score is not None and isinstance(total_score, (int, float)):
                if float(total_score) < min_score:
                    continue

            if expected_type:
                detail = self.get_fund_detail(
                    self._normalize_fund_code(str(fund.get("fund_code") or fund.get("code") or ""))
                )
                actual_type = str(detail.get("fund_type") or "").strip()
                if actual_type != expected_type:
                    continue

            filtered.append(fund)
            if len(filtered) >= limit:
                break

        return filtered

    @staticmethod
    def _parse_nav_date(raw_value: Any) -> date | None:
        """Parse nav date from API payload."""
        if isinstance(raw_value, date):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return date.fromisoformat(raw_value)
            except ValueError:
                return None
        return None

    def _resolve_latest_available_nav_date(self, fund_code: str) -> date | None:
        """
        Resolve the latest local NAV date for period-based performance calls.

        SDK callers often use local historical-only datasets. Anchoring to
        ``date.today()`` can therefore miss the latest available research window
        and produce a false 404 from ``performance/calculate/``.
        """
        nav_history = self.get_nav_history(fund_code, limit=5000)
        nav_dates = [
            parsed
            for parsed in (
                self._parse_nav_date(item.get("nav_date"))
                for item in nav_history
                if isinstance(item, dict)
            )
            if parsed is not None
        ]
        if not nav_dates:
            return None
        return max(nav_dates)

    def get_fund_score(
        self,
        fund_code: str,
        as_of_date: date | None = None,
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
            >>> client = AgomTradeProClient()
            >>> score = client.fund.get_fund_score("000001.OF")
            >>> print(f"综合评分: {score['overall_score']}")
            >>> print(f"业绩分数: {score['performance_score']}")
        """
        normalized_code = self._normalize_fund_code(fund_code)
        funds = self.list_funds(limit=200)
        for fund in funds:
            candidate_code = str(fund.get("fund_code") or fund.get("code") or "")
            if self._normalize_fund_code(candidate_code) == normalized_code:
                return fund
        return {
            "success": False,
            "fund_code": normalized_code,
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "error": "fund score endpoint is not exposed by current canonical API",
        }

    def list_funds(
        self,
        fund_type: str | None = None,
        min_score: float | None = None,
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
            >>> client = AgomTradeProClient()
            >>> funds = client.fund.list_funds(fund_type="equity")
            >>> for fund in funds:
            ...     print(f"{fund['code']}: {fund['name']}")
        """
        ranked_funds = self.rank_funds(max_count=max(limit * 3, limit))
        return self._filter_ranked_funds(
            ranked_funds,
            fund_type=fund_type,
            min_score=min_score,
            limit=limit,
        )

    def rank_funds(
        self,
        regime: str = "Recovery",
        max_count: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return canonical ranked fund results from ``/api/fund/rank/``.
        """
        response = self._get(
            "rank/",
            params={"regime": regime, "max_count": max_count},
        )
        return response.get("funds", [])

    def screen_funds(
        self,
        regime: str | None = None,
        custom_types: list[str] | None = None,
        custom_styles: list[str] | None = None,
        min_scale: float | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """
        Call the canonical fund screening endpoint.
        """
        payload: dict[str, Any] = {"max_count": limit}
        if regime is not None:
            payload["regime"] = regime
        if custom_types:
            payload["custom_types"] = custom_types
        if custom_styles:
            payload["custom_styles"] = custom_styles
        if min_scale is not None:
            payload["min_scale"] = min_scale
        return self._post("screen/", json=payload)

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
            >>> client = AgomTradeProClient()
            >>> detail = client.fund.get_fund_detail("000001.OF")
            >>> print(f"基金名称: {detail['name']}")
            >>> print(f"基金类型: {detail['fund_type']}")
        """
        response = self._get(f"info/{self._normalize_fund_code(fund_code)}/")
        return response.get("fund", response)

    def get_recommendations(
        self,
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
            >>> client = AgomTradeProClient()
            >>> recs = client.fund.get_recommendations(
            ...     regime="Recovery",
            ...     fund_type="equity"
            ... )
            >>> for fund in recs:
            ...     print(f"{fund['code']}: {fund['reason']}")
        """
        ranked_funds = self.rank_funds(
            regime=regime or "Recovery",
            max_count=max(limit * 3, limit),
        )
        return self._filter_ranked_funds(
            ranked_funds,
            fund_type=fund_type,
            min_score=None,
            limit=limit,
        )

    def analyze_fund(
        self,
        fund_code: str,
        report_date: date | None = None,
        *,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """
        分析基金

        返回基金的详细分析，包括业绩、风险、持仓等。

        Args:
            fund_code: 基金代码
            report_date: 报告日期（None 表示最新）
            as_of_date: 分析日期兼容别名

        Returns:
            基金分析结果

        Example:
            >>> client = AgomTradeProClient()
            >>> analysis = client.fund.analyze_fund("000001.OF")
            >>> print(f"业绩分析: {analysis['performance']}")
            >>> print(f"风险分析: {analysis['risk']}")
        """
        effective_report_date = report_date or as_of_date
        params: dict[str, Any] = {}
        if effective_report_date is not None:
            params["report_date"] = effective_report_date.isoformat()

        return self._get(
            f"style/{self._normalize_fund_code(fund_code)}/",
            params=params,
        )

    def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
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
            >>> client = AgomTradeProClient()
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

        response = self._get(
            f"nav/{self._normalize_fund_code(fund_code)}/",
            params=params,
        )
        return response.get(
            "nav_data",
            response.get("data", response.get("results", response)),
        )

    def get_holdings(
        self,
        fund_code: str,
        report_date: date | None = None,
        *,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取基金持仓

        Args:
            fund_code: 基金代码
            report_date: 报告日期（None 表示最新）
            as_of_date: 持仓日期兼容别名

        Returns:
            持仓列表

        Example:
            >>> client = AgomTradeProClient()
            >>> holdings = client.fund.get_holdings("000001.OF")
            >>> for h in holdings:
            ...     print(f"{h['stock_code']}: {h['weight']:.2%}")
        """
        effective_report_date = report_date or as_of_date
        params: dict[str, Any] = {}
        if effective_report_date is not None:
            params["report_date"] = effective_report_date.isoformat()

        response = self._get(
            f"holding/{self._normalize_fund_code(fund_code)}/",
            params=params,
        )
        return response.get(
            "holdings",
            response.get("data", response.get("results", response)),
        )

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
            >>> client = AgomTradeProClient()
            >>> perf = client.fund.get_performance("000001.OF", period="1y")
            >>> print(f"近一年收益: {perf['return']:.2%}")
            >>> print(f"夏普比率: {perf['sharpe']:.2f}")
        """
        days_by_period = {
            "1m": 30,
            "3m": 90,
            "6m": 180,
            "1y": 365,
            "3y": 365 * 3,
            "5y": 365 * 5,
            "ytd": max((date.today() - date(date.today().year, 1, 1)).days, 1),
            "inception": 365 * 10,
        }
        days = days_by_period.get(period, 365)
        normalized_code = self._normalize_fund_code(fund_code)
        end_date = self._resolve_latest_available_nav_date(normalized_code) or date.today()
        start_date = end_date - timedelta(days=days)
        try:
            response = self._post(
                "performance/calculate/",
                json={
                    "fund_code": normalized_code,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
        except AgomTradeProAPIError as exc:
            return {
                "success": False,
                "fund_code": fund_code,
                "period": period,
                "error": str(exc),
            }
        return response.get("performance", response)
