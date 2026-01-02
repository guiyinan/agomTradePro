"""
Use Cases for Regime Calculation.

Application layer orchestrating the workflow of calculating Regime.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Dict, Set

from ..domain.services import RegimeCalculator, calculate_momentum, calculate_rolling_zscore
from ..domain.entities import RegimeSnapshot

logger = logging.getLogger(__name__)


class RegimeCalculationError(Exception):
    """Regime 计算异常"""
    pass


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
    4. 提供容错机制
    """

    # 定义关键指标的最小数据量要求
    MIN_DATA_POINTS = 24  # 至少24个月的数据
    CRITICAL_INDICATORS = {'CN_PMI', 'CN_CPI'}  # 关键指标

    def __init__(self, repository, regime_repository=None, calculator: Optional[RegimeCalculator] = None):
        """
        Args:
            repository: MacroRepository 实例
            regime_repository: RegimeRepository 实例（用于降级方案）
            calculator: RegimeCalculator 实例（可选，默认使用标准配置）
        """
        self.repository = repository
        self.regime_repository = regime_repository
        self.calculator = calculator or RegimeCalculator()

    def _check_data_completeness(
        self,
        growth_series: List[float],
        inflation_series: List[float],
        growth_code: str,
        inflation_code: str
    ) -> Set[str]:
        """
        检查数据完整性

        Args:
            growth_series: 增长指标序列
            inflation_series: 通胀指标序列
            growth_code: 增长指标代码
            inflation_code: 通胀指标代码

        Returns:
            Set[str]: 缺失的指标代码集合
        """
        missing = set()

        if not growth_series or len(growth_series) < self.MIN_DATA_POINTS:
            missing.add(growth_code)
            logger.warning(f"Growth indicator {growth_code} has insufficient data: {len(growth_series) if growth_series else 0}")

        if not inflation_series or len(inflation_series) < self.MIN_DATA_POINTS:
            missing.add(inflation_code)
            logger.warning(f"Inflation indicator {inflation_code} has insufficient data: {len(inflation_series) if inflation_series else 0}")

        return missing

    def _fill_missing_data(
        self,
        growth_code: str,
        inflation_code: str,
        end_date: date,
        missing_indicators: Set[str],
        use_pit: bool,
        source: Optional[str]
    ) -> Dict[str, Optional[List[float]]]:
        """
        使用前值填充缺失数据

        Args:
            growth_code: 增长指标代码
            inflation_code: 通胀指标代码
            end_date: 结束日期
            missing_indicators: 缺失的指标代码集合
            use_pit: 是否使用 PIT 模式
            source: 数据源

        Returns:
            Dict: 填充后的数据 {'growth': List[float], 'inflation': List[float]}
        """
        result = {'growth': None, 'inflation': None}

        for indicator_code in missing_indicators:
            # 获取前值
            last_observation = self.repository.get_latest_observation(
                code=indicator_code,
                before_date=end_date
            )

            if last_observation:
                logger.info(f"Filled {indicator_code} with last value: {last_observation.value} from {last_observation.reporting_period}")

                # 获取完整序列并添加前值填充
                if indicator_code == growth_code:
                    full_series = self.repository.get_growth_series_full(
                        indicator_code=growth_code,
                        end_date=end_date,
                        use_pit=use_pit,
                        source=source
                    )
                    # 在序列开头插入前值（如果序列为空或第一个值晚于 end_date - timedelta(days=60)）
                    if full_series and (end_date - full_series[0].reporting_period).days > 60:
                        # 创建一个填充的指标
                        from apps.macro.domain.entities import MacroIndicator, PeriodType
                        filled_indicator = MacroIndicator(
                            code=indicator_code,
                            value=last_observation.value,
                            reporting_period=end_date - timedelta(days=30),  # 假设月度数据
                            period_type=PeriodType.MONTH,
                            published_at=last_observation.published_at,
                            source=last_observation.source
                        )
                        result['growth'] = [filled_indicator.value] + [ind.value for ind in full_series]
                    else:
                        result['growth'] = [ind.value for ind in full_series]

                elif indicator_code == inflation_code:
                    full_series = self.repository.get_inflation_series_full(
                        indicator_code=inflation_code,
                        end_date=end_date,
                        use_pit=use_pit,
                        source=source
                    )
                    if full_series and (end_date - full_series[0].reporting_period).days > 60:
                        from apps.macro.domain.entities import MacroIndicator, PeriodType
                        filled_indicator = MacroIndicator(
                            code=indicator_code,
                            value=last_observation.value,
                            reporting_period=end_date - timedelta(days=30),
                            period_type=PeriodType.MONTH,
                            published_at=last_observation.published_at,
                            source=last_observation.source
                        )
                        result['inflation'] = [filled_indicator.value] + [ind.value for ind in full_series]
                    else:
                        result['inflation'] = [ind.value for ind in full_series]
            else:
                logger.warning(f"No previous observation available for {indicator_code}")

        return result

    def _is_critical_data_missing(self, missing_indicators: Set[str]) -> bool:
        """
        检查是否有关键数据缺失

        Args:
            missing_indicators: 缺失的指标代码集合

        Returns:
            bool: 是否关键数据缺失
        """
        return bool(missing_indicators & self.CRITICAL_INDICATORS)

    def _fallback_regime_estimation(self, as_of_date: date) -> RegimeSnapshot:
        """
        降级方案：使用上一次的 Regime，降低置信度

        Args:
            as_of_date: 当前日期

        Returns:
            RegimeSnapshot: 降级后的快照

        Raises:
            RegimeCalculationError: 无可用的降级数据
        """
        if not self.regime_repository:
            raise RegimeCalculationError("No regime repository available for fallback")

        last_regime = self.regime_repository.get_latest_snapshot(before_date=as_of_date)

        if not last_regime:
            raise RegimeCalculationError("No fallback regime available")

        # 降低置信度（最多降低到 0.1）
        new_confidence = max(last_regime.confidence * 0.8, 0.1)

        logger.warning(
            f"Using fallback regime from {last_regime.observed_at}, "
            f"confidence reduced from {last_regime.confidence:.2f} to {new_confidence:.2f}"
        )

        return RegimeSnapshot(
            growth_momentum_z=last_regime.growth_momentum_z,
            inflation_momentum_z=last_regime.inflation_momentum_z,
            distribution=last_regime.distribution,
            dominant_regime=last_regime.dominant_regime,
            confidence=new_confidence,
            observed_at=as_of_date
        )

    def execute(self, request: CalculateRegimeRequest) -> CalculateRegimeResponse:
        """
        执行 Regime 计算（带容错机制）

        Args:
            request: 计算请求

        Returns:
            CalculateRegimeResponse: 计算结果
        """
        warnings_list = []

        try:
            # 转换指标代码
            growth_code = self.repository.GROWTH_INDICATORS.get(request.growth_indicator, request.growth_indicator)
            inflation_code = self.repository.INFLATION_INDICATORS.get(request.inflation_indicator, request.inflation_indicator)

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

            # 3. 数据完整性检查
            missing_indicators = self._check_data_completeness(
                growth_series=growth_series,
                inflation_series=inflation_series,
                growth_code=growth_code,
                inflation_code=inflation_code
            )

            # 4. 如果有缺失数据，尝试前值填充
            if missing_indicators:
                logger.info(f"Missing indicators detected: {missing_indicators}, attempting forward fill")
                filled_data = self._fill_missing_data(
                    growth_code=growth_code,
                    inflation_code=inflation_code,
                    end_date=request.as_of_date,
                    missing_indicators=missing_indicators,
                    use_pit=request.use_pit,
                    source=request.data_source
                )

                # 更新数据
                if filled_data.get('growth'):
                    growth_series = filled_data['growth']
                    warnings_list.append(f"增长指标使用前值填充")
                if filled_data.get('inflation'):
                    inflation_series = filled_data['inflation']
                    warnings_list.append(f"通胀指标使用前值填充")

            # 5. 再次检查数据完整性
            missing_indicators = self._check_data_completeness(
                growth_series=growth_series,
                inflation_series=inflation_series,
                growth_code=growth_code,
                inflation_code=inflation_code
            )

            # 6. 如果关键数据仍然缺失，使用降级方案
            if missing_indicators and self._is_critical_data_missing(missing_indicators):
                logger.warning(f"Critical data missing after fill attempt: {missing_indicators}, using fallback regime")
                try:
                    snapshot = self._fallback_regime_estimation(request.as_of_date)
                    return CalculateRegimeResponse(
                        success=True,
                        snapshot=snapshot,
                        warnings=warnings_list + ["使用降级方案：基于上一次的 Regime"],
                        error=None,
                        raw_data=None,
                        intermediate_data=None
                    )
                except RegimeCalculationError as e:
                    return CalculateRegimeResponse(
                        success=False,
                        snapshot=None,
                        warnings=warnings_list,
                        error=f"计算失败且无降级方案: {str(e)}"
                    )

            # 7. 调用 Domain 层计算
            result = self.calculator.calculate(
                growth_series=growth_series,
                inflation_series=inflation_series,
                as_of_date=request.as_of_date
            )

            # 8. 获取完整数据（用于详细展示）
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

            # 8.5. 获取实际最新数据的日期（用于 observed_at）
            actual_data_dates = []
            if growth_full:
                actual_data_dates.append(growth_full[-1].reporting_period)
            if inflation_full:
                actual_data_dates.append(inflation_full[-1].reporting_period)

            # 使用较早的日期作为 observed_at（确保两个指标都有数据）
            if actual_data_dates:
                actual_observed_at = min(actual_data_dates)
            else:
                actual_observed_at = request.as_of_date

            # 9. 计算中间值
            growth_momentums = calculate_momentum(growth_series, period=3)
            inflation_momentums = calculate_momentum(inflation_series, period=3)
            growth_z_scores = calculate_rolling_zscore(growth_momentums, window=60, min_periods=24)
            inflation_z_scores = calculate_rolling_zscore(inflation_momentums, window=60, min_periods=24)

            # 10. 组装详细数据
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

            # 创建新的 snapshot，使用实际数据日期
            from ..domain.entities import RegimeSnapshot
            corrected_snapshot = RegimeSnapshot(
                growth_momentum_z=result.snapshot.growth_momentum_z,
                inflation_momentum_z=result.snapshot.inflation_momentum_z,
                distribution=result.snapshot.distribution,
                dominant_regime=result.snapshot.dominant_regime,
                confidence=result.snapshot.confidence,
                observed_at=actual_observed_at  # 使用实际数据日期
            )

            return CalculateRegimeResponse(
                success=True,
                snapshot=corrected_snapshot,
                warnings=result.warnings + warnings_list,
                error=None,
                raw_data=raw_data,
                intermediate_data=intermediate_data
            )

        except RegimeCalculationError as e:
            # 降级方案失败
            return CalculateRegimeResponse(
                success=False,
                snapshot=None,
                warnings=warnings_list,
                error=f"计算失败: {str(e)}"
            )
        except Exception as e:
            # 其他异常
            logger.exception(f"Unexpected error during regime calculation: {e}")
            return CalculateRegimeResponse(
                success=False,
                snapshot=None,
                warnings=warnings_list,
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
