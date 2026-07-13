"""
AgomTradePro SDK - Factor Module

因子选股模块 SDK 封装。
"""

from datetime import date
from typing import TYPE_CHECKING, Any

from ..exceptions import NotFoundError

if TYPE_CHECKING:
    from ..client import AgomTradeProClient


FACTOR_FOCUS_WEIGHTS: dict[str, dict[str, float]] = {
    "value": {
        "pe_ttm": -0.4,
        "pb": -0.3,
        "roe": 0.15,
        "revenue_growth": 0.1,
        "profit_growth": 0.05,
    },
    "growth": {
        "revenue_growth": 0.35,
        "profit_growth": 0.35,
        "roe": 0.2,
        "momentum_3m": 0.1,
    },
    "quality": {
        "roe": 0.3,
        "roa": 0.2,
        "debt_ratio": -0.2,
        "current_ratio": 0.15,
        "gross_margin": 0.15,
    },
    "balanced": {
        "pe_ttm": -0.2,
        "pb": -0.1,
        "roe": 0.25,
        "revenue_growth": 0.2,
        "profit_growth": 0.15,
        "momentum_3m": 0.1,
    },
}


def resolve_factor_focus_weights(focus: str) -> dict[str, float]:
    """Return the stable factor-weight contract for one explanation focus."""

    if focus not in FACTOR_FOCUS_WEIGHTS:
        raise ValueError(
            "focus must be one of: value, growth, quality, balanced"
        )
    return dict(FACTOR_FOCUS_WEIGHTS[focus])


class FactorModule:
    """因子选股模块"""

    def __init__(self, client: "AgomTradeProClient") -> None:
        """初始化模块"""
        self._client = client

    def get_all_factors(self) -> list[dict[str, Any]]:
        """
        获取所有因子定义

        Returns:
            因子列表
        """
        return self._client.get("/api/factor/all-factors/")

    def get_all_configs(self) -> list[dict[str, Any]]:
        """
        获取所有因子组合配置

        Returns:
            配置列表
        """
        return self._client.get("/api/factor/all-configs/")

    def get_top_stocks(
        self,
        factor_preferences: dict[str, str],
        top_n: int = 30
    ) -> dict[str, Any]:
        """
        获取因子选股结果

        Args:
            factor_preferences: 因子偏好设置
                e.g., {"value": "high", "quality": "high", "growth": "medium"}
            top_n: 返回股票数量

        Returns:
            选股结果
        """
        return self._client.post(
            "/api/factor/top-stocks/",
            json={
                "factor_preferences": factor_preferences,
                "top_n": top_n,
            }
        )

    def create_portfolio(
        self,
        config_name: str,
        trade_date: date | None = None
    ) -> dict[str, Any]:
        """
        创建因子组合

        Args:
            config_name: 配置名称
            trade_date: 交易日期

        Returns:
            组合详情
        """
        date_str = trade_date.isoformat() if trade_date else None
        return self._client.post(
            "/api/factor/create-portfolio/",
            json={
                "config_name": config_name,
                "trade_date": date_str,
            }
        )

    def explain_stock(
        self,
        stock_code: str,
        factor_weights: dict[str, float]
    ) -> dict[str, Any]:
        """
        解释股票因子得分

        Args:
            stock_code: 股票代码
            factor_weights: 因子权重

        Returns:
            得分说明
        """
        return self._client.post(
            "/api/factor/explain-stock/",
            json={
                "stock_code": stock_code,
                "factor_weights": factor_weights,
            }
        )

    def explain_stock_by_focus(
        self,
        stock_code: str,
        focus: str = "balanced",
    ) -> dict[str, Any]:
        """Explain one stock using the stable named focus contract."""

        return self.explain_stock(
            stock_code,
            resolve_factor_focus_weights(focus),
        )

    def get_portfolio(self, config_name: str) -> dict[str, Any] | None:
        """
        获取因子组合最新持仓

        Args:
            config_name: 配置名称

        Returns:
            持仓详情
        """
        try:
            return self._client.get(
                "/api/factor/portfolio/",
                params={"config_name": config_name},
            )
        except NotFoundError:
            return None
