"""
个股分析模块 Infrastructure 层数据仓储

遵循四层架构规范：
- Infrastructure 层允许导入 django.db
- 实现 Domain 层定义的接口（如果有的话）
- 负责数据持久化逻辑
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import requests
from django.db import models
from django.utils import timezone

from apps.data_center.domain.entities import FinancialFact, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module
from apps.data_center.infrastructure.repositories import (
    AssetRepository as DataCenterAssetRepository,
)
from apps.data_center.infrastructure.repositories import (
    FinancialFactRepository as DataCenterFinancialFactRepository,
)
from apps.data_center.infrastructure.repositories import (
    PriceBarRepository as DataCenterPriceBarRepository,
)
from apps.data_center.infrastructure.repositories import (
    QuoteSnapshotRepository as DataCenterQuoteSnapshotRepository,
)
from apps.data_center.infrastructure.repositories import (
    ValuationFactRepository as DataCenterValuationFactRepository,
)
from apps.equity.domain.entities import (
    EquityAssetScore,
    FinancialData,
    IntradayPricePoint,
    StockInfo,
    TechnicalBar,
    TechnicalIndicators,
    ValuationMetrics,
)
from core.exceptions import DataFetchError, DataValidationError

from .adapters import TushareStockAdapter
from .models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationDataQualitySnapshotModel,
    ValuationModel,
)

logger = logging.getLogger(__name__)

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


class DjangoStockRepository:
    """Django ORM 个股数据仓储"""

    _EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    _EASTMONEY_METADATA_FIELDS = "f43,f57,f58"

    def __init__(self) -> None:
        self._last_intraday_source: str | None = None
        self._dc_asset_repo = DataCenterAssetRepository()
        self._dc_financial_repo = DataCenterFinancialFactRepository()
        self._dc_price_bar_repo = DataCenterPriceBarRepository()
        self._dc_quote_repo = DataCenterQuoteSnapshotRepository()
        self._dc_valuation_repo = DataCenterValuationFactRepository()

    def get_all_stocks_with_fundamentals(
        self, as_of_date: date | None = None
    ) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]:
        """
        获取所有股票的基本面数据（最新财务数据 + 最新估值数据）

        Args:
            as_of_date: 截止日期（可选），如果不指定则使用最新数据

        Returns:
            [(StockInfo, FinancialData, ValuationMetrics), ...]
        """
        result = []

        # 获取所有活跃股票的基本信息
        stock_infos = StockInfoModel._default_manager.filter(is_active=True)

        for stock_info_model in stock_infos:
            stock_code = stock_info_model.stock_code

            # 转换为 Domain 层实体
            stock_info = StockInfo(
                stock_code=stock_info_model.stock_code,
                name=stock_info_model.name,
                sector=stock_info_model.sector,
                market=stock_info_model.market,
                list_date=stock_info_model.list_date,
            )

            # 获取最新财务数据
            financial = self._get_latest_financial(stock_code)
            if not financial:
                # 没有财务数据，跳过
                continue

            # 获取最新估值数据
            valuation = self._get_latest_valuation(stock_code)
            if not valuation:
                # 没有估值数据，跳过
                continue

            result.append((stock_info, financial, valuation))

        return result

    def get_stock_info(self, stock_code: str) -> StockInfo | None:
        """
        获取单个股票的基本信息

        Args:
            stock_code: 股票代码

        Returns:
            StockInfo 或 None
        """
        dc_info = self._get_stock_info_from_data_center(stock_code)
        if dc_info is not None:
            return dc_info

        for candidate in self._build_stock_code_candidates(stock_code):
            model = StockInfoModel._default_manager.filter(stock_code=candidate).first()
            if model is not None:
                return StockInfo(
                    stock_code=model.stock_code,
                    name=model.name,
                    sector=model.sector,
                    market=model.market,
                    list_date=model.list_date,
                )
        fallback_info = self._get_minimal_stock_info_from_data_center(stock_code)
        if fallback_info is not None:
            return fallback_info
        return None

    def resolve_stock_names(self, stock_codes: list[str]) -> dict[str, str]:
        """批量解析股票名称。"""
        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        requested_codes = list(dict.fromkeys(normalized_codes))
        candidate_codes = {
            candidate
            for code in requested_codes
            for candidate in self._build_stock_code_candidates(code)
        }
        models = StockInfoModel._default_manager.filter(stock_code__in=list(candidate_codes))
        model_map = {model.stock_code.upper(): model for model in models}

        resolved: dict[str, str] = {}
        for requested_code in requested_codes:
            for candidate in self._build_stock_code_candidates(requested_code):
                model = model_map.get(candidate.upper())
                if model is not None and model.name:
                    resolved[requested_code] = model.name
                    break
        return resolved

    def get_financial_data(self, stock_code: str, limit: int = 4) -> list[FinancialData]:
        """
        获取股票的财务数据

        Args:
            stock_code: 股票代码
            limit: 限制返回数量（默认 4，即最近 4 个季度）

        Returns:
            FinancialData 列表，按日期降序排列
        """
        dc_financials = self._get_financials_from_data_center(stock_code, limit=limit)
        if dc_financials:
            return dc_financials

        for candidate in self._build_stock_code_candidates(stock_code):
            models = FinancialDataModel._default_manager.filter(stock_code=candidate).order_by(
                "-report_date"
            )[:limit]
            if not models:
                continue
            return [
                FinancialData(
                    stock_code=m.stock_code,
                    report_date=m.report_date,
                    revenue=m.revenue,
                    net_profit=m.net_profit,
                    revenue_growth=m.revenue_growth or 0.0,
                    net_profit_growth=m.net_profit_growth or 0.0,
                    total_assets=m.total_assets,
                    total_liabilities=m.total_liabilities,
                    equity=m.equity,
                    roe=m.roe,
                    roa=m.roa or 0.0,
                    debt_ratio=m.debt_ratio,
                )
                for m in models
            ]
        return []

    def get_valuation_history(
        self, stock_code: str, start_date: date, end_date: date
    ) -> list[ValuationMetrics]:
        """
        获取股票的估值历史数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            ValuationMetrics 列表，按日期升序排列
        """
        dc_valuations = self._get_valuations_from_data_center(stock_code, start_date, end_date)
        if dc_valuations:
            return dc_valuations

        for candidate in self._build_stock_code_candidates(stock_code):
            models = ValuationModel._default_manager.filter(
                stock_code=candidate,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            ).order_by("trade_date")
            if not models:
                continue
            return [
                ValuationMetrics(
                    stock_code=m.stock_code,
                    trade_date=m.trade_date,
                    pe=m.pe or 0.0,
                    pb=m.pb or 0.0,
                    ps=m.ps or 0.0,
                    total_mv=m.total_mv,
                    circ_mv=m.circ_mv,
                    dividend_yield=m.dividend_yield or 0.0,
                    source_provider=m.source_provider,
                    source_updated_at=m.source_updated_at,
                    fetched_at=m.fetched_at,
                    pe_type=m.pe_type,
                    is_valid=m.is_valid,
                    quality_flag=m.quality_flag,
                    quality_notes=m.quality_notes,
                    raw_payload_hash=m.raw_payload_hash,
                )
                for m in models
            ]
        return []

    def save_stock_info(self, stock_info: StockInfo) -> None:
        """
        保存股票基本信息

        Args:
            stock_info: StockInfo 实体
        """
        # Remote fallback metadata can be partial; skip caching if required fields are missing.
        if stock_info.list_date is None:
            logger.info(
                "Skip caching stock info for %s because list_date is unavailable",
                stock_info.stock_code,
            )
            return

        StockInfoModel._default_manager.update_or_create(
            stock_code=stock_info.stock_code,
            defaults={
                "name": stock_info.name,
                "sector": stock_info.sector,
                "market": stock_info.market,
                "list_date": stock_info.list_date,
            },
        )

    def save_financial_data(self, financial: FinancialData) -> None:
        """
        保存财务数据

        Args:
            financial: FinancialData 实体
        """
        # 确定报告类型
        month = financial.report_date.month
        if month == 3:
            report_type = "1Q"
        elif month == 6:
            report_type = "2Q"
        elif month == 9:
            report_type = "3Q"
        else:
            report_type = "4Q"

        FinancialDataModel._default_manager.update_or_create(
            stock_code=financial.stock_code,
            report_date=financial.report_date,
            report_type=report_type,
            defaults={
                "revenue": financial.revenue,
                "net_profit": financial.net_profit,
                "revenue_growth": financial.revenue_growth,
                "net_profit_growth": financial.net_profit_growth,
                "total_assets": financial.total_assets,
                "total_liabilities": financial.total_liabilities,
                "equity": financial.equity,
                "roe": financial.roe,
                "roa": financial.roa,
                "debt_ratio": financial.debt_ratio,
            },
        )
        self._dc_financial_repo.bulk_upsert(
            self._financial_entity_to_dc_facts(financial, report_type)
        )

    def save_valuation(self, valuation: ValuationMetrics) -> None:
        """
        保存估值数据

        Args:
            valuation: ValuationMetrics 实体
        """
        ValuationModel._default_manager.update_or_create(
            stock_code=valuation.stock_code,
            trade_date=valuation.trade_date,
            defaults={
                "pe": valuation.pe,
                "pb": valuation.pb,
                "ps": valuation.ps,
                "total_mv": valuation.total_mv,
                "circ_mv": valuation.circ_mv,
                "dividend_yield": valuation.dividend_yield,
                "source_provider": valuation.source_provider,
                "source_updated_at": valuation.source_updated_at,
                "fetched_at": valuation.fetched_at or timezone.now(),
                "pe_type": valuation.pe_type,
                "is_valid": valuation.is_valid,
                "quality_flag": valuation.quality_flag,
                "quality_notes": valuation.quality_notes,
                "raw_payload_hash": valuation.raw_payload_hash,
            },
        )
        self._dc_valuation_repo.bulk_upsert([self._valuation_entity_to_dc_fact(valuation)])

    def _get_latest_financial(self, stock_code: str) -> FinancialData | None:
        dc_items = self._get_financials_from_data_center(stock_code, limit=1)
        if dc_items:
            return dc_items[0]

        for candidate in self._build_stock_code_candidates(stock_code):
            financial_model = (
                FinancialDataModel._default_manager.filter(stock_code=candidate)
                .order_by("-report_date")
                .first()
            )
            if financial_model is None:
                continue
            return FinancialData(
                stock_code=financial_model.stock_code,
                report_date=financial_model.report_date,
                revenue=financial_model.revenue,
                net_profit=financial_model.net_profit,
                revenue_growth=financial_model.revenue_growth or 0.0,
                net_profit_growth=financial_model.net_profit_growth or 0.0,
                total_assets=financial_model.total_assets,
                total_liabilities=financial_model.total_liabilities,
                equity=financial_model.equity,
                roe=financial_model.roe,
                roa=financial_model.roa or 0.0,
                debt_ratio=financial_model.debt_ratio,
            )
        return None

    def _get_latest_valuation(self, stock_code: str) -> ValuationMetrics | None:
        dc_item = self._dc_valuation_repo.get_latest(stock_code)
        if dc_item is not None:
            return self._dc_fact_to_valuation(dc_item)

        for candidate in self._build_stock_code_candidates(stock_code):
            valuation_model = (
                ValuationModel._default_manager.filter(stock_code=candidate)
                .order_by("-trade_date")
                .first()
            )
            if valuation_model is None:
                continue
            return ValuationMetrics(
                stock_code=valuation_model.stock_code,
                trade_date=valuation_model.trade_date,
                pe=valuation_model.pe or 0.0,
                pb=valuation_model.pb or 0.0,
                ps=valuation_model.ps or 0.0,
                total_mv=valuation_model.total_mv,
                circ_mv=valuation_model.circ_mv,
                dividend_yield=valuation_model.dividend_yield or 0.0,
                source_provider=valuation_model.source_provider,
                source_updated_at=valuation_model.source_updated_at,
                fetched_at=valuation_model.fetched_at,
                pe_type=valuation_model.pe_type,
                is_valid=valuation_model.is_valid,
                quality_flag=valuation_model.quality_flag,
                quality_notes=valuation_model.quality_notes,
                raw_payload_hash=valuation_model.raw_payload_hash,
            )
        return None

    def _get_financials_from_data_center(
        self,
        stock_code: str,
        limit: int,
    ) -> list[FinancialData]:
        facts = self._dc_financial_repo.get_facts(stock_code, limit=max(limit * 12, 40))
        if not facts:
            return []

        grouped: dict[date, dict[str, FinancialFact]] = {}
        report_dates: dict[date, date | None] = {}
        for fact in facts:
            grouped.setdefault(fact.period_end, {})[fact.metric_code] = fact
            if fact.period_end not in report_dates or report_dates[fact.period_end] is None:
                report_dates[fact.period_end] = fact.report_date

        results: list[FinancialData] = []
        required_metrics = {
            "revenue",
            "net_profit",
            "total_assets",
            "total_liabilities",
            "equity",
            "roe",
            "debt_ratio",
        }
        for period_end in sorted(grouped.keys(), reverse=True):
            metric_map = grouped[period_end]
            if not required_metrics.issubset(metric_map.keys()):
                continue
            results.append(
                FinancialData(
                    stock_code=stock_code,
                    report_date=report_dates.get(period_end) or period_end,
                    revenue=Decimal(str(metric_map["revenue"].value)),
                    net_profit=Decimal(str(metric_map["net_profit"].value)),
                    revenue_growth=(
                        float(metric_map.get("revenue_growth").value)
                        if metric_map.get("revenue_growth")
                        else 0.0
                    ),
                    net_profit_growth=(
                        float(metric_map.get("net_profit_growth").value)
                        if metric_map.get("net_profit_growth")
                        else 0.0
                    ),
                    total_assets=Decimal(str(metric_map["total_assets"].value)),
                    total_liabilities=Decimal(str(metric_map["total_liabilities"].value)),
                    equity=Decimal(str(metric_map["equity"].value)),
                    roe=float(metric_map["roe"].value),
                    roa=float(metric_map.get("roa").value) if metric_map.get("roa") else 0.0,
                    debt_ratio=float(metric_map["debt_ratio"].value),
                )
            )
            if len(results) >= limit:
                break
        return results

    def _get_valuations_from_data_center(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetrics]:
        facts = self._dc_valuation_repo.get_series(stock_code, start=start_date, end=end_date)
        if not facts:
            return []
        return [self._dc_fact_to_valuation(fact) for fact in reversed(facts)]

    def _dc_fact_to_valuation(self, fact: ValuationFact) -> ValuationMetrics:
        total_mv = fact.market_cap if fact.market_cap is not None else 0.0
        circ_mv = fact.float_market_cap if fact.float_market_cap is not None else total_mv
        return ValuationMetrics(
            stock_code=fact.asset_code,
            trade_date=fact.val_date,
            pe=fact.pe_ttm or fact.pe_static or 0.0,
            pb=fact.pb or 0.0,
            ps=fact.ps_ttm or 0.0,
            total_mv=Decimal(str(total_mv)),
            circ_mv=Decimal(str(circ_mv)),
            dividend_yield=fact.dv_ratio or 0.0,
            source_provider=fact.source,
            source_updated_at=fact.fetched_at,
            fetched_at=fact.fetched_at,
            pe_type="ttm" if fact.pe_ttm is not None else "static",
        )

    def _financial_entity_to_dc_facts(
        self,
        financial: FinancialData,
        report_type: str,
    ) -> list[FinancialFact]:
        period_type_map = {
            "1Q": FinancialPeriodType.QUARTERLY,
            "2Q": FinancialPeriodType.SEMI_ANNUAL,
            "3Q": FinancialPeriodType.QUARTERLY,
            "4Q": FinancialPeriodType.ANNUAL,
        }
        common = {
            "asset_code": financial.stock_code,
            "period_end": financial.report_date,
            "period_type": period_type_map[report_type],
            "source": "equity_legacy_repo",
            "report_date": financial.report_date,
        }
        return [
            FinancialFact(
                metric_code="revenue", value=float(financial.revenue), unit="元", **common
            ),
            FinancialFact(
                metric_code="net_profit", value=float(financial.net_profit), unit="元", **common
            ),
            FinancialFact(
                metric_code="revenue_growth",
                value=float(financial.revenue_growth),
                unit="%",
                **common,
            ),
            FinancialFact(
                metric_code="net_profit_growth",
                value=float(financial.net_profit_growth),
                unit="%",
                **common,
            ),
            FinancialFact(
                metric_code="total_assets", value=float(financial.total_assets), unit="元", **common
            ),
            FinancialFact(
                metric_code="total_liabilities",
                value=float(financial.total_liabilities),
                unit="元",
                **common,
            ),
            FinancialFact(metric_code="equity", value=float(financial.equity), unit="元", **common),
            FinancialFact(metric_code="roe", value=float(financial.roe), unit="%", **common),
            FinancialFact(metric_code="roa", value=float(financial.roa), unit="%", **common),
            FinancialFact(
                metric_code="debt_ratio", value=float(financial.debt_ratio), unit="%", **common
            ),
        ]

    def _valuation_entity_to_dc_fact(self, valuation: ValuationMetrics) -> ValuationFact:
        return ValuationFact(
            asset_code=valuation.stock_code,
            val_date=valuation.trade_date,
            pe_ttm=valuation.pe,
            pb=valuation.pb,
            ps_ttm=valuation.ps,
            market_cap=float(valuation.total_mv),
            float_market_cap=float(valuation.circ_mv),
            dv_ratio=valuation.dividend_yield,
            source=valuation.source_provider or "equity_legacy_repo",
            fetched_at=valuation.fetched_at or timezone.now(),
        )

    def get_daily_prices(
        self, stock_code: str, start_date: date, end_date: date
    ) -> list[tuple[date, Decimal]]:
        """
        获取股票的日线收盘价数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [(日期, 收盘价), ...]，按日期升序排列
        """
        dc_bars = self._dc_price_bar_repo.get_bars(
            stock_code,
            start=start_date,
            end=end_date,
            limit=max((end_date - start_date).days + 10, 120),
        )
        if dc_bars:
            return [
                (bar.bar_date, Decimal(str(bar.close)))
                for bar in sorted(dc_bars, key=lambda item: item.bar_date)
            ]

        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")
        local_prices = [(m.trade_date, m.close) for m in models]
        if local_prices:
            return local_prices

        return self._get_remote_daily_prices(stock_code, start_date, end_date)

    def get_technical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[TechnicalBar]:
        """获取K线与技术指标序列。"""
        dc_bars = self._dc_price_bar_repo.get_bars(
            stock_code,
            start=start_date,
            end=end_date,
            limit=max((end_date - start_date).days + 10, 120),
        )
        if dc_bars:
            return self._price_bars_to_technical_bars(stock_code, dc_bars)

        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")

        local_bars = [
            TechnicalBar(
                stock_code=model.stock_code,
                trade_date=model.trade_date,
                open=model.open,
                high=model.high,
                low=model.low,
                close=model.close,
                volume=model.volume,
                amount=model.amount,
                ma5=model.ma5,
                ma20=model.ma20,
                ma60=model.ma60,
                macd=model.macd,
                macd_signal=model.macd_signal,
                macd_hist=model.macd_hist,
                rsi=model.rsi,
            )
            for model in models
        ]
        if local_bars:
            return local_bars

        remote_bars = self._get_remote_historical_bars(stock_code, start_date, end_date)
        self._cache_remote_historical_bars(stock_code, remote_bars)
        return self._recalculate_technical_bars(
            [
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=bar.trade_date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=bar.volume or 0,
                    amount=self._safe_decimal(getattr(bar, "amount", None)) or Decimal("0"),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                for bar in remote_bars
            ]
        )

    def get_intraday_points(self, stock_code: str) -> list[IntradayPricePoint]:
        """获取单资产最新交易日的 1 分钟分时数据。"""
        try:
            quotes = self._dc_quote_repo.get_series(stock_code, limit=600)
        except RuntimeError as exc:
            logger.debug(
                "Skip data center intraday lookup for %s because DB access is unavailable: %s",
                stock_code,
                exc,
            )
            quotes = []
        except Exception as exc:
            logger.warning("Failed to load quote snapshots for %s: %s", stock_code, exc)
            quotes = []

        if quotes:
            market_tz = ZoneInfo("Asia/Shanghai")
            latest_session = max(quote.snapshot_at.astimezone(market_tz).date() for quote in quotes)
            session_quotes = sorted(
                [
                    quote
                    for quote in quotes
                    if quote.snapshot_at.astimezone(market_tz).date() == latest_session
                ],
                key=lambda item: item.snapshot_at,
            )

            points: list[IntradayPricePoint] = []
            for quote in session_quotes:
                price = self._safe_decimal(quote.current_price)
                if price is None or price <= 0:
                    continue

                volume = self._safe_int(quote.volume)
                points.append(
                    IntradayPricePoint(
                        stock_code=stock_code,
                        timestamp=quote.snapshot_at.astimezone(market_tz),
                        price=price,
                        avg_price=price,
                        volume=volume,
                    )
                )

            if points:
                self._last_intraday_source = "data_center_quote_snapshot"
                return points

        symbol = self._to_akshare_symbol(stock_code)
        self._last_intraday_source = None

        primary_error: DataFetchError | None = None
        try:
            primary_points = self._get_intraday_hist_min_points(stock_code, symbol)
        except DataFetchError as exc:
            primary_points = []
            primary_error = exc
            logger.warning("Primary intraday source failed for %s: %s", stock_code, exc)

        if primary_points:
            self._last_intraday_source = "akshare_hist_min_em"
            return self._validate_intraday_points(primary_points, "akshare_hist_min_em")

        try:
            fallback_points = self._get_intraday_tick_points(stock_code, symbol)
        except DataFetchError as exc:
            if primary_error is not None:
                raise DataFetchError(
                    message=f"{stock_code} 分时主备数据源均不可用",
                    details={
                        "stock_code": stock_code,
                        "primary_source": "akshare_hist_min_em",
                        "primary_error": primary_error.message,
                        "fallback_source": "akshare_intraday_em",
                        "fallback_error": exc.message,
                    },
                ) from exc
            raise

        if not fallback_points:
            if primary_error is not None:
                raise primary_error
            return []

        if primary_error is None:
            logger.warning(
                "Primary intraday source returned no data for %s; rejecting unvalidated fallback",
                stock_code,
            )
            raise DataFetchError(
                message=f"{stock_code} 主分时数据源暂无数据，拒绝切换到未校验备用源",
                details={
                    "stock_code": stock_code,
                    "primary_source": "akshare_hist_min_em",
                    "fallback_source": "akshare_intraday_em",
                },
            )

        validated_fallback = self._validate_intraday_fallback(stock_code, fallback_points)
        self._last_intraday_source = "akshare_intraday_em_fallback"
        logger.warning(
            "Using validated intraday fallback for %s due to primary failure: %s",
            stock_code,
            primary_error.message,
        )
        return validated_fallback

    def get_last_intraday_source(self) -> str | None:
        """返回最近一次分时数据读取所使用的数据源。"""
        return self._last_intraday_source

    def calculate_daily_returns(
        self, stock_code: str, start_date: date, end_date: date
    ) -> dict[date, float]:
        """
        计算股票的日收益率

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}，收益率以小数表示（如 0.01 表示 1%）
        """
        prices = self.get_daily_prices(stock_code, start_date, end_date)

        returns = {}
        for i in range(1, len(prices)):
            prev_date, prev_price = prices[i - 1]
            curr_date, curr_price = prices[i]

            if prev_price > 0:
                daily_return = float((curr_price - prev_price) / prev_price)
                returns[curr_date] = daily_return

        return returns

    def _get_intraday_hist_min_points(
        self,
        stock_code: str,
        symbol: str,
    ) -> list[IntradayPricePoint]:
        try:
            ak = get_akshare_module()
            import pandas as pd

            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period="1", adjust="")
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 主分时接口获取失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_hist_min_em"},
            ) from exc

        try:
            if frame is None or frame.empty:
                return []

            frame = frame.copy()
            frame["时间"] = pd.to_datetime(frame["时间"], errors="coerce")
            frame = frame.dropna(subset=["时间"]).sort_values("时间")
            if frame.empty:
                return []

            latest_session = frame["时间"].dt.date.max()
            frame = frame[frame["时间"].dt.date == latest_session]

            points: list[IntradayPricePoint] = []
            for _, row in frame.iterrows():
                price = self._safe_decimal(row.get("收盘"))
                if price is None or price <= 0:
                    continue
                points.append(
                    IntradayPricePoint(
                        stock_code=stock_code,
                        timestamp=self._to_market_aware_datetime(row["时间"]),
                        price=price,
                        avg_price=self._safe_decimal(row.get("均价")),
                        volume=self._safe_int(row.get("成交量")),
                    )
                )
            return points
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 主分时接口解析失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_hist_min_em"},
            ) from exc

    def _get_intraday_tick_points(
        self,
        stock_code: str,
        symbol: str,
    ) -> list[IntradayPricePoint]:
        try:
            ak = get_akshare_module()
            import pandas as pd

            frame = ak.stock_intraday_em(symbol=symbol)
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 备用分时接口获取失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_intraday_em"},
            ) from exc

        try:
            if frame is None or frame.empty:
                return []

            frame = frame.copy()
            frame["时间"] = pd.to_datetime(
                date.today().isoformat() + " " + frame["时间"].astype(str),
                errors="coerce",
            )
            frame["成交价"] = pd.to_numeric(frame["成交价"], errors="coerce")
            frame["手数"] = pd.to_numeric(frame["手数"], errors="coerce").fillna(0)
            frame = frame.dropna(subset=["时间", "成交价"]).sort_values("时间")
            if frame.empty:
                return []

            frame["minute"] = frame["时间"].dt.floor("min")

            points: list[IntradayPricePoint] = []
            for minute, bucket in frame.groupby("minute"):
                last_row = bucket.iloc[-1]
                shares = bucket["手数"] * 100
                total_shares = int(shares.sum()) if not shares.empty else 0
                weighted_amount = float((bucket["成交价"] * shares).sum()) if total_shares else 0.0
                avg_price = (
                    self._safe_decimal(weighted_amount / total_shares) if total_shares > 0 else None
                )
                price = self._safe_decimal(last_row.get("成交价"))
                if price is None or price <= 0:
                    continue
                points.append(
                    IntradayPricePoint(
                        stock_code=stock_code,
                        timestamp=self._to_market_aware_datetime(minute),
                        price=price,
                        avg_price=avg_price,
                        volume=total_shares or None,
                    )
                )
            return points
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 备用分时接口解析失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_intraday_em"},
            ) from exc

    def _to_akshare_symbol(self, stock_code: str) -> str:
        return stock_code.split(".")[0] if "." in stock_code else stock_code

    def _to_market_aware_datetime(self, value: object) -> datetime:
        """将分时数据时间转换为 Asia/Shanghai 的 timezone-aware datetime。"""
        if hasattr(value, "to_pydatetime"):
            dt_value = value.to_pydatetime()
        elif isinstance(value, datetime):
            dt_value = value
        else:
            raise DataValidationError(f"无法解析分时时间: {value!r}")

        market_tz = ZoneInfo("Asia/Shanghai")
        if timezone.is_naive(dt_value):
            return timezone.make_aware(dt_value, market_tz)
        return dt_value.astimezone(market_tz)

    def _validate_intraday_points(
        self,
        points: list[IntradayPricePoint],
        source_name: str,
    ) -> list[IntradayPricePoint]:
        """校验分时点序列的基础数据质量。"""
        if not points:
            return []

        session_date = points[0].timestamp.date()
        previous_timestamp: datetime | None = None

        for point in points:
            if timezone.is_naive(point.timestamp):
                raise DataValidationError(f"{source_name} 返回了 naive datetime")
            if point.timestamp.date() != session_date:
                raise DataValidationError(f"{source_name} 返回了跨交易日分时数据")
            if previous_timestamp is not None and point.timestamp < previous_timestamp:
                raise DataValidationError(f"{source_name} 返回的分时数据未按时间升序排列")
            if point.price <= 0:
                raise DataValidationError(f"{source_name} 返回了非正价格")
            if point.avg_price is not None and point.avg_price <= 0:
                raise DataValidationError(f"{source_name} 返回了非正均价")
            if point.volume is not None and point.volume < 0:
                raise DataValidationError(f"{source_name} 返回了负成交量")
            previous_timestamp = point.timestamp

        return points

    def _validate_intraday_fallback(
        self,
        stock_code: str,
        fallback_points: list[IntradayPricePoint],
    ) -> list[IntradayPricePoint]:
        """在切换到备用分时源前执行一致性校验。"""
        validated_points = self._validate_intraday_points(
            fallback_points,
            "akshare_intraday_em",
        )
        validation_price = self._get_intraday_validation_price(stock_code)
        if validation_price is None or validation_price <= 0:
            raise DataFetchError(
                message=f"{stock_code} 备用分时数据缺少校验基准，拒绝切换",
                details={"stock_code": stock_code, "fallback_source": "akshare_intraday_em"},
            )

        latest_price = validated_points[-1].price
        deviation = abs((latest_price - validation_price) / validation_price)
        if deviation > Decimal("0.01"):
            logger.warning(
                "Rejected intraday fallback for %s due to %.2f%% deviation against validation price",
                stock_code,
                float(deviation * Decimal("100")),
            )
            raise DataValidationError(
                f"{stock_code} 备用分时数据校验失败，偏差 {float(deviation * Decimal('100')):.2f}%"
            )
        return validated_points

    def _get_intraday_validation_price(self, stock_code: str) -> Decimal | None:
        """获取切换备用分时源前的一致性校验价格。"""
        try:
            from apps.realtime.infrastructure.repositories import (
                AKSharePriceDataProvider,
                RedisRealtimePriceRepository,
            )

            cached_price = RedisRealtimePriceRepository().get_latest_price(stock_code)
            if cached_price is not None:
                cached_decimal = self._safe_decimal(cached_price.price)
                if cached_decimal is not None and cached_decimal > 0:
                    return cached_decimal

            realtime_price = AKSharePriceDataProvider().get_realtime_price(stock_code)
            if realtime_price is None:
                return None

            realtime_decimal = self._safe_decimal(realtime_price.price)
            if realtime_decimal is not None and realtime_decimal > 0:
                return realtime_decimal
        except Exception as exc:
            logger.warning("Failed to get intraday validation price for %s: %s", stock_code, exc)

        return None

    def _get_remote_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """在数据中台价格事实缺失时，通过数据中台 Gateway 拉取只读日线价格。"""
        tushare_gateway_prices = self._get_tushare_gateway_daily_prices(
            stock_code,
            start_date,
            end_date,
        )
        if tushare_gateway_prices:
            return tushare_gateway_prices

        akshare_gateway_bars = self._get_akshare_gateway_historical_bars(
            stock_code,
            start_date,
            end_date,
        )
        self._cache_remote_historical_bars(stock_code, akshare_gateway_bars)
        return self._bars_to_daily_prices(akshare_gateway_bars)

    def _get_remote_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """在数据中台价格事实缺失时，通过数据中台 Gateway 拉取历史 K 线。"""
        tushare_bars = self._get_tushare_gateway_historical_bars(
            stock_code,
            start_date,
            end_date,
        )
        if tushare_bars:
            return tushare_bars

        return self._get_akshare_gateway_historical_bars(stock_code, start_date, end_date)

    def _bars_to_daily_prices(self, bars: list) -> list[tuple[date, Decimal]]:
        prices: list[tuple[date, Decimal]] = []
        for bar in bars:
            trade_date = getattr(bar, "trade_date", None)
            close_price = self._safe_decimal(getattr(bar, "close", None))
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            prices.append((trade_date, close_price))
        return prices

    def _price_bars_to_technical_bars(
        self,
        stock_code: str,
        bars: list,
    ) -> list[TechnicalBar]:
        return self._recalculate_technical_bars(
            [
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=bar.bar_date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=bar.volume or 0,
                    amount=self._safe_decimal(bar.amount) or Decimal("0"),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                for bar in sorted(bars, key=lambda item: item.bar_date)
            ]
        )

    def _recalculate_technical_bars(
        self,
        bars: list[TechnicalBar],
    ) -> list[TechnicalBar]:
        recalculated: list[TechnicalBar] = []
        closes: list[Decimal] = []
        ema12: float | None = None
        ema26: float | None = None
        signal_ema: float | None = None
        alpha12 = 2 / 13
        alpha26 = 2 / 27
        alpha9 = 2 / 10

        for bar in sorted(bars, key=lambda item: item.trade_date):
            closes.append(bar.close)
            close_float = float(bar.close)
            ema12 = close_float if ema12 is None else ema12 + (close_float - ema12) * alpha12
            ema26 = close_float if ema26 is None else ema26 + (close_float - ema26) * alpha26
            macd = ema12 - ema26
            signal_ema = macd if signal_ema is None else signal_ema + (macd - signal_ema) * alpha9

            recalculated.append(
                TechnicalBar(
                    stock_code=bar.stock_code,
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    amount=bar.amount,
                    ma5=self._calculate_sma(closes, 5),
                    ma20=self._calculate_sma(closes, 20),
                    ma60=self._calculate_sma(closes, 60),
                    macd=macd,
                    macd_signal=signal_ema,
                    macd_hist=macd - signal_ema,
                    rsi=None,
                )
            )
        return recalculated

    def _calculate_sma(self, closes: list[Decimal], window: int) -> Decimal | None:
        if len(closes) < window:
            return None
        return sum(closes[-window:]) / Decimal(window)

    def _get_tushare_gateway_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """通过 Tushare Gateway 获取真实远端日线价格。"""
        bars = self._get_tushare_gateway_historical_bars(stock_code, start_date, end_date)
        self._cache_remote_historical_bars(stock_code, bars)

        remote_prices: list[tuple[date, Decimal]] = []
        for bar in bars:
            close_price = self._safe_decimal(getattr(bar, "close", None))
            if close_price is None or close_price <= 0:
                continue
            remote_prices.append((bar.trade_date, close_price))
        return remote_prices

    def _get_tushare_gateway_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """通过 Data Center 的 Tushare Gateway 获取历史 K 线。"""
        try:
            from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

            return TushareGateway().get_historical_prices(
                asset_code=stock_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch Tushare gateway historical bars for %s: %s",
                stock_code,
                exc,
            )
            return []

    def _cache_remote_historical_bars(self, stock_code: str, bars: list) -> None:
        """将远端历史 K 线幂等写入本地日线表，作为 read-through cache。"""
        if not bars:
            return

        try:
            for bar in bars:
                trade_date = getattr(bar, "trade_date", None)
                open_price = self._safe_decimal(getattr(bar, "open", None))
                high_price = self._safe_decimal(getattr(bar, "high", None))
                low_price = self._safe_decimal(getattr(bar, "low", None))
                close_price = self._safe_decimal(getattr(bar, "close", None))
                amount = self._safe_decimal(getattr(bar, "amount", None)) or Decimal("0")

                if (
                    not isinstance(trade_date, date)
                    or open_price is None
                    or open_price <= 0
                    or high_price is None
                    or high_price <= 0
                    or low_price is None
                    or low_price <= 0
                    or close_price is None
                    or close_price <= 0
                ):
                    continue

                StockDailyModel._default_manager.update_or_create(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    defaults={
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": getattr(bar, "volume", None) or 0,
                        "amount": amount,
                        "turnover_rate": getattr(bar, "turnover_rate", None),
                        "adj_factor": getattr(bar, "adj_factor", 1.0) or 1.0,
                    },
                )
        except Exception as exc:
            logger.warning(
                "Failed to cache remote historical bars for %s: %s",
                stock_code,
                exc,
            )

    def _get_akshare_gateway_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """通过 AKShare EastMoney Gateway 获取历史 K 线。"""
        try:
            from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
                AKShareEastMoneyGateway,
            )

            return AKShareEastMoneyGateway().get_historical_prices(
                asset_code=stock_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch AKShare gateway historical bars for %s: %s",
                stock_code,
                exc,
            )
            return []

    def _get_tushare_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """从 Tushare 获取远端日线价格。"""
        try:
            frame = TushareStockAdapter().fetch_daily_data(stock_code, start_date, end_date)
        except Exception as exc:
            logger.warning(
                "Failed to fetch Tushare daily prices for %s: %s",
                stock_code,
                exc,
            )
            return []

        if frame is None or frame.empty:
            return []

        remote_prices: list[tuple[date, Decimal]] = []
        for _, row in frame.iterrows():
            trade_date = row.get("trade_date")
            close_price = self._safe_decimal(row.get("close"))
            if hasattr(trade_date, "date"):
                trade_date = trade_date.date()
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            remote_prices.append((trade_date, close_price))

        return remote_prices

    def _get_akshare_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """从 AKShare 获取远端日线价格。"""
        try:
            ak = get_akshare_module()

            frame = ak.stock_zh_a_hist(
                symbol=self._to_akshare_symbol(stock_code),
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch AKShare daily prices for %s: %s",
                stock_code,
                exc,
            )
            return []

        if frame is None or frame.empty:
            return []

        remote_prices: list[tuple[date, Decimal]] = []
        for _, row in frame.iterrows():
            trade_date = row.get("日期")
            close_price = self._safe_decimal(row.get("收盘"))
            if hasattr(trade_date, "date"):
                trade_date = trade_date.date()
            elif isinstance(trade_date, str):
                try:
                    trade_date = datetime.fromisoformat(trade_date).date()
                except ValueError:
                    continue
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            remote_prices.append((trade_date, close_price))

        return remote_prices

    def _safe_decimal(self, value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            decimal_value = Decimal(str(value))
            return None if decimal_value != decimal_value else decimal_value
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _build_stock_code_candidates(self, stock_code: str) -> list[str]:
        normalized = stock_code.strip().upper()
        if not normalized:
            return []

        candidates = [normalized]
        base_code = normalized.split(".", 1)[0]
        if base_code != normalized:
            candidates.append(base_code)
        else:
            market = self._infer_market_from_stock_code(normalized)
            if market:
                candidates.append(f"{base_code}.{market}")

        result: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in result:
                result.append(candidate)
        return result

    def _get_stock_info_from_data_center(self, stock_code: str) -> StockInfo | None:
        asset = self._dc_asset_repo.get_by_code(stock_code)
        if asset is None:
            return None

        market_map = {
            "SSE": "SH",
            "SZSE": "SZ",
            "BSE": "BJ",
        }
        market = market_map.get(
            asset.exchange.value, self._infer_market_from_stock_code(asset.code)
        )
        return StockInfo(
            stock_code=asset.code,
            name=asset.short_name or asset.name,
            sector=asset.sector or asset.industry or "",
            market=market,
            list_date=asset.list_date,
        )

    def _get_minimal_stock_info_from_data_center(self, stock_code: str) -> StockInfo | None:
        candidate_code = None

        latest_quote = self._dc_quote_repo.get_latest(stock_code)
        if latest_quote is not None:
            candidate_code = latest_quote.asset_code
        else:
            latest_bar = self._dc_price_bar_repo.get_latest(stock_code)
            if latest_bar is not None:
                candidate_code = latest_bar.asset_code
            else:
                latest_valuation = self._dc_valuation_repo.get_latest(stock_code)
                if latest_valuation is not None:
                    candidate_code = latest_valuation.asset_code
                else:
                    latest_financial = self._dc_financial_repo.get_latest(stock_code)
                    if latest_financial is not None:
                        candidate_code = latest_financial.asset_code

        if candidate_code is None:
            return None

        return StockInfo(
            stock_code=candidate_code,
            name=candidate_code,
            sector="",
            market=self._infer_market_from_stock_code(candidate_code),
            list_date=None,
        )

    def _get_stock_info_from_eastmoney(self, stock_code: str) -> StockInfo | None:
        params = {
            "secid": self._to_eastmoney_secid(stock_code),
            "fields": self._EASTMONEY_METADATA_FIELDS,
            "invt": "2",
            "fltt": "1",
        }
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.headers.update(
                    {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/133.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json,text/plain,*/*",
                        "Referer": "https://quote.eastmoney.com/",
                    }
                )
                response = session.get(
                    self._EASTMONEY_QUOTE_URL,
                    params=params,
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("Failed to fetch remote stock info for %s: %s", stock_code, exc)
            return None

        data = payload.get("data") or {}
        raw_price = data.get("f43")
        if raw_price in (None, "", "-"):
            return None

        remote_name = str(data.get("f58") or "").strip() or stock_code
        return StockInfo(
            stock_code=stock_code,
            name=remote_name,
            sector="",
            market=self._infer_market_from_stock_code(stock_code),
            list_date=None,
        )

    def _infer_market_from_stock_code(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        if code.endswith(".SH"):
            return "SH"
        if code.endswith(".SZ"):
            return "SZ"
        if code.endswith(".BJ"):
            return "BJ"
        if code.startswith("6"):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return ""

    def _to_eastmoney_secid(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        symbol = code.split(".")[0]
        market = self._infer_market_from_stock_code(code)
        if market == "SH":
            return f"1.{symbol}"
        return f"0.{symbol}"

    def _safe_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def get_latest_financial_data(self, stock_code: str) -> FinancialData | None:
        """
        获取股票最新的财务数据

        Args:
            stock_code: 股票代码

        Returns:
            FinancialData 或 None
        """
        return self._get_latest_financial(stock_code)

    def get_stock_count_by_sector(self, sector: str) -> int:
        """
        获取指定行业的股票数量

        Args:
            sector: 行业名称

        Returns:
            股票数量
        """
        return StockInfoModel._default_manager.filter(sector=sector, is_active=True).count()

    def get_all_sectors(self) -> list[str]:
        """
        获取所有行业列表

        Returns:
            行业名称列表
        """
        sectors = (
            StockInfoModel._default_manager.filter(is_active=True)
            .values_list("sector", flat=True)
            .distinct()
        )

        return list(sectors)

    def list_active_stock_codes(
        self,
        limit: int | None = None,
        stock_codes: list[str] | None = None,
    ) -> list[str]:
        """
        获取所有活跃股票代码列表

        用于批量扫描等场景，避免构造完整实体。

        Args:
            limit: 数量限制（可选）
            stock_codes: 指定股票代码列表（可选）

        Returns:
            股票代码列表
        """
        queryset = StockInfoModel._default_manager.filter(is_active=True)

        if stock_codes:
            normalized_codes = [str(code).strip().upper() for code in stock_codes if code]
            queryset = queryset.filter(stock_code__in=normalized_codes)

        queryset = queryset.values_list("stock_code", flat=True).order_by("stock_code")

        if limit:
            queryset = queryset[:limit]

        return list(queryset)

    def get_latest_valuation_date(self) -> date | None:
        """获取最新估值日期。"""
        latest = (
            ValuationModel._default_manager.order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        return latest

    def get_valuation_models_by_date(self, as_of_date: date) -> list[ValuationModel]:
        """获取指定日期的原始估值模型记录。"""
        return list(
            ValuationModel._default_manager.filter(trade_date=as_of_date).order_by("stock_code")
        )


class ScoringWeightConfigRepository:
    """股票评分权重配置仓储"""

    def get_active_config(self):
        """
        获取当前启用的评分权重配置

        Returns:
            ScoringWeightConfig 实体，如果没有启用配置则返回默认配置
        """
        from .models import ScoringWeightConfigModel

        try:
            model = ScoringWeightConfigModel._default_manager.filter(is_active=True).first()

            if model:
                return model.to_domain_entity()

            # 没有启用配置时返回默认配置
            return self._get_default_config()

        except Exception:
            # 发生错误时返回默认配置
            return self._get_default_config()

    def get_config_by_name(self, name: str):
        """
        根据名称获取评分权重配置

        Args:
            name: 配置名称

        Returns:
            ScoringWeightConfig 实体，不存在则返回 None
        """
        from .models import ScoringWeightConfigModel

        try:
            model = ScoringWeightConfigModel._default_manager.filter(name=name).first()

            if model:
                return model.to_domain_entity()

            return None

        except Exception:
            return None

    def get_all_configs(self):
        """
        获取所有评分权重配置

        Returns:
            ScoringWeightConfig 实体列表
        """
        from .models import ScoringWeightConfigModel

        try:
            models = ScoringWeightConfigModel._default_manager.all().order_by(
                "-is_active", "-created_at"
            )
            return [m.to_domain_entity() for m in models]
        except Exception:
            return []

    def save_config(self, config_entity):
        """
        保存评分权重配置

        Args:
            config_entity: ScoringWeightConfig 实体
        """
        from .models import ScoringWeightConfigModel

        ScoringWeightConfigModel._default_manager.update_or_create(
            name=config_entity.name,
            defaults={
                "description": config_entity.description,
                "is_active": config_entity.is_active,
                "growth_weight": config_entity.growth_weight,
                "profitability_weight": config_entity.profitability_weight,
                "valuation_weight": config_entity.valuation_weight,
                "revenue_growth_weight": config_entity.revenue_growth_weight,
                "profit_growth_weight": config_entity.profit_growth_weight,
            },
        )

    def _get_default_config(self):
        """
        获取默认评分权重配置

        当数据库中没有配置或配置加载失败时使用此默认值。
        """
        from apps.equity.domain.entities import ScoringWeightConfig

        return ScoringWeightConfig(
            name="默认配置",
            description="系统默认评分权重配置（当数据库配置不可用时使用）",
            is_active=True,
            growth_weight=0.4,
            profitability_weight=0.4,
            valuation_weight=0.2,
            revenue_growth_weight=0.5,
            profit_growth_weight=0.5,
        )


class DjangoValuationRepairRepository:
    """Django ORM 估值修复仓储"""

    def upsert_snapshot(self, status, source_universe: str = "all_active") -> None:
        """
        保存或更新估值修复快照

        Args:
            status: ValuationRepairStatus 实体
            source_universe: 来源股票池
        """
        from .models import ValuationRepairTrackingModel

        ValuationRepairTrackingModel._default_manager.update_or_create(
            stock_code=status.stock_code,
            source_universe=source_universe,
            defaults={
                "stock_name": status.stock_name,
                "as_of_date": status.as_of_date,
                "repair_start_date": status.repair_start_date,
                "repair_start_percentile": status.repair_start_percentile,
                "current_phase": status.phase,
                "signal": status.signal,
                "composite_percentile": status.composite_percentile,
                "pe_percentile": status.pe_percentile,
                "pb_percentile": status.pb_percentile,
                "repair_progress": status.repair_progress,
                "repair_speed_per_30d": status.repair_speed_per_30d,
                "estimated_days_to_target": status.estimated_days_to_target,
                "is_stalled": status.is_stalled,
                "stall_start_date": status.stall_start_date,
                "stall_duration_trading_days": status.stall_duration_trading_days,
                "repair_duration_trading_days": status.repair_duration_trading_days,
                "lowest_percentile": status.lowest_percentile,
                "lowest_percentile_date": status.lowest_percentile_date,
                "target_percentile": status.target_percentile,
                "composite_method": status.composite_method,
                "confidence": status.confidence,
                "is_active": True,
            },
        )

    def deactivate_snapshot(self, stock_code: str, source_universe: str = "all_active") -> None:
        """
        停用估值修复快照

        Args:
            stock_code: 股票代码
            source_universe: 来源股票池
        """
        from .models import ValuationRepairTrackingModel

        ValuationRepairTrackingModel._default_manager.filter(
            stock_code=stock_code, source_universe=source_universe
        ).update(is_active=False)

    def list_active_snapshots(
        self, source_universe: str = "all_active", phase: str | None = None, limit: int = 50
    ) -> list:
        """
        列出活跃的估值修复快照

        Args:
            source_universe: 来源股票池
            phase: 阶段过滤（可选）
            limit: 数量限制

        Returns:
            ORM Model 列表
        """
        from .models import ValuationRepairTrackingModel

        queryset = ValuationRepairTrackingModel._default_manager.filter(
            source_universe=source_universe, is_active=True
        )

        if phase:
            queryset = queryset.filter(current_phase=phase)

        return list(queryset.order_by("-composite_percentile")[:limit])

    def get_snapshot(self, stock_code: str, source_universe: str = "all_active") -> object | None:
        """
        获取单只股票的估值修复快照

        Args:
            stock_code: 股票代码
            source_universe: 来源股票池

        Returns:
            ORM Model 或 None
        """
        from .models import ValuationRepairTrackingModel

        try:
            return ValuationRepairTrackingModel._default_manager.get(
                stock_code=stock_code, source_universe=source_universe, is_active=True
            )
        except ValuationRepairTrackingModel.DoesNotExist:
            return None

    def get_snapshot_map(self, stock_codes: list[str]) -> dict[str, dict]:
        """批量获取估值修复快照映射。"""
        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        from .models import ValuationRepairTrackingModel

        rows = ValuationRepairTrackingModel._default_manager.filter(
            stock_code__in=normalized_codes,
            is_active=True,
        ).values(
            "stock_code",
            "current_phase",
            "signal",
            "composite_percentile",
            "repair_progress",
            "repair_speed_per_30d",
            "estimated_days_to_target",
            "confidence",
            "as_of_date",
            "is_stalled",
        )
        return {
            str(row["stock_code"]).upper(): {
                "phase": row.get("current_phase"),
                "signal": row.get("signal"),
                "composite_percentile": row.get("composite_percentile"),
                "repair_progress": row.get("repair_progress"),
                "repair_speed_per_30d": row.get("repair_speed_per_30d"),
                "estimated_days_to_target": row.get("estimated_days_to_target"),
                "confidence": row.get("confidence"),
                "is_stalled": row.get("is_stalled"),
                "as_of_date": row["as_of_date"].isoformat() if row.get("as_of_date") else None,
            }
            for row in rows
        }


class DjangoValuationDataQualityRepository:
    """估值数据质量快照仓储"""

    def upsert_snapshot(self, snapshot: dict) -> None:
        ValuationDataQualitySnapshotModel._default_manager.update_or_create(
            as_of_date=snapshot["as_of_date"],
            defaults=snapshot,
        )

    def get_snapshot(self, as_of_date: date) -> ValuationDataQualitySnapshotModel | None:
        try:
            return ValuationDataQualitySnapshotModel._default_manager.get(as_of_date=as_of_date)
        except ValuationDataQualitySnapshotModel.DoesNotExist:
            return None

    def get_latest_snapshot(self) -> ValuationDataQualitySnapshotModel | None:
        return ValuationDataQualitySnapshotModel._default_manager.order_by("-as_of_date").first()

    def get_latest_gate_passed_snapshot(self) -> ValuationDataQualitySnapshotModel | None:
        return (
            ValuationDataQualitySnapshotModel._default_manager.filter(is_gate_passed=True)
            .order_by("-as_of_date")
            .first()
        )


class ValuationRepairConfigRepository:
    """估值修复配置仓储。"""

    def get_queryset(self):
        """Return the config queryset ordered for admin/API use."""

        from .models import ValuationRepairConfigModel

        return ValuationRepairConfigModel._default_manager.all().order_by(
            "-is_active",
            "-version",
            "-created_at",
        )

    def get_active_model(self):
        """Return the active config model if present."""

        return self.get_queryset().filter(is_active=True).first()

    def get_active_domain_config(self):
        """Return the active config as a domain config object if present."""
        model = self.get_active_model()
        return model.to_domain_config() if model else None

    def get_active_version(self) -> int:
        """Return the active config version, or 0 if missing."""
        model = self.get_active_model()
        return int(getattr(model, "version", 0) or 0)

    def list_models(self) -> list:
        """Return all config models for interface/application consumers."""

        return list(self.get_queryset())

    def get_by_id(self, config_id: int):
        """Return one config model by primary key, if present."""

        return self.get_queryset().filter(pk=config_id).first()

    def create(self, *, data: dict, created_by: str):
        """Create one config model."""

        from .models import ValuationRepairConfigModel

        model = ValuationRepairConfigModel(
            **data,
            created_by=created_by,
        )
        model.save()
        return model

    def update(self, *, config_id: int, data: dict):
        """Update one config model and return the refreshed instance."""

        model = self.get_by_id(config_id)
        if model is None:
            return None

        for field_name, value in data.items():
            setattr(model, field_name, value)
        model.save()
        return model

    def activate(self, *, config_id: int):
        """Activate one config model and return the refreshed instance."""

        model = self.get_by_id(config_id)
        if model is None:
            return None

        model.is_active = True
        model.effective_from = timezone.now()
        model.save()
        return model

    def delete(self, *, config_id: int) -> bool:
        """Delete one config model if present."""

        model = self.get_by_id(config_id)
        if model is None:
            return False

        model.delete()
        return True


class EquityBootstrapConfigRepository:
    """Persistence helpers for equity bootstrap configuration commands."""

    def upsert_stock_screening_rule(self, rule_data: dict[str, Any]) -> None:
        """Create or update one stock screening rule row."""

        from shared.infrastructure.models import StockScreeningRuleConfigModel

        StockScreeningRuleConfigModel._default_manager.update_or_create(
            regime=rule_data["regime"],
            rule_name=rule_data["rule_name"],
            defaults=rule_data,
        )

    def upsert_sector_preference(self, preference: dict[str, Any]) -> None:
        """Create or update one sector preference row."""

        from shared.infrastructure.models import SectorPreferenceConfigModel

        SectorPreferenceConfigModel._default_manager.update_or_create(
            regime=preference["regime"],
            sector_name=preference["sector_name"],
            defaults=preference,
        )

    def upsert_fund_type_preference(self, preference: dict[str, Any]) -> None:
        """Create or update one fund-type preference row."""

        from shared.infrastructure.models import FundTypePreferenceConfigModel

        FundTypePreferenceConfigModel._default_manager.update_or_create(
            regime=preference["regime"],
            fund_type=preference["fund_type"],
            style=preference["style"],
            defaults=preference,
        )


def compute_valuation_quality_flag(
    pb: float | None,
    pe: float | None,
    previous_pb: float | None = None,
    previous_pe: float | None = None,
) -> tuple[bool, str, str]:
    """根据估值字段计算基础质量标记。"""
    if pb is None:
        return False, "missing_pb", "PB is missing"
    if pb <= 0:
        return False, "invalid_pb", "PB must be greater than 0"
    if pe is None:
        return True, "missing_pe", "PE is missing"

    if previous_pb and previous_pb > 0:
        pb_jump = abs(pb - previous_pb) / previous_pb
        if pb_jump > 0.60:
            return True, "jump_alert", f"PB jump={pb_jump:.2f}"

    if previous_pe and previous_pe > 0:
        pe_jump = abs(pe - previous_pe) / previous_pe
        if pe_jump > 0.80:
            return True, "jump_alert", f"PE jump={pe_jump:.2f}"

    return True, "ok", ""


def build_quality_snapshot(
    as_of_date: date,
    expected_stock_count: int,
    valuations: list[ValuationModel],
    primary_source: str = "akshare",
) -> dict:
    """根据指定日期估值记录构建质量快照。"""
    synced_stock_count = len(valuations)
    valid_stock_count = sum(1 for item in valuations if item.is_valid)
    missing_pb_count = sum(1 for item in valuations if item.quality_flag == "missing_pb")
    invalid_pb_count = sum(1 for item in valuations if item.quality_flag == "invalid_pb")
    missing_pe_count = sum(1 for item in valuations if item.quality_flag == "missing_pe")
    jump_alert_count = sum(1 for item in valuations if item.quality_flag == "jump_alert")
    source_deviation_count = sum(
        1 for item in valuations if item.quality_flag == "source_deviation"
    )
    fallback_used_count = sum(1 for item in valuations if item.source_provider != primary_source)

    coverage_ratio = (synced_stock_count / expected_stock_count) if expected_stock_count else 0.0
    valid_ratio = (valid_stock_count / synced_stock_count) if synced_stock_count else 0.0

    gate_reasons = []
    if coverage_ratio < 0.95:
        gate_reasons.append("coverage<0.95")
    if valid_ratio < 0.90:
        gate_reasons.append("valid<0.90")
    if invalid_pb_count > 0:
        gate_reasons.append("invalid_pb")
    if synced_stock_count:
        if jump_alert_count / synced_stock_count > 0.03:
            gate_reasons.append("jump_alert_ratio>0.03")
        if source_deviation_count / synced_stock_count > 0.05:
            gate_reasons.append("source_deviation_ratio>0.05")

    return {
        "as_of_date": as_of_date,
        "expected_stock_count": expected_stock_count,
        "synced_stock_count": synced_stock_count,
        "valid_stock_count": valid_stock_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "valid_ratio": round(valid_ratio, 4),
        "missing_pb_count": missing_pb_count,
        "invalid_pb_count": invalid_pb_count,
        "missing_pe_count": missing_pe_count,
        "jump_alert_count": jump_alert_count,
        "source_deviation_count": source_deviation_count,
        "primary_source": primary_source,
        "fallback_used_count": fallback_used_count,
        "is_gate_passed": not gate_reasons,
        "gate_reason": ", ".join(gate_reasons),
    }
