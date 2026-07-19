"""Equity asset repository for the generic asset-analysis framework.

Owns `DjangoEquityAssetRepository` (the `AssetRepositoryProtocol`
implementation). The compatibility facade in `repositories.py` remains the
stable import surface; do not import it here.
"""

from django.db import models

from apps.equity.domain.entities import (
    EquityAssetScore,
    FinancialData,
    StockInfo,
    TechnicalIndicators,
    ValuationMetrics,
)

from .models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
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

    def get_assets_by_filter(
        self, asset_type: str, filters: dict, max_count: int = 100
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

        # 构建查询
        queryset = StockInfoModel._default_manager.filter(is_active=True)

        # 应用过滤条件
        sector = filters.get("sector")
        if sector:
            queryset = queryset.filter(sector=sector)

        market = filters.get("market")
        if market:
            queryset = queryset.filter(market=market)

        # 先筛出有估值数据的股票，避免先截断导致漏掉有效标的
        valuation_exists = ValuationModel._default_manager.filter(
            stock_code=models.OuterRef("stock_code")
        )
        queryset = (
            queryset.annotate(has_valuation=models.Exists(valuation_exists))
            .filter(has_valuation=True)
            .order_by("stock_code")
        )

        # 获取所有股票后再过滤（因为需要关联估值表）
        stocks_data = []
        for stock_model in queryset:
            stock_code = stock_model.stock_code

            # 获取最新估值数据
            valuation = (
                ValuationModel._default_manager.filter(stock_code=stock_code)
                .order_by("-trade_date")
                .first()
            )

            if not valuation:
                continue

            # 市值过滤
            min_market_cap = filters.get("min_market_cap")
            max_market_cap = filters.get("max_market_cap")
            if min_market_cap is not None and valuation.total_mv < min_market_cap:
                continue
            if max_market_cap is not None and valuation.total_mv > max_market_cap:
                continue

            # PE 过滤
            min_pe = filters.get("min_pe")
            max_pe = filters.get("max_pe")
            if min_pe is not None and (not valuation.pe or valuation.pe < min_pe):
                continue
            if max_pe is not None and (not valuation.pe or valuation.pe > max_pe):
                continue

            # 获取最新财务数据
            financial = (
                FinancialDataModel._default_manager.filter(stock_code=stock_code)
                .order_by("-report_date")
                .first()
            )

            # 获取最新技术指标（从日线数据）
            daily = (
                StockDailyModel._default_manager.filter(stock_code=stock_code)
                .order_by("-trade_date")
                .first()
            )

            # 构建 EquityAssetScore
            stock_info = StockInfo(
                stock_code=stock_model.stock_code,
                name=stock_model.name,
                sector=stock_model.sector,
                market=stock_model.market,
                list_date=stock_model.list_date,
            )

            valuation_entity = (
                ValuationMetrics(
                    stock_code=valuation.stock_code,
                    trade_date=valuation.trade_date,
                    pe=valuation.pe or 0.0,
                    pb=valuation.pb or 0.0,
                    ps=valuation.ps or 0.0,
                    total_mv=valuation.total_mv,
                    circ_mv=valuation.circ_mv,
                    dividend_yield=valuation.dividend_yield or 0.0,
                    source_provider=valuation.source_provider,
                    source_updated_at=valuation.source_updated_at,
                    fetched_at=valuation.fetched_at,
                    pe_type=valuation.pe_type,
                    is_valid=valuation.is_valid,
                    quality_flag=valuation.quality_flag,
                    quality_notes=valuation.quality_notes,
                    raw_payload_hash=valuation.raw_payload_hash,
                )
                if valuation
                else None
            )

            financial_entity = (
                FinancialData(
                    stock_code=financial.stock_code,
                    report_date=financial.report_date,
                    revenue=financial.revenue,
                    net_profit=financial.net_profit,
                    revenue_growth=financial.revenue_growth or 0.0,
                    net_profit_growth=financial.net_profit_growth or 0.0,
                    total_assets=financial.total_assets,
                    total_liabilities=financial.total_liabilities,
                    equity=financial.equity,
                    roe=financial.roe,
                    roa=financial.roa or 0.0,
                    debt_ratio=financial.debt_ratio,
                )
                if financial
                else None
            )

            technical_entity = (
                TechnicalIndicators(
                    stock_code=daily.stock_code,
                    trade_date=daily.trade_date,
                    close=daily.close,
                    ma5=daily.ma5,
                    ma20=daily.ma20,
                    ma60=daily.ma60,
                    macd=daily.macd,
                    macd_signal=daily.macd_signal,
                    macd_hist=daily.macd_hist,
                    rsi=daily.rsi,
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

        try:
            stock_model = StockInfoModel._default_manager.get(stock_code=asset_code, is_active=True)

            stock_info = StockInfo(
                stock_code=stock_model.stock_code,
                name=stock_model.name,
                sector=stock_model.sector,
                market=stock_model.market,
                list_date=stock_model.list_date,
            )

            # 获取最新估值数据
            valuation = self._get_latest_valuation(asset_code)

            # 获取最新财务数据
            financial = self._get_latest_financial(asset_code)

            # 获取最新技术指标
            daily_model = (
                StockDailyModel._default_manager.filter(stock_code=asset_code)
                .order_by("-trade_date")
                .first()
            )

            technical = (
                TechnicalIndicators(
                    stock_code=daily_model.stock_code,
                    trade_date=daily_model.trade_date,
                    close=daily_model.close,
                    ma5=daily_model.ma5,
                    ma20=daily_model.ma20,
                    ma60=daily_model.ma60,
                    macd=daily_model.macd,
                    macd_signal=daily_model.macd_signal,
                    macd_hist=daily_model.macd_hist,
                    rsi=daily_model.rsi,
                )
                if daily_model
                else None
            )

            return EquityAssetScore.from_stock_info(stock_info, valuation, financial, technical)

        except StockInfoModel.DoesNotExist:
            return None

    def _get_latest_financial(self, stock_code: str) -> FinancialData | None:
        items = self._stock_repo.get_financial_data(stock_code, limit=1)
        return items[0] if items else None

    def _get_latest_valuation(self, stock_code: str) -> ValuationMetrics | None:
        return self._stock_repo._get_latest_valuation(stock_code)


__all__ = ["DjangoEquityAssetRepository"]
