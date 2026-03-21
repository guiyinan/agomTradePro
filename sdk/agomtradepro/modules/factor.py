"""
AgomTradePro SDK - Factor Module

因子选股模块 SDK 封装。
"""

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..client import AgomTradeProClient


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
        trade_date: Optional[date] = None
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

    def get_portfolio(self, config_name: str) -> Optional[dict[str, Any]]:
        """
        获取因子组合最新持仓

        Args:
            config_name: 配置名称

        Returns:
            持仓详情
        """
        from apps.factor.infrastructure.repositories import FactorPortfolioHoldingRepository
        repo = FactorPortfolioHoldingRepository()
        holdings = repo.get_latest_holdings(config_name)

        if not holdings:
            return None

        return {
            'config_name': config_name,
            'trade_date': holdings[0].trade_date.isoformat() if holdings else '',
            'total_stocks': len(holdings),
            'holdings': [
                {
                    'stock_code': h.stock_code,
                    'stock_name': h.stock_name,
                    'weight': round(float(h.weight) * 100, 2),
                    'factor_score': round(float(h.factor_score), 2),
                    'rank': h.rank,
                    'sector': h.sector,
                }
                for h in holdings
            ],
        }
