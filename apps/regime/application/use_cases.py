"""
Use Cases for Regime Calculation.

Application layer orchestrating the workflow of calculating Regime.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from core.exceptions import (
    BusinessLogicError,
    DataFetchError,
    InsufficientDataError,
)
from core.metrics import record_exception
from shared.infrastructure.config_helper import ConfigHelper, ConfigKeys

from ..domain.entities import RegimeSnapshot
from ..domain.services import (
    RegimeCalculator,
    calculate_absolute_momentum,
    calculate_momentum,
    calculate_rolling_zscore,
)

logger = logging.getLogger(__name__)


# 默认阈值（从配置读取失败时使用）
DEFAULT_SPREAD_BP_THRESHOLD = 100.0
DEFAULT_US_YIELD_THRESHOLD = 4.5
DEFAULT_DAILY_PERSIST_DAYS = 10
DEFAULT_CONFLICT_CONFIDENCE_BOOST = 0.2



# ==================== High-Frequency Signal Use Cases ====================

class SpreadCalculationError(Exception):
    """Spread calculation exception"""
    pass


@dataclass
class CalculateTermSpreadRequest:
    """Calculate term spread request DTO"""
    as_of_date: date
    long_term: str = "10Y"  # 10Y, 5Y
    short_term: str = "2Y"  # 2Y, 1Y
    country: str = "CN"  # CN or US


@dataclass
class CalculateTermSpreadResponse:
    """Calculate term spread response DTO"""
    success: bool
    spread_value: float | None  # BP (基点)
    long_yield: float | None  # %
    short_yield: float | None  # %
    is_inverted: bool
    inversion_severity: float  # BP (0 if not inverted)
    curve_shape: str  # INVERTED, FLAT, NORMAL, STEEP
    error: str | None = None


class CalculateTermSpreadUseCase:
    """
    Calculate term spread use case

    Term spread = long_term_yield - short_term_yield
    Expressed in basis points (BP), where 1% = 100 BP

    Economic meaning:
    - Positive spread: Normal yield curve (market expects growth)
    - Negative spread (inverted): Recession warning
    - Flat spread: Uncertainty or transition period
    """

    def __init__(self, repository):
        self.repository = repository

    def execute(self, request: CalculateTermSpreadRequest) -> CalculateTermSpreadResponse:
        """
        Calculate term spread for a given date

        Args:
            request: Calculation request

        Returns:
            CalculateTermSpreadResponse: Calculation result
        """
        try:
            # Build indicator codes
            long_code = f"{request.country}_BOND_{request.long_term}"
            short_code = f"{request.country}_BOND_{request.short_term}"

            # Get yields for the date (use latest available if exact date not found)
            long_yield_data = self.repository.get_by_code_and_date(
                code=long_code,
                observed_at=request.as_of_date
            )

            short_yield_data = self.repository.get_by_code_and_date(
                code=short_code,
                observed_at=request.as_of_date
            )

            if not long_yield_data or not short_yield_data:
                # Try to get latest available data
                long_yield_data = self.repository.get_latest_observation(
                    code=long_code,
                    before_date=request.as_of_date
                )
                short_yield_data = self.repository.get_latest_observation(
                    code=short_code,
                    before_date=request.as_of_date
                )

            if not long_yield_data or not short_yield_data:
                return CalculateTermSpreadResponse(
                    success=False,
                    spread_value=None,
                    long_yield=None,
                    short_yield=None,
                    is_inverted=False,
                    inversion_severity=0.0,
                    curve_shape="NO_DATA",
                    error=f"Bond yield data not available for {long_code} or {short_code}"
                )

            long_yield = long_yield_data.value
            short_yield = short_yield_data.value

            # Calculate spread in basis points
            spread_pct = long_yield - short_yield
            spread_bp = spread_pct * 100  # Convert to BP

            # Determine curve characteristics
            is_inverted = spread_bp < 0
            inversion_severity = abs(spread_bp) if is_inverted else 0.0

            if is_inverted:
                curve_shape = "INVERTED"
            elif abs(spread_bp) < 0.5:  # Less than 0.5 BP
                curve_shape = "FLAT"
            elif spread_bp > 1.5:  # More than 1.5 BP
                curve_shape = "STEEP"
            else:
                curve_shape = "NORMAL"

            return CalculateTermSpreadResponse(
                success=True,
                spread_value=spread_bp,
                long_yield=long_yield,
                short_yield=short_yield,
                is_inverted=is_inverted,
                inversion_severity=inversion_severity,
                curve_shape=curve_shape,
                error=None
            )

        except Exception as e:
            logger.exception(f"Error calculating term spread: {e}")
            return CalculateTermSpreadResponse(
                success=False,
                spread_value=None,
                long_yield=None,
                short_yield=None,
                is_inverted=False,
                inversion_severity=0.0,
                curve_shape="ERROR",
                error=str(e)
            )


@dataclass
class HighFrequencySignalRequest:
    """Generate high-frequency signal request DTO"""
    as_of_date: date
    lookback_days: int = 30  # Days to look back for trend calculation


@dataclass
class HighFrequencySignalResponse:
    """High-frequency signal response DTO"""
    success: bool
    signal_direction: str | None  # BULLISH, BEARISH, NEUTRAL
    signal_strength: float  # 0-1
    confidence: float  # 0-1
    contributing_indicators: list[dict]  # Indicators that contributed to the signal
    warning_signals: list[str]  # Any warning signals (e.g., yield curve inversion)
    error: str | None = None


class HighFrequencySignalUseCase:
    """
    Generate high-frequency regime signal use case

    Uses daily/weekly high-frequency indicators to generate early warning signals
    for regime changes. This reduces lag from 3-6 months to 1-2 weeks.
    """

    def __init__(self, repository):
        self.repository = repository

    def execute(self, request: HighFrequencySignalRequest) -> HighFrequencySignalResponse:
        """
        Generate high-frequency regime signal

        Args:
            request: Signal generation request

        Returns:
            HighFrequencySignalResponse: Generated signal
        """
        try:
            from apps.macro.domain.entities import RegimeSensitivity

            contributing_indicators = []
            warning_signals = []
            signal_scores = []  # List of (score, weight) tuples

            # 1. Check term spread (10Y-2Y) - HIGH sensitivity
            term_spread_result = self._evaluate_term_spread(request.as_of_date)
            if term_spread_result['success']:
                contributing_indicators.append({
                    'code': 'CN_TERM_SPREAD_10Y2Y',
                    'value': term_spread_result['spread_value'],
                    'signal': term_spread_result['signal'],
                    'sensitivity': 'HIGH'
                })

                # Score: -1 (bearish) to +1 (bullish)
                # Normalized: spread > threshold BP = +1, spread < 0 BP = -1
                spread_bp = term_spread_result['spread_value']
                spread_threshold = ConfigHelper.get_float(
                    ConfigKeys.REGIME_SPREAD_BP_THRESHOLD,
                    DEFAULT_SPREAD_BP_THRESHOLD
                )
                if spread_bp > spread_threshold:
                    score = 1.0
                elif spread_bp < 0:
                    score = -1.0
                else:
                    score = (spread_bp / spread_threshold)  # Linear interpolation
                signal_scores.append((score, 1.0))  # Weight 1.0 for term spread

                if term_spread_result['is_inverted']:
                    warning_signals.append("YIELD_CURVE_INVERTED")

            # 2. Check NHCI (南华商品指数) - MEDIUM sensitivity
            nhci_result = self._evaluate_nhci(request.as_of_date, request.lookback_days)
            if nhci_result['success']:
                contributing_indicators.append({
                    'code': 'CN_NHCI',
                    'value': nhci_result['current_value'],
                    'change_pct': nhci_result['change_pct'],
                    'signal': nhci_result['signal'],
                    'sensitivity': 'MEDIUM'
                })

                # Score based on momentum
                signal_scores.append((nhci_result['score'], 0.8))

            # 3. Check US 10Y bond - MEDIUM sensitivity
            us_bond_result = self._evaluate_us_bond(request.as_of_date)
            if us_bond_result['success']:
                contributing_indicators.append({
                    'code': 'US_BOND_10Y',
                    'value': us_bond_result['value'],
                    'signal': us_bond_result['signal'],
                    'sensitivity': 'MEDIUM'
                })

                signal_scores.append((us_bond_result['score'], 0.7))

            # 4. Aggregate signals
            if not signal_scores:
                return HighFrequencySignalResponse(
                    success=False,
                    signal_direction=None,
                    signal_strength=0.0,
                    confidence=0.0,
                    contributing_indicators=[],
                    warning_signals=[],
                    error="No high-frequency indicators available"
                )

            # Weighted average of scores
            total_weight = sum(weight for _, weight in signal_scores)
            weighted_score = sum(score * weight for score, weight in signal_scores) / total_weight

            # Determine signal direction
            if weighted_score > 0.3:
                signal_direction = "BULLISH"
            elif weighted_score < -0.3:
                signal_direction = "BEARISH"
            else:
                signal_direction = "NEUTRAL"

            # Signal strength is the absolute value of the weighted score
            signal_strength = min(abs(weighted_score), 1.0)

            # Confidence based on number of indicators and agreement
            num_indicators = len(contributing_indicators)
            if num_indicators >= 3:
                base_confidence = 0.7
            elif num_indicators >= 2:
                base_confidence = 0.5
            else:
                base_confidence = 0.3

            # Boost confidence if indicators agree
            all_agree = all(
                ind['signal'] == signal_direction
                for ind in contributing_indicators
            )
            if all_agree and num_indicators > 1:
                confidence = min(base_confidence + 0.2, 1.0)
            else:
                confidence = base_confidence

            return HighFrequencySignalResponse(
                success=True,
                signal_direction=signal_direction,
                signal_strength=signal_strength,
                confidence=confidence,
                contributing_indicators=contributing_indicators,
                warning_signals=warning_signals,
                error=None
            )

        except Exception as e:
            logger.exception(f"Error generating high-frequency signal: {e}")
            return HighFrequencySignalResponse(
                success=False,
                signal_direction=None,
                signal_strength=0.0,
                confidence=0.0,
                contributing_indicators=[],
                warning_signals=[],
                error=str(e)
            )

    def _evaluate_term_spread(self, as_of_date: date) -> dict:
        """Evaluate term spread indicator"""
        try:
            # 重构说明 (2026-03-11): 使用注入的 repository 而非创建新实例
            # Get latest term spread data
            spread_data = self.repository.get_latest_observation(
                code='CN_TERM_SPREAD_10Y2Y',
                before_date=as_of_date
            )

            if not spread_data:
                return {'success': False}

            spread_bp = spread_data.value  # Already in BP
            is_inverted = spread_bp < 0

            spread_threshold = ConfigHelper.get_float(
                ConfigKeys.REGIME_SPREAD_BP_THRESHOLD,
                DEFAULT_SPREAD_BP_THRESHOLD
            )
            if is_inverted:
                signal = 'BEARISH'
            elif spread_bp > spread_threshold:
                signal = 'BULLISH'
            else:
                signal = 'NEUTRAL'

            return {
                'success': True,
                'spread_value': spread_bp,
                'is_inverted': is_inverted,
                'signal': signal
            }
        except Exception as e:
            logger.warning(f"Error evaluating term spread: {e}")
            return {'success': False}

    def _evaluate_nhci(self, as_of_date: date, lookback_days: int) -> dict:
        """Evaluate NHCI (南华商品指数) indicator"""
        try:
            # 重构说明 (2026-03-11): 使用注入的 repository 而非创建新实例
            # Get current and historical NHCI
            current_data = self.repository.get_latest_observation(
                code='CN_NHCI',
                before_date=as_of_date
            )

            if not current_data:
                return {'success': False}

            # Get data from lookback_days ago
            from datetime import timedelta
            past_date = as_of_date - timedelta(days=lookback_days)
            past_data = self.repository.get_latest_observation(
                code='CN_NHCI',
                before_date=past_date
            )

            if not past_data:
                return {'success': False}

            current_value = current_data.value
            past_value = past_data.value
            change_pct = ((current_value - past_value) / past_value) * 100

            # NHCI rising indicates industrial demand (bullish for growth)
            # NHCI falling indicates slowing demand (bearish)
            if change_pct > 5:
                signal = 'BULLISH'
                score = 1.0
            elif change_pct < -5:
                signal = 'BEARISH'
                score = -1.0
            else:
                signal = 'NEUTRAL'
                score = change_pct / 5  # Linear interpolation

            return {
                'success': True,
                'current_value': current_value,
                'change_pct': change_pct,
                'signal': signal,
                'score': score
            }
        except Exception as e:
            logger.warning(f"Error evaluating NHCI: {e}")
            return {'success': False}

    def _evaluate_us_bond(self, as_of_date: date) -> dict:
        """Evaluate US 10Y bond yield indicator"""
        try:
            # 重构说明 (2026-03-11): 使用注入的 repository 而非创建新实例
            # Get latest US 10Y bond
            us_bond_data = self.repository.get_latest_observation(
                code='US_BOND_10Y',
                before_date=as_of_date
            )

            if not us_bond_data:
                return {'success': False}

            us_yield = us_bond_data.value  # In percent

            # US bond yield interpretation for China regime:
            # - Rising US yields -> capital outflow pressure -> BEARISH for China
            # - Falling US yields -> easing pressure -> BULLISH for China
            # - Threshold from configuration
            us_yield_threshold = ConfigHelper.get_float(
                ConfigKeys.REGIME_US_YIELD_THRESHOLD,
                DEFAULT_US_YIELD_THRESHOLD
            )
            if us_yield > us_yield_threshold:
                signal = 'BEARISH'
                score = -1.0
            elif us_yield < 3.0:
                signal = 'BULLISH'
                score = 1.0
            else:
                signal = 'NEUTRAL'
                # Linear interpolation between 3.0% and threshold
                score = 1.0 - ((us_yield - 3.0) / (us_yield_threshold - 3.0)) * 2

            return {
                'success': True,
                'value': us_yield,
                'signal': signal,
                'score': score
            }
        except Exception as e:
            logger.warning(f"Error evaluating US bond: {e}")
            return {'success': False}


@dataclass
class ResolveSignalConflictRequest:
    """Resolve signal conflict request DTO"""
    daily_signal: str  # BULLISH, BEARISH, NEUTRAL
    daily_confidence: float
    daily_duration_days: int  # How many days daily signal has persisted
    monthly_signal: str
    monthly_confidence: float
    weekly_signal: str | None = None  # Optional weekly signal


@dataclass
class ResolveSignalConflictResponse:
    """Resolve signal conflict response DTO"""
    final_signal: str
    final_confidence: float
    resolution_reason: str
    source: str  # DAILY_ONLY, MONTHLY_DEFAULT, DAILY_PERSISTENT, DAILY_WEEKLY_CONSISTENT, ALL_CONSISTENT


class ResolveSignalConflictUseCase:
    """
    Resolve signal conflicts between daily high-frequency and monthly traditional indicators

    Rules:
    1. Daily == Monthly: High confidence (0.9)
    2. Daily persists >= N days: Use daily (configurable)
    3. Daily + Weekly一致 (both differ from monthly): Consider switching (0.6 confidence)
    4. Default: Use monthly, lower confidence (0.5)
    """

    def execute(self, request: ResolveSignalConflictRequest) -> ResolveSignalConflictResponse:
        """
        Resolve signal conflict using predefined rules

        Args:
            request: Conflict resolution request

        Returns:
            ResolveSignalConflictResponse: Resolution result
        """
        # Get configurable values
        daily_persist_days = ConfigHelper.get_int(
            ConfigKeys.REGIME_DAILY_PERSIST_DAYS,
            DEFAULT_DAILY_PERSIST_DAYS
        )
        confidence_boost = ConfigHelper.get_float(
            ConfigKeys.REGIME_CONFLICT_CONFIDENCE_BOOST,
            DEFAULT_CONFLICT_CONFIDENCE_BOOST
        )

        # Rule 1: Daily and Monthly一致
        if request.daily_signal == request.monthly_signal:
            avg_confidence = (request.daily_confidence + request.monthly_confidence) / 2
            return ResolveSignalConflictResponse(
                final_signal=request.daily_signal,
                final_confidence=min(avg_confidence + confidence_boost, 1.0),  # Boost confidence
                resolution_reason="Daily and monthly signals一致",
                source="ALL_CONSISTENT"
            )

        # Rule 2: Daily signal persists for >= N days
        if request.daily_duration_days >= daily_persist_days:
            return ResolveSignalConflictResponse(
                final_signal=request.daily_signal,
                final_confidence=min(request.daily_confidence + 0.1, 1.0),
                resolution_reason=f"Daily signal persisted for {request.daily_duration_days} days",
                source="DAILY_PERSISTENT"
            )

        # Rule 3: Daily + Weekly一致 (both differ from monthly)
        if request.weekly_signal and request.weekly_signal == request.daily_signal:
            return ResolveSignalConflictResponse(
                final_signal=request.daily_signal,
                final_confidence=0.6,
                resolution_reason="Daily and weekly signals一致，monthly differs",
                source="DAILY_WEEKLY_CONSISTENT"
            )

        # Rule 4: Default - Use monthly signal, lower confidence
        return ResolveSignalConflictResponse(
            final_signal=request.monthly_signal,
            final_confidence=max(request.monthly_confidence * 0.8, 0.4),
            resolution_reason="Default: Use monthly signal, reduce confidence due to conflicting daily signal",
            source="MONTHLY_DEFAULT"
        )


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
    data_source: str | None = None  # 数据源过滤（akshare, tushare等）
    skip_cache: bool = False  # 跳过缓存，强制重新计算


@dataclass
class CalculateRegimeResponse:
    """计算 Regime 的响应 DTO"""
    success: bool
    snapshot: RegimeSnapshot | None
    warnings: list[str]
    error: str | None = None
    # 新增：详细数据
    raw_data: dict | None = None  # 原始数据
    intermediate_data: dict | None = None  # 中间计算值
    history_data: list | None = None  # 历史趋势


class CalculateRegimeUseCase:
    """
    [LEGACY] 计算 Regime 的 V1 用例（动量/Z-score 路径）

    职责：
    1. 协调 Repository 获取数据
    2. 调用 Domain 层服务计算
    3. 返回格式化结果
    4. 提供容错机制

    说明：
    - 主业务流程已统一迁移到 V2 + resolve_current_regime()。
    - 本类仅保留历史兼容与离线回算，不应再作为线上主链路入口。
    """

    # 定义关键指标的最小数据量要求
    MIN_DATA_POINTS = 24  # 至少24个月的数据
    CRITICAL_INDICATORS = {'CN_PMI', 'CN_CPI', 'CN_CPI_NATIONAL_YOY'}  # 关键指标
    MAX_FALLBACK_COUNT = 3  # 最大降级次数限制（防止无限循环）

    def __init__(self, repository, regime_repository=None, calculator: RegimeCalculator | None = None):
        """
        Args:
            repository: MacroRepository 实例
            regime_repository: RegimeRepository 实例（用于降级方案）
            calculator: RegimeCalculator 实例（可选，默认使用标准配置）
        """
        self.repository = repository
        self.regime_repository = regime_repository
        self.calculator = calculator or RegimeCalculator()
        self._consecutive_fallback_count = 0  # 连续降级计数器（每次计算重置）

    def _check_data_completeness(
        self,
        growth_series: list[float],
        inflation_series: list[float],
        growth_code: str,
        inflation_code: str
    ) -> set[str]:
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
        missing_indicators: set[str],
        use_pit: bool,
        source: str | None
    ) -> dict[str, list[float] | None]:
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

    def _is_critical_data_missing(self, missing_indicators: set[str]) -> bool:
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
            RegimeCalculationError: 无可用的降级数据或降级次数超限
        """
        if not self.regime_repository:
            raise RegimeCalculationError("No regime repository available for fallback")

        last_regime = self.regime_repository.get_latest_snapshot(before_date=as_of_date)

        if not last_regime:
            raise RegimeCalculationError("No fallback regime available")

        # 检查降级次数限制
        self._consecutive_fallback_count += 1
        if self._consecutive_fallback_count > self.MAX_FALLBACK_COUNT:
            logger.error(
                f"Exceeded maximum fallback count ({self.MAX_FALLBACK_COUNT}). "
                f"Data has been missing for too long. Refusing to return stale regime."
            )
            raise RegimeCalculationError(
                f"Maximum fallback count ({self.MAX_FALLBACK_COUNT}) exceeded. "
                f"Data has been unavailable for {self._consecutive_fallback_count} consecutive attempts. "
                f"Please check data source availability."
            )

        # 降低置信度（最多降低到 0.1）
        new_confidence = max(last_regime.confidence * 0.8, 0.1)

        logger.warning(
            f"Using fallback regime from {last_regime.observed_at}, "
            f"confidence reduced from {last_regime.confidence:.2f} to {new_confidence:.2f} "
            f"(fallback count: {self._consecutive_fallback_count}/{self.MAX_FALLBACK_COUNT})"
        )

        return RegimeSnapshot(
            growth_momentum_z=last_regime.growth_momentum_z,
            inflation_momentum_z=last_regime.inflation_momentum_z,
            distribution=last_regime.distribution,
            dominant_regime=last_regime.dominant_regime,
            confidence=new_confidence,
            observed_at=as_of_date,
            data_source="fallback",
            fallback_count=self._consecutive_fallback_count
        )

    def execute(self, request: CalculateRegimeRequest) -> CalculateRegimeResponse:
        """
        执行 Regime 计算（带容错机制 + 缓存优化）

        Args:
            request: 计算请求

        Returns:
            CalculateRegimeResponse: 计算结果
        """
        warnings_list = []
        is_pytest_env = bool(os.getenv("PYTEST_CURRENT_TEST"))

        # 易用性改进 - Redis缓存层：优先检查缓存（除非跳过缓存）
        if not request.skip_cache and not is_pytest_env:
            try:
                from shared.infrastructure.cache_service import CacheService

                cached_data = CacheService.get_regime(
                    as_of_date=request.as_of_date.isoformat(),
                    growth_indicator=request.growth_indicator,
                    inflation_indicator=request.inflation_indicator,
                )

                if cached_data:
                    logger.info(f"Regime缓存命中: {request.as_of_date}, {request.growth_indicator}/{request.inflation_indicator}")
                    # 从缓存恢复RegimeSnapshot对象
                    snapshot = RegimeSnapshot(
                        growth_momentum_z=cached_data['growth_momentum_z'],
                        inflation_momentum_z=cached_data['inflation_momentum_z'],
                        distribution=cached_data['distribution'],
                        dominant_regime=cached_data['dominant_regime'],
                        confidence=cached_data['confidence'],
                        observed_at=date.fromisoformat(cached_data['observed_at']),
                        data_source=cached_data.get('data_source', 'cached'),
                        fallback_count=cached_data.get('fallback_count', 0),
                    )
                    return CalculateRegimeResponse(
                        success=True,
                        snapshot=snapshot,
                        warnings=cached_data.get('warnings', []),
                        error=None,
                        raw_data=cached_data.get('raw_data'),
                        intermediate_data=cached_data.get('intermediate_data'),
                        history_data=cached_data.get('history_data'),
                    )
            except ImportError:
                logger.warning("CacheService不可用，跳过缓存检查")
            except Exception as e:
                logger.warning(f"缓存检查失败: {e}，继续正常计算")

        try:
            # 重置降级计数器（每次新的计算尝试）
            self._consecutive_fallback_count = 0

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
                    warnings_list.append("增长指标使用前值填充")
                if filled_data.get('inflation'):
                    inflation_series = filled_data['inflation']
                    warnings_list.append("通胀指标使用前值填充")

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
            # 重置降级计数器（成功获取数据并计算）
            self._consecutive_fallback_count = 0

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

            # 9. 计算中间值（用于详细展示）
            # 增长指标：使用相对动量
            growth_momentums = calculate_momentum(growth_series, period=3)
            # 通胀指标：使用绝对差值动量（避免低基数扭曲）
            inflation_momentums = calculate_absolute_momentum(inflation_series, period=3)
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
            corrected_snapshot = RegimeSnapshot(
                growth_momentum_z=result.snapshot.growth_momentum_z,
                inflation_momentum_z=result.snapshot.inflation_momentum_z,
                distribution=result.snapshot.distribution,
                dominant_regime=result.snapshot.dominant_regime,
                confidence=result.snapshot.confidence,
                observed_at=actual_observed_at,  # 使用实际数据日期
                data_source=getattr(result.snapshot, 'data_source', 'calculated'),
                fallback_count=getattr(result.snapshot, 'fallback_count', 0),
            )

            response = CalculateRegimeResponse(
                success=True,
                snapshot=corrected_snapshot,
                warnings=result.warnings + warnings_list,
                error=None,
                raw_data=raw_data,
                intermediate_data=intermediate_data
            )

            # 易用性改进 - Redis缓存层：缓存计算结果
            try:
                from shared.infrastructure.cache_service import CacheService

                cache_data = {
                    'growth_momentum_z': corrected_snapshot.growth_momentum_z,
                    'inflation_momentum_z': corrected_snapshot.inflation_momentum_z,
                    'distribution': corrected_snapshot.distribution,
                    'dominant_regime': corrected_snapshot.dominant_regime,
                    'confidence': corrected_snapshot.confidence,
                    'observed_at': corrected_snapshot.observed_at.isoformat(),
                    'warnings': result.warnings + warnings_list,
                    'raw_data': raw_data,
                    'intermediate_data': intermediate_data,
                }

                if not is_pytest_env:
                    CacheService.set_regime(
                        as_of_date=request.as_of_date.isoformat(),
                        growth_indicator=request.growth_indicator,
                        inflation_indicator=request.inflation_indicator,
                        data=cache_data,
                    )
                    logger.info(f"Regime计算结果已缓存: {request.as_of_date}")
            except Exception as e:
                logger.warning(f"缓存设置失败: {e}，不影响结果返回")

            return response

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
    ) -> list[CalculateRegimeResponse]:
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
        available_dates = sorted(available_dates)
        if len(available_dates) > 12:
            available_dates = available_dates[-12:]

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


# ==================== V2 Use Case (Level-based) ====================

@dataclass
class CalculateRegimeV2Request:
    """计算 Regime V2 的请求 DTO"""
    as_of_date: date
    use_pit: bool = False
    growth_indicator: str = "PMI"
    inflation_indicator: str = "CPI"
    data_source: str | None = None
    skip_cache: bool = False


@dataclass
class CalculateRegimeV2Response:
    """计算 Regime V2 的响应 DTO"""
    success: bool
    result: Optional["RegimeCalculationResult"]
    warnings: list[str]
    error: str | None = None
    raw_data: dict | None = None


class CalculateRegimeV2UseCase:
    """
    计算 Regime V2 的用例（基于绝对水平）

    职责：
    1. 使用 V2 服务（水平判定法）计算 Regime
    2. 从数据库读取阈值配置
    3. 返回包含趋势预测的结果
    """

    MIN_DATA_POINTS = 3  # V2 只需要最近的数据

    def __init__(self, repository):
        self.repository = repository

    def _load_threshold_config(self) -> "ThresholdConfig":
        """从数据库加载阈值配置"""
        from ..domain.services_v2 import ThresholdConfig
        from ..infrastructure.models import RegimeIndicatorThreshold, RegimeThresholdConfig

        try:
            # 获取激活的配置
            config_model = RegimeThresholdConfig._default_manager.filter(is_active=True).first()

            if config_model:
                # 读取各指标的阈值
                thresholds = {
                    t.indicator_code: t
                    for t in config_model.thresholds.all()
                }

                # 获取 PMI 阈值
                pmi_threshold = thresholds.get('PMI')
                pmi_expansion = pmi_threshold.level_high if pmi_threshold else 50.0
                pmi_contraction = pmi_threshold.level_low if pmi_threshold else 50.0

                # 获取 CPI 阈值
                cpi_threshold = thresholds.get('CPI')
                if cpi_threshold:
                    cpi_high = cpi_threshold.level_high
                    cpi_low = cpi_threshold.level_low
                    cpi_deflation = 0.0  # 默认值
                else:
                    cpi_high = 2.0
                    cpi_low = 1.0
                    cpi_deflation = 0.0

                # 获取趋势权重
                trend_config = config_model.trend_indicators.filter(indicator_code='PMI').first()
                momentum_weight = trend_config.trend_weight if trend_config else 0.3

                return ThresholdConfig(
                    pmi_expansion=pmi_expansion,
                    pmi_contraction=pmi_contraction,
                    cpi_high=cpi_high,
                    cpi_low=cpi_low,
                    cpi_deflation=cpi_deflation,
                    momentum_weight=momentum_weight
                )
        except Exception as e:
            logger.warning(f"Failed to load threshold config from database: {e}, using defaults")

        # 返回默认配置
        return ThresholdConfig()

    def execute(self, request: CalculateRegimeV2Request) -> CalculateRegimeV2Response:
        """执行 Regime V2 计算"""
        warnings_list = []

        try:
            from ..domain.services_v2 import RegimeCalculatorV2

            # 转换指标代码
            growth_code = self.repository.GROWTH_INDICATORS.get(request.growth_indicator, request.growth_indicator)
            inflation_code = self.repository.INFLATION_INDICATORS.get(request.inflation_indicator, request.inflation_indicator)

            # 获取数据序列（只需要最近的数据）
            growth_series = self.repository.get_growth_series(
                indicator_code=request.growth_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )

            inflation_series = self.repository.get_inflation_series(
                indicator_code=request.inflation_indicator,
                end_date=request.as_of_date,
                use_pit=request.use_pit,
                source=request.data_source
            )

            if not growth_series or not inflation_series:
                return CalculateRegimeV2Response(
                    success=False,
                    result=None,
                    warnings=[],
                    error="数据不足：需要 PMI 和 CPI 数据"
                )

            # 加载阈值配置
            config = self._load_threshold_config()

            # 使用 V2 计算器
            calculator = RegimeCalculatorV2(config=config)
            result = calculator.calculate(
                pmi_series=growth_series,
                cpi_series=inflation_series,
                as_of_date=request.as_of_date
            )

            # 获取完整数据用于展示
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

            return CalculateRegimeV2Response(
                success=True,
                result=result,
                warnings=result.warnings + warnings_list,
                error=None,
                raw_data=raw_data
            )

        except Exception as e:
            logger.exception(f"Unexpected error during regime V2 calculation: {e}")
            return CalculateRegimeV2Response(
                success=False,
                result=None,
                warnings=warnings_list,
                error=f"计算失败: {str(e)}"
            )
