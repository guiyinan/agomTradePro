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
    TechnicalIndicators
)


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
