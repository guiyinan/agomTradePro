"""Equity asset repository for the generic asset-analysis framework.

Owns `DjangoEquityAssetRepository` (the `AssetRepositoryProtocol`
implementation). The compatibility facade in `repositories.py` remains the
stable import surface; do not import it here.
"""

from decimal import Decimal, InvalidOperation
from math import isfinite

from apps.data_center.application.public import get_asset_repository_port
from apps.equity.domain.entities import (
    EquityAssetScore,
    FinancialData,
    StockInfo,
    TechnicalIndicators,
    ValuationMetrics,
)

from .stock_repository import DjangoStockRepository

# ==================== 通用资产分析框架集成 ====================
# 实现 AssetRepositoryProtocol 接口以支持通用资产分析


class DjangoEquityAssetRepository:
    """
    个股资产仓储（实现 AssetRepositoryProtocol）

    为通用资产分析框架提供个股数据访问接口。
    """

    def __init__(self) -> None:
        self._stock_repo = DjangoStockRepository()
        self._asset_repo = get_asset_repository_port()

    def get_assets_by_filter(
        self, asset_type: str, filters: dict[str, object], max_count: int = 100
    ) -> list[EquityAssetScore]:
        """
        根据过滤条件获取资产列表

        Args:
            asset_type: 资产类型（应为 "equity"）
            filters: 过滤条件字典
                - sector: 行业
                - market: 市场（SH/SZ/BJ）
                - min_market_cap: 最小市值（元）
                - max_market_cap: 最大市值（元）
                - min_pe: 最小市盈率
                - max_pe: 最大市盈率
            max_count: 最大返回数量

        Returns:
            EquityAssetScore 实体列表
        """
        if asset_type != "equity":
            return []
        if (
            isinstance(max_count, bool)
            or not isinstance(max_count, int)
            or not 1 <= max_count <= 1000
        ):
            raise ValueError("max_count must be an integer between 1 and 1000")

        # 应用过滤条件
        sector = filters.get("sector")
        if sector is not None and not isinstance(sector, str):
            raise ValueError("sector must be text")

        market = filters.get("market")
        if market is not None and not isinstance(market, str):
            raise ValueError("market must be text")

        min_market_cap = self._optional_decimal_filter(filters, "min_market_cap")
        max_market_cap = self._optional_decimal_filter(filters, "max_market_cap")
        min_pe = self._optional_float_filter(filters, "min_pe")
        max_pe = self._optional_float_filter(filters, "max_pe")
        if min_market_cap is not None and max_market_cap is not None:
            if min_market_cap > max_market_cap:
                raise ValueError("min_market_cap cannot exceed max_market_cap")
        if min_pe is not None and max_pe is not None and min_pe > max_pe:
            raise ValueError("min_pe cannot exceed max_pe")

        # Canonical asset-master and D1/D4/D5 facts are queried through the
        # Data Center repositories; legacy equity tables are not read.
        market_alias = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
        requested_exchange = (
            market_alias.get(str(market).upper(), str(market).upper()) if market else None
        )
        stocks_data = []
        for asset in self._asset_repo.list_active():
            if asset.asset_type.value != "stock":
                continue
            if sector and asset.sector != sector:
                continue
            if requested_exchange and asset.exchange.value != requested_exchange:
                continue
            stock_code = asset.code

            # 获取最新估值数据
            valuation = self._stock_repo._get_latest_valuation(
                stock_code,
                published_only=True,
            )

            if not valuation:
                continue

            if valuation.total_mv is None:
                # A missing market-cap fact cannot satisfy a market-cap filter
                # or be presented as a zero-valued asset.
                continue

            # 市值过滤
            if min_market_cap is not None and valuation.total_mv < min_market_cap:
                continue
            if max_market_cap is not None and valuation.total_mv > max_market_cap:
                continue

            # PE 过滤
            if min_pe is not None and (valuation.pe is None or valuation.pe < min_pe):
                continue
            if max_pe is not None and (valuation.pe is None or valuation.pe > max_pe):
                continue

            # 获取最新财务数据和 canonical 价格事实
            financial = self._stock_repo._get_latest_financial(
                stock_code,
                published_only=True,
            )
            daily = self._stock_repo._get_latest_price_bar(
                stock_code,
                published_only=True,
            )

            # 构建 EquityAssetScore
            stock_info = StockInfo(
                stock_code=asset.code,
                name=asset.short_name or asset.name,
                sector=asset.sector,
                market={"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(
                    asset.exchange.value,
                    asset.exchange.value,
                ),
                list_date=asset.list_date,
            )

            valuation_entity = valuation
            financial_entity = financial

            technical_entity = (
                TechnicalIndicators(
                    stock_code=stock_code,
                    trade_date=daily.bar_date,
                    close=Decimal(str(daily.close)),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                if daily
                else None
            )

            asset_score = EquityAssetScore.from_stock_info(
                stock_info, valuation_entity, financial_entity, technical_entity
            )

            stocks_data.append(asset_score)

            if len(stocks_data) >= max_count:
                break

        return stocks_data

    @staticmethod
    def _optional_decimal_filter(filters: dict[str, object], key: str) -> Decimal | None:
        """Parse one finite decimal filter without accepting booleans."""

        value = filters.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"{key} must be numeric")
        try:
            normalized = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if not normalized.is_finite():
            raise ValueError(f"{key} must be finite")
        if normalized < 0:
            raise ValueError(f"{key} cannot be negative")
        return normalized

    @staticmethod
    def _optional_float_filter(filters: dict[str, object], key: str) -> float | None:
        """Parse one finite float filter without accepting booleans."""

        value = filters.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"{key} must be numeric")
        normalized = float(value)
        if not isfinite(normalized):
            raise ValueError(f"{key} must be finite")
        return normalized

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> EquityAssetScore | None:
        """
        根据代码获取资产

        Args:
            asset_type: 资产类型（应为 "equity"）
            asset_code: 股票代码

        Returns:
            EquityAssetScore 实体，不存在则返回 None
        """
        if asset_type != "equity":
            return None

        asset = self._asset_repo.get_by_code(asset_code)
        if asset is None or not asset.is_active or asset.asset_type.value != "stock":
            return None

        try:
            stock_info = StockInfo(
                stock_code=asset.code,
                name=asset.short_name or asset.name,
                sector=asset.sector,
                market={"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(
                    asset.exchange.value,
                    asset.exchange.value,
                ),
                list_date=asset.list_date,
            )

            # 获取最新估值数据
            valuation = self._get_latest_valuation(asset_code, published_only=True)

            # 获取最新财务数据
            financial = self._get_latest_financial(asset_code, published_only=True)

            # 获取最新技术指标
            daily_model = self._stock_repo._get_latest_price_bar(
                asset_code,
                published_only=True,
            )

            technical = (
                TechnicalIndicators(
                    stock_code=asset_code,
                    trade_date=daily_model.bar_date,
                    close=Decimal(str(daily_model.close)),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                if daily_model
                else None
            )

            return EquityAssetScore.from_stock_info(stock_info, valuation, financial, technical)

        except (LookupError, ValueError):
            return None

    def _get_latest_financial(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
    ) -> FinancialData | None:
        return self._stock_repo._get_latest_financial(
            stock_code,
            published_only=published_only,
        )

    def _get_latest_valuation(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
    ) -> ValuationMetrics | None:
        return self._stock_repo._get_latest_valuation(
            stock_code,
            published_only=published_only,
        )


__all__ = ["DjangoEquityAssetRepository"]
