"""
Use Cases for Regime Calculation.

Application layer orchestrating the workflow of calculating Regime.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, List, Dict

from ..domain.services import RegimeCalculator, calculate_momentum, calculate_rolling_zscore
from ..domain.entities import RegimeSnapshot


@dataclass
class CalculateRegimeRequest:
    """计算 Regime 的请求 DTO"""
    as_of_date: date
    use_pit: bool = False
    growth_indicator: str = "PMI"
    inflation_indicator: str = "CPI"
    data_source: Optional[str] = None  # 数据源过滤（akshare, tushare等）


@dataclass
class CalculateRegimeResponse:
    """计算 Regime 的响应 DTO"""
    success: bool
    snapshot: Optional[RegimeSnapshot]
    warnings: List[str]
    error: Optional[str] = None
    # 新增：详细数据
    raw_data: Optional[Dict] = None  # 原始数据
    intermediate_data: Optional[Dict] = None  # 中间计算值
    history_data: Optional[List] = None  # 历史趋势


class CalculateRegimeUseCase:
    """
    计算 Regime 的用例

    职责：
    1. 协调 Repository 获取数据
    2. 调用 Domain 层服务计算
    3. 返回格式化结果
    """

    def __init__(self, repository, calculator: Optional[RegimeCalculator] = None):
        """
        Args:
            repository: MacroRepository 实例
            calculator: RegimeCalculator 实例（可选，默认使用标准配置）
        """
        self.repository = repository
        self.calculator = calculator or RegimeCalculator()

    def execute(self, request: CalculateRegimeRequest) -> CalculateRegimeResponse:
        """
        执行 Regime 计算

        Args:
            request: 计算请求

        Returns:
            CalculateRegimeResponse: 计算结果
        """
        try:
            # 1. 获取增长指标序列（值）
            growth_series = self.repository.get_growth_series(
                indicator_code=request.growth_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )

            # 2. 获取通胀指标序列（值）
            inflation_series = self.repository.get_inflation_series(
                indicator_code=request.inflation_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )

            # 3. 数据检查
            if not growth_series:
                return CalculateRegimeResponse(
                    success=False,
                    snapshot=None,
                    warnings=[],
                    error=f"无增长指标数据: {request.growth_indicator}"
                )

            if not inflation_series:
                return CalculateRegimeResponse(
                    success=False,
                    snapshot=None,
                    warnings=[],
                    error=f"无通胀指标数据: {request.inflation_indicator}"
                )

            # 4. 调用 Domain 层计算
            result = self.calculator.calculate(
                growth_series=growth_series,
                inflation_series=inflation_series,
                as_of_date=request.as_of_date
            )

            # 5. 获取完整数据（用于详细展示）
            growth_full = self.repository.get_growth_series_full(
                indicator_code=request.growth_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )
            inflation_full = self.repository.get_inflation_series_full(
                indicator_code=request.inflation_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )

            # 6. 计算中间值
            growth_momentums = calculate_momentum(growth_series, period=3)
            inflation_momentums = calculate_momentum(inflation_series, period=3)
            growth_z_scores = calculate_rolling_zscore(growth_momentums, window=60, min_periods=24)
            inflation_z_scores = calculate_rolling_zscore(inflation_momentums, window=60, min_periods=24)

            # 7. 组装详细数据
            raw_data = {
                'growth': [
                    {
                        'date': ind.reporting_period.isoformat(),
                        'value': ind.value,
                        'code': ind.code
                    } for ind in growth_full
                ],
                'inflation': [
                    {
                        'date': ind.reporting_period.isoformat(),
                        'value': ind.value,
                        'code': ind.code
                    } for ind in inflation_full
                ]
            }

            intermediate_data = {
                'growth_momentum': growth_momentums,
                'inflation_momentum': inflation_momentums,
                'growth_z_score': growth_z_scores,
                'inflation_z_score': inflation_z_scores
            }

            return CalculateRegimeResponse(
                success=True,
                snapshot=result.snapshot,
                warnings=result.warnings,
                error=None,
                raw_data=raw_data,
                intermediate_data=intermediate_data
            )

        except Exception as e:
            return CalculateRegimeResponse(
                success=False,
                snapshot=None,
                warnings=[],
                error=f"计算失败: {str(e)}"
            )

    def calculate_history(
        self,
        start_date: date,
        end_date: date,
        growth_indicator: str = "PMI",
        inflation_indicator: str = "CPI",
        use_pit: bool = False
    ) -> List[CalculateRegimeResponse]:
        """
        批量计算历史 Regime

        Args:
            start_date: 起始日期
            end_date: 结束日期
            growth_indicator: 增长指标代码
            inflation_indicator: 通胀指标代码
            use_pit: 是否使用 Point-in-Time 模式

        Returns:
            List[CalculateRegimeResponse]: 每个日期的计算结果
        """
        # 获取可用日期列表
        available_dates = self.repository.get_available_dates(
            codes=[
                self.repository.GROWTH_INDICATORS.get(growth_indicator, growth_indicator),
                self.repository.INFLATION_INDICATORS.get(inflation_indicator, inflation_indicator)
            ],
            start_date=start_date,
            end_date=end_date
        )

        results = []
        for dt in available_dates:
            request = CalculateRegimeRequest(
                as_of_date=dt,
                use_pit=use_pit,
                growth_indicator=growth_indicator,
                inflation_indicator=inflation_indicator
            )
            result = self.execute(request)
            results.append(result)

        return results
