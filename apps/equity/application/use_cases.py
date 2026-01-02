"""
个股分析模块 Application 层用例

遵循四层架构规范：
- Application 层负责用例编排
- 通过依赖注入使用 Infrastructure 层
- 调用 Domain 层的业务逻辑
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import date
from decimal import Decimal

from apps.equity.domain.services import StockScreener
from apps.equity.domain.rules import StockScreeningRule


@dataclass
class ScreenStocksRequest:
    """筛选个股请求"""
    regime: Optional[str] = None  # 如果为 None，自动获取最新 Regime
    custom_rule: Optional[dict] = None  # 自定义规则
    max_count: int = 30


@dataclass
class ScreenStocksResponse:
    """筛选个股响应"""
    success: bool
    regime: str
    stock_codes: List[str]
    screening_criteria: dict
    error: Optional[str] = None


class ScreenStocksUseCase:
    """筛选个股用例"""

    def __init__(self, stock_repository, regime_repository):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
            regime_repository: Regime 数据仓储
        """
        self.stock_repo = stock_repository
        self.regime_repo = regime_repository

    def execute(self, request: ScreenStocksRequest) -> ScreenStocksResponse:
        """
        执行个股筛选

        流程：
        1. 获取当前 Regime（如果未指定）
        2. 加载对应的筛选规则
        3. 获取全市场股票数据
        4. 应用规则筛选
        5. 返回结果
        """
        try:
            # 1. 获取 Regime
            if request.regime:
                regime = request.regime
            else:
                latest_regime = self.regime_repo.get_latest_regime()
                regime = latest_regime['dominant_regime']

            # 2. 获取筛选规则（从数据库配置加载）
            from shared.infrastructure.config_loader import get_stock_screening_rule
            rule = get_stock_screening_rule(regime)

            if not rule:
                raise ValueError(
                    f"未找到 Regime '{regime}' 的筛选规则，"
                    f"请在 Django Admin 中配置或运行 scripts/init_equity_config.py"
                )

            if request.custom_rule:
                # 用户自定义规则覆盖
                rule = self._parse_custom_rule(request.custom_rule, regime)

            # 调整 max_count
            if request.max_count != rule.max_count:
                rule = StockScreeningRule(
                    regime=rule.regime,
                    name=rule.name,
                    min_roe=rule.min_roe,
                    min_revenue_growth=rule.min_revenue_growth,
                    min_profit_growth=rule.min_profit_growth,
                    max_debt_ratio=rule.max_debt_ratio,
                    max_pe=rule.max_pe,
                    max_pb=rule.max_pb,
                    min_market_cap=rule.min_market_cap,
                    sector_preference=rule.sector_preference,
                    max_count=request.max_count
                )

            # 3. 获取全市场数据（最新财务数据 + 最新估值）
            all_stocks = self.stock_repo.get_all_stocks_with_fundamentals()

            if not all_stocks:
                raise ValueError("没有找到股票数据，请先运行数据采集任务")

            # 4. 筛选（调用 Domain 服务）
            screener = StockScreener()
            stock_codes = screener.screen(all_stocks, rule)

            # 5. 返回结果
            return ScreenStocksResponse(
                success=True,
                regime=regime,
                stock_codes=stock_codes,
                screening_criteria={
                    'rule_name': rule.name,
                    'min_roe': rule.min_roe,
                    'max_pe': rule.max_pe,
                    'max_pb': rule.max_pb,
                    'sectors': rule.sector_preference
                }
            )

        except Exception as e:
            return ScreenStocksResponse(
                success=False,
                regime='',
                stock_codes=[],
                screening_criteria={},
                error=str(e)
            )

    def _parse_custom_rule(
        self,
        custom_rule: dict,
        regime: str
    ) -> StockScreeningRule:
        """
        解析自定义规则

        Args:
            custom_rule: 自定义规则字典
            regime: Regime 名称

        Returns:
            StockScreeningRule 对象
        """
        return StockScreeningRule(
            regime=regime,
            name=custom_rule.get('name', '自定义规则'),
            min_roe=custom_rule.get('min_roe', 0.0),
            min_revenue_growth=custom_rule.get('min_revenue_growth', 0.0),
            min_profit_growth=custom_rule.get('min_profit_growth', 0.0),
            max_debt_ratio=custom_rule.get('max_debt_ratio', 100.0),
            max_pe=custom_rule.get('max_pe', 999.0),
            max_pb=custom_rule.get('max_pb', 999.0),
            min_market_cap=Decimal(str(custom_rule.get('min_market_cap', 0))),
            sector_preference=custom_rule.get('sector_preference'),
            max_count=custom_rule.get('max_count', 50)
        )


@dataclass
class AnalyzeValuationRequest:
    """估值分析请求"""
    stock_code: str
    lookback_days: int = 252  # 回看天数（默认 1 年）


@dataclass
class AnalyzeValuationResponse:
    """估值分析响应"""
    success: bool
    stock_code: str
    stock_name: str
    current_pe: float
    pe_percentile: float
    current_pb: float
    pb_percentile: float
    is_undervalued: bool
    error: Optional[str] = None


class AnalyzeValuationUseCase:
    """估值分析用例"""

    def __init__(self, stock_repository):
        """
        初始化用例

        Args:
            stock_repository: 股票数据仓储
        """
        self.stock_repo = stock_repository

    def execute(self, request: AnalyzeValuationRequest) -> AnalyzeValuationResponse:
        """
        执行估值分析

        流程：
        1. 获取股票基本信息
        2. 获取历史估值数据
        3. 计算 PE/PB 百分位
        4. 判断是否低估
        5. 返回结果
        """
        try:
            from apps.equity.domain.services import ValuationAnalyzer
            from datetime import timedelta

            # 1. 获取股票基本信息
            stock_info = self.stock_repo.get_stock_info(request.stock_code)
            if not stock_info:
                raise ValueError(f"未找到股票 {request.stock_code}")

            # 2. 获取历史估值数据
            end_date = date.today()
            start_date = end_date - timedelta(days=request.lookback_days)

            valuation_history = self.stock_repo.get_valuation_history(
                request.stock_code,
                start_date,
                end_date
            )

            if not valuation_history:
                raise ValueError(f"未找到股票 {request.stock_code} 的估值数据")

            # 最新估值
            latest = valuation_history[-1]

            # 3. 计算百分位
            analyzer = ValuationAnalyzer()
            pe_history = [v.pe for v in valuation_history if v.pe > 0]
            pb_history = [v.pb for v in valuation_history if v.pb > 0]

            pe_percentile = analyzer.calculate_pe_percentile(latest.pe, pe_history)
            pb_percentile = analyzer.calculate_pb_percentile(latest.pb, pb_history)

            # 4. 判断是否低估
            is_undervalued = analyzer.is_undervalued(pe_percentile, pb_percentile)

            # 5. 返回结果
            return AnalyzeValuationResponse(
                success=True,
                stock_code=request.stock_code,
                stock_name=stock_info.name,
                current_pe=latest.pe,
                pe_percentile=pe_percentile,
                current_pb=latest.pb,
                pb_percentile=pb_percentile,
                is_undervalued=is_undervalued
            )

        except Exception as e:
            return AnalyzeValuationResponse(
                success=False,
                stock_code=request.stock_code,
                stock_name='',
                current_pe=0.0,
                pe_percentile=0.0,
                current_pb=0.0,
                pb_percentile=0.0,
                is_undervalued=False,
                error=str(e)
            )
