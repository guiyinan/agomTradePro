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
from zoneinfo import ZoneInfo

from django.db import models
from django.utils import timezone

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

    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict,
        max_count: int = 100
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
            valuation = ValuationModel._default_manager.filter(
                stock_code=stock_code
            ).order_by('-trade_date').first()

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
            financial = FinancialDataModel._default_manager.filter(
                stock_code=stock_code
            ).order_by('-report_date').first()

            # 获取最新技术指标（从日线数据）
            daily = StockDailyModel._default_manager.filter(
                stock_code=stock_code
            ).order_by('-trade_date').first()

            # 构建 EquityAssetScore
            stock_info = StockInfo(
                stock_code=stock_model.stock_code,
                name=stock_model.name,
                sector=stock_model.sector,
                market=stock_model.market,
                list_date=stock_model.list_date
            )

            valuation_entity = ValuationMetrics(
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
            ) if valuation else None

            financial_entity = FinancialData(
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
                debt_ratio=financial.debt_ratio
            ) if financial else None

            technical_entity = TechnicalIndicators(
                stock_code=daily.stock_code,
                trade_date=daily.trade_date,
                close=daily.close,
                ma5=daily.ma5,
                ma20=daily.ma20,
                ma60=daily.ma60,
                macd=daily.macd,
                macd_signal=daily.macd_signal,
                macd_hist=daily.macd_hist,
                rsi=daily.rsi
            ) if daily else None

            asset_score = EquityAssetScore.from_stock_info(
                stock_info,
                valuation_entity,
                financial_entity,
                technical_entity
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
            stock_model = StockInfoModel._default_manager.get(
                stock_code=asset_code,
                is_active=True
            )

            stock_info = StockInfo(
                stock_code=stock_model.stock_code,
                name=stock_model.name,
                sector=stock_model.sector,
                market=stock_model.market,
                list_date=stock_model.list_date
            )

            # 获取最新估值数据
            valuation_model = ValuationModel._default_manager.filter(
                stock_code=asset_code
            ).order_by('-trade_date').first()

            valuation = ValuationMetrics(
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
            ) if valuation_model else None

            # 获取最新财务数据
            financial_model = FinancialDataModel._default_manager.filter(
                stock_code=asset_code
            ).order_by('-report_date').first()

            financial = FinancialData(
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
                debt_ratio=financial_model.debt_ratio
            ) if financial_model else None

            # 获取最新技术指标
            daily_model = StockDailyModel._default_manager.filter(
                stock_code=asset_code
            ).order_by('-trade_date').first()

            technical = TechnicalIndicators(
                stock_code=daily_model.stock_code,
                trade_date=daily_model.trade_date,
                close=daily_model.close,
                ma5=daily_model.ma5,
                ma20=daily_model.ma20,
                ma60=daily_model.ma60,
                macd=daily_model.macd,
                macd_signal=daily_model.macd_signal,
                macd_hist=daily_model.macd_hist,
                rsi=daily_model.rsi
            ) if daily_model else None

            return EquityAssetScore.from_stock_info(
                stock_info,
                valuation,
                financial,
                technical
            )

        except StockInfoModel.DoesNotExist:
            return None


class DjangoStockRepository:
    """Django ORM 个股数据仓储"""

    def __init__(self) -> None:
        self._last_intraday_source: str | None = None

    def get_all_stocks_with_fundamentals(
        self,
        as_of_date: date | None = None
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
                list_date=stock_info_model.list_date
            )

            # 获取最新财务数据
            financial_query = FinancialDataModel._default_manager.filter(
                stock_code=stock_code
            ).order_by('-report_date').first()

            if not financial_query:
                # 没有财务数据，跳过
                continue

            financial = FinancialData(
                stock_code=financial_query.stock_code,
                report_date=financial_query.report_date,
                revenue=financial_query.revenue,
                net_profit=financial_query.net_profit,
                revenue_growth=financial_query.revenue_growth or 0.0,
                net_profit_growth=financial_query.net_profit_growth or 0.0,
                total_assets=financial_query.total_assets,
                total_liabilities=financial_query.total_liabilities,
                equity=financial_query.equity,
                roe=financial_query.roe,
                roa=financial_query.roa or 0.0,
                debt_ratio=financial_query.debt_ratio
            )

            # 获取最新估值数据
            valuation_query = ValuationModel._default_manager.filter(
                stock_code=stock_code
            ).order_by('-trade_date').first()

            if not valuation_query:
                # 没有估值数据，跳过
                continue

            valuation = ValuationMetrics(
                stock_code=valuation_query.stock_code,
                trade_date=valuation_query.trade_date,
                pe=valuation_query.pe or 0.0,
                pb=valuation_query.pb or 0.0,
                ps=valuation_query.ps or 0.0,
                total_mv=valuation_query.total_mv,
                circ_mv=valuation_query.circ_mv,
                dividend_yield=valuation_query.dividend_yield or 0.0,
                source_provider=valuation_query.source_provider,
                source_updated_at=valuation_query.source_updated_at,
                fetched_at=valuation_query.fetched_at,
                pe_type=valuation_query.pe_type,
                is_valid=valuation_query.is_valid,
                quality_flag=valuation_query.quality_flag,
                quality_notes=valuation_query.quality_notes,
                raw_payload_hash=valuation_query.raw_payload_hash,
            )

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
        try:
            model = StockInfoModel._default_manager.get(stock_code=stock_code)
            return StockInfo(
                stock_code=model.stock_code,
                name=model.name,
                sector=model.sector,
                market=model.market,
                list_date=model.list_date
            )
        except StockInfoModel.DoesNotExist:
            return None

    def get_financial_data(
        self,
        stock_code: str,
        limit: int = 4
    ) -> list[FinancialData]:
        """
        获取股票的财务数据

        Args:
            stock_code: 股票代码
            limit: 限制返回数量（默认 4，即最近 4 个季度）

        Returns:
            FinancialData 列表，按日期降序排列
        """
        models = FinancialDataModel._default_manager.filter(
            stock_code=stock_code
        ).order_by('-report_date')[:limit]

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
                debt_ratio=m.debt_ratio
            )
            for m in models
        ]

    def get_valuation_history(
        self,
        stock_code: str,
        start_date: date,
        end_date: date
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
        models = ValuationModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date
        ).order_by('trade_date')

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

    def save_stock_info(self, stock_info: StockInfo) -> None:
        """
        保存股票基本信息

        Args:
            stock_info: StockInfo 实体
        """
        StockInfoModel._default_manager.update_or_create(
            stock_code=stock_info.stock_code,
            defaults={
                'name': stock_info.name,
                'sector': stock_info.sector,
                'market': stock_info.market,
                'list_date': stock_info.list_date
            }
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
            report_type = '1Q'
        elif month == 6:
            report_type = '2Q'
        elif month == 9:
            report_type = '3Q'
        else:
            report_type = '4Q'

        FinancialDataModel._default_manager.update_or_create(
            stock_code=financial.stock_code,
            report_date=financial.report_date,
            report_type=report_type,
            defaults={
                'revenue': financial.revenue,
                'net_profit': financial.net_profit,
                'revenue_growth': financial.revenue_growth,
                'net_profit_growth': financial.net_profit_growth,
                'total_assets': financial.total_assets,
                'total_liabilities': financial.total_liabilities,
                'equity': financial.equity,
                'roe': financial.roe,
                'roa': financial.roa,
                'debt_ratio': financial.debt_ratio
            }
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
                'pe': valuation.pe,
                'pb': valuation.pb,
                'ps': valuation.ps,
                'total_mv': valuation.total_mv,
                'circ_mv': valuation.circ_mv,
                'dividend_yield': valuation.dividend_yield,
                'source_provider': valuation.source_provider,
                'source_updated_at': valuation.source_updated_at,
                'fetched_at': valuation.fetched_at or timezone.now(),
                'pe_type': valuation.pe_type,
                'is_valid': valuation.is_valid,
                'quality_flag': valuation.quality_flag,
                'quality_notes': valuation.quality_notes,
                'raw_payload_hash': valuation.raw_payload_hash,
            }
        )

    def get_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date
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
        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date
        ).order_by('trade_date')

        return [(m.trade_date, m.close) for m in models]

    def get_technical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[TechnicalBar]:
        """获取K线与技术指标序列。"""
        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")

        return [
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

    def get_intraday_points(self, stock_code: str) -> list[IntradayPricePoint]:
        """获取单资产最新交易日的 1 分钟分时数据。"""
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
        self,
        stock_code: str,
        start_date: date,
        end_date: date
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
            import akshare as ak
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
            import akshare as ak
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
                    self._safe_decimal(weighted_amount / total_shares)
                    if total_shares > 0
                    else None
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

    def _safe_decimal(self, value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            decimal_value = Decimal(str(value))
            return None if decimal_value != decimal_value else decimal_value
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _safe_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def get_latest_financial_data(
        self,
        stock_code: str
    ) -> FinancialData | None:
        """
        获取股票最新的财务数据

        Args:
            stock_code: 股票代码

        Returns:
            FinancialData 或 None
        """
        model = FinancialDataModel._default_manager.filter(
            stock_code=stock_code
        ).order_by('-report_date').first()

        if not model:
            return None

        return FinancialData(
            stock_code=model.stock_code,
            report_date=model.report_date,
            revenue=model.revenue,
            net_profit=model.net_profit,
            revenue_growth=model.revenue_growth or 0.0,
            net_profit_growth=model.net_profit_growth or 0.0,
            total_assets=model.total_assets,
            total_liabilities=model.total_liabilities,
            equity=model.equity,
            roe=model.roe,
            roa=model.roa or 0.0,
            debt_ratio=model.debt_ratio
        )

    def get_stock_count_by_sector(self, sector: str) -> int:
        """
        获取指定行业的股票数量

        Args:
            sector: 行业名称

        Returns:
            股票数量
        """
        return StockInfoModel._default_manager.filter(
            sector=sector,
            is_active=True
        ).count()

    def get_all_sectors(self) -> list[str]:
        """
        获取所有行业列表

        Returns:
            行业名称列表
        """
        sectors = StockInfoModel._default_manager.filter(
            is_active=True
        ).values_list('sector', flat=True).distinct()

        return list(sectors)

    def list_active_stock_codes(self, limit: int | None = None) -> list[str]:
        """
        获取所有活跃股票代码列表

        用于批量扫描等场景，避免构造完整实体。

        Args:
            limit: 数量限制（可选）

        Returns:
            股票代码列表
        """
        queryset = StockInfoModel._default_manager.filter(
            is_active=True
        ).values_list('stock_code', flat=True).order_by('stock_code')

        if limit:
            queryset = queryset[:limit]

        return list(queryset)

    def get_latest_valuation_date(self) -> date | None:
        """获取最新估值日期。"""
        latest = ValuationModel._default_manager.order_by("-trade_date").values_list("trade_date", flat=True).first()
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
            model = ScoringWeightConfigModel._default_manager.filter(
                is_active=True
            ).first()

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
            model = ScoringWeightConfigModel._default_manager.filter(
                name=name
            ).first()

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
            models = ScoringWeightConfigModel._default_manager.all().order_by('-is_active', '-created_at')
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
                'description': config_entity.description,
                'is_active': config_entity.is_active,
                'growth_weight': config_entity.growth_weight,
                'profitability_weight': config_entity.profitability_weight,
                'valuation_weight': config_entity.valuation_weight,
                'revenue_growth_weight': config_entity.revenue_growth_weight,
                'profit_growth_weight': config_entity.profit_growth_weight,
            }
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
            profit_growth_weight=0.5
        )


class DjangoValuationRepairRepository:
    """Django ORM 估值修复仓储"""

    def upsert_snapshot(
        self,
        status,
        source_universe: str = "all_active"
    ) -> None:
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
            }
        )

    def deactivate_snapshot(
        self,
        stock_code: str,
        source_universe: str = "all_active"
    ) -> None:
        """
        停用估值修复快照

        Args:
            stock_code: 股票代码
            source_universe: 来源股票池
        """
        from .models import ValuationRepairTrackingModel

        ValuationRepairTrackingModel._default_manager.filter(
            stock_code=stock_code,
            source_universe=source_universe
        ).update(is_active=False)

    def list_active_snapshots(
        self,
        source_universe: str = "all_active",
        phase: str | None = None,
        limit: int = 50
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
            source_universe=source_universe,
            is_active=True
        )

        if phase:
            queryset = queryset.filter(current_phase=phase)

        return list(queryset.order_by("-composite_percentile")[:limit])

    def get_snapshot(
        self,
        stock_code: str,
        source_universe: str = "all_active"
    ) -> object | None:
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
                stock_code=stock_code,
                source_universe=source_universe,
                is_active=True
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
            ValuationDataQualitySnapshotModel._default_manager
            .filter(is_gate_passed=True)
            .order_by("-as_of_date")
            .first()
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
    source_deviation_count = sum(1 for item in valuations if item.quality_flag == "source_deviation")
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

