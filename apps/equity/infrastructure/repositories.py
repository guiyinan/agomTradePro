"""
个股分析模块 Infrastructure 层数据仓储

遵循四层架构规范：
- Infrastructure 层允许导入 django.db
- 实现 Domain 层定义的接口（如果有的话）
- 负责数据持久化逻辑
"""

from typing import List, Optional, Tuple, Dict
from datetime import date
from decimal import Decimal

from django.db import models

from .models import (
    StockInfoModel,
    StockDailyModel,
    FinancialDataModel,
    ValuationModel
)
from apps.equity.domain.entities import (
    StockInfo,
    FinancialData,
    ValuationMetrics,
    TechnicalIndicators,
    EquityAssetScore
)


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
    ) -> List[EquityAssetScore]:
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
        queryset = StockInfoModel.objects.filter(is_active=True)

        # 应用过滤条件
        sector = filters.get("sector")
        if sector:
            queryset = queryset.filter(sector=sector)

        market = filters.get("market")
        if market:
            queryset = queryset.filter(market=market)

        # 需要关联估值表进行市值和PE过滤
        queryset = queryset.select_related().all()

        # 获取所有股票后再过滤（因为需要关联估值表）
        stocks_data = []
        for stock_model in queryset[:max_count * 2]:  # 多取一些
            stock_code = stock_model.stock_code

            # 获取最新估值数据
            valuation = ValuationModel.objects.filter(
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
            financial = FinancialDataModel.objects.filter(
                stock_code=stock_code
            ).order_by('-report_date').first()

            # 获取最新技术指标（从日线数据）
            daily = StockDailyModel.objects.filter(
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
                dividend_yield=valuation.dividend_yield or 0.0
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

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Optional[EquityAssetScore]:
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
            stock_model = StockInfoModel.objects.get(
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
            valuation_model = ValuationModel.objects.filter(
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
                dividend_yield=valuation_model.dividend_yield or 0.0
            ) if valuation_model else None

            # 获取最新财务数据
            financial_model = FinancialDataModel.objects.filter(
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
            daily_model = StockDailyModel.objects.filter(
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

    def get_all_stocks_with_fundamentals(
        self,
        as_of_date: Optional[date] = None
    ) -> List[Tuple[StockInfo, FinancialData, ValuationMetrics]]:
        """
        获取所有股票的基本面数据（最新财务数据 + 最新估值数据）

        Args:
            as_of_date: 截止日期（可选），如果不指定则使用最新数据

        Returns:
            [(StockInfo, FinancialData, ValuationMetrics), ...]
        """
        result = []

        # 获取所有活跃股票的基本信息
        stock_infos = StockInfoModel.objects.filter(is_active=True)

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
            financial_query = FinancialDataModel.objects.filter(
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
            valuation_query = ValuationModel.objects.filter(
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
                dividend_yield=valuation_query.dividend_yield or 0.0
            )

            result.append((stock_info, financial, valuation))

        return result

    def get_stock_info(self, stock_code: str) -> Optional[StockInfo]:
        """
        获取单个股票的基本信息

        Args:
            stock_code: 股票代码

        Returns:
            StockInfo 或 None
        """
        try:
            model = StockInfoModel.objects.get(stock_code=stock_code)
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
    ) -> List[FinancialData]:
        """
        获取股票的财务数据

        Args:
            stock_code: 股票代码
            limit: 限制返回数量（默认 4，即最近 4 个季度）

        Returns:
            FinancialData 列表，按日期降序排列
        """
        models = FinancialDataModel.objects.filter(
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
    ) -> List[ValuationMetrics]:
        """
        获取股票的估值历史数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            ValuationMetrics 列表，按日期升序排列
        """
        models = ValuationModel.objects.filter(
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
                dividend_yield=m.dividend_yield or 0.0
            )
            for m in models
        ]

    def save_stock_info(self, stock_info: StockInfo) -> None:
        """
        保存股票基本信息

        Args:
            stock_info: StockInfo 实体
        """
        StockInfoModel.objects.update_or_create(
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

        FinancialDataModel.objects.update_or_create(
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
        ValuationModel.objects.update_or_create(
            stock_code=valuation.stock_code,
            trade_date=valuation.trade_date,
            defaults={
                'pe': valuation.pe,
                'pb': valuation.pb,
                'ps': valuation.ps,
                'total_mv': valuation.total_mv,
                'circ_mv': valuation.circ_mv,
                'dividend_yield': valuation.dividend_yield
            }
        )

    def get_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date
    ) -> List[Tuple[date, Decimal]]:
        """
        获取股票的日线收盘价数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [(日期, 收盘价), ...]，按日期升序排列
        """
        models = StockDailyModel.objects.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date
        ).order_by('trade_date')

        return [(m.trade_date, m.close) for m in models]

    def calculate_daily_returns(
        self,
        stock_code: str,
        start_date: date,
        end_date: date
    ) -> Dict[date, float]:
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

    def get_latest_financial_data(
        self,
        stock_code: str
    ) -> Optional[FinancialData]:
        """
        获取股票最新的财务数据

        Args:
            stock_code: 股票代码

        Returns:
            FinancialData 或 None
        """
        model = FinancialDataModel.objects.filter(
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
        return StockInfoModel.objects.filter(
            sector=sector,
            is_active=True
        ).count()

    def get_all_sectors(self) -> List[str]:
        """
        获取所有行业列表

        Returns:
            行业名称列表
        """
        sectors = StockInfoModel.objects.filter(
            is_active=True
        ).values_list('sector', flat=True).distinct()

        return list(sectors)


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
            model = ScoringWeightConfigModel.objects.filter(
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
            model = ScoringWeightConfigModel.objects.filter(
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
            models = ScoringWeightConfigModel.objects.all().order_by('-is_active', '-created_at')
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

        ScoringWeightConfigModel.objects.update_or_create(
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
