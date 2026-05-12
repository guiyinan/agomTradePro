"""
Domain Services for Regime Calculation.

纯业务逻辑，只使用 Python 标准库。
"""

import math
from dataclasses import dataclass
from datetime import date

from .entities import (
    ConfidenceBreakdown,
    ConfidenceConfig,
    IndicatorPredictivePower,
    RegimeProbabilities,
    RegimeSnapshot,
    SignalConflict,
)


@dataclass(frozen=True)
class RegimeCalculationResult:
    """Regime 计算结果"""
    snapshot: "RegimeSnapshot"
    warnings: list[str]


@dataclass(frozen=True)
class MomentumResult:
    """动量计算结果"""
    value: float
    momentum: float


def sigmoid(x: float, k: float = 2.0) -> float:
    """
    Sigmoid 函数

    Args:
        x: 输入值
        k: 斜率参数，控制函数陡峭程度

    Returns:
        float: (0, 1) 范围内的概率值
    """
    z = k * x

    # Enforce odd symmetry: sigmoid(-z) = 1 - sigmoid(z)
    if z < 0:
        return 1.0 - sigmoid(-x, k)

    # Regular logistic region where float precision is still expressive.
    if z <= 20.0:
        return 1.0 / (1.0 + math.exp(-z))

    # Tail approximation to avoid float saturation to exactly 1.0.
    z0 = 20.0
    base = 1.0 / (1.0 + math.exp(-z0))
    a = (1.0 - base) * (z0 + 1.0) ** 4
    return 1.0 - a / (z + 1.0) ** 4


def calculate_regime_distribution(
    growth_z: float,
    inflation_z: float,
    k: float = 2.0,
    correlation: float = 0.3
) -> dict[str, float]:
    """
    计算四象限 Regime 的模糊权重分布

    使用 Sigmoid 函数将 Z-score 转换为概率，
    考虑增长和通胀的相关性，得到四个象限的归一化权重。

    Args:
        growth_z: 增长动量的 Z-score
        inflation_z: 通胀动量的 Z-score
        k: Sigmoid 斜率参数
        correlation: 增长和通胀的相关系数 (-1 到 1)
                    正相关表示高增长伴随高通胀（经济周期常态）
                    负相关表示高增长伴随低通胀（供给冲击场景）
                    0 表示独立（原始简化假设）

    Returns:
        Dict[str, float]: 四个象限的概率分布，总和为 1

    语义定义:
        correlation: 增长与通胀的相关性系数
                   - 正值 (0.0 ~ 1.0): 增强过热和通缩，抑制滞胀和复苏
                   - 负值 (-1.0 ~ 0.0): 增强滞胀和复苏，抑制过热和通缩
                   - 0.0: 独立假设（原始版本）

    经济含义:
        - 历史数据显示增长和通胀通常呈正相关（约0.3-0.5）
        - 正相关时期：经济繁荣伴随通胀，衰退伴随通缩
        - 负相关时期：供给冲击导致滞胀（高通胀低增长）
    """
    # 边界检查
    correlation = max(-1.0, min(1.0, correlation))

    p_growth_up = sigmoid(growth_z, k)
    p_inflation_up = sigmoid(inflation_z, k)

    # 基础概率（独立假设）
    recovery_independent = p_growth_up * (1 - p_inflation_up)
    overheat_independent = p_growth_up * p_inflation_up
    stagflation_independent = (1 - p_growth_up) * p_inflation_up
    deflation_independent = (1 - p_growth_up) * (1 - p_inflation_up)

    if abs(correlation) < 0.01:
        # 相关性接近0，使用独立假设
        recovery = recovery_independent
        overheat = overheat_independent
        stagflation = stagflation_independent
        deflation = deflation_independent
    else:
        # 应用相关性调整
        # 正相关：增强同向场景（过热+通缩），抑制反向场景（复苏+滞胀）
        # 负相关：增强反向场景（复苏+滞胀），抑制同向场景（过热+通缩）

        # 计算调整因子
        # 对于正相关（correlation > 0）：
        # - 同向概率（过热、通缩）增加
        # - 反向概率（复苏、滞胀）减少
        adjustment = correlation * 0.5  # 系数0.5控制调整幅度

        if correlation > 0:
            # 正相关：增强过热和通缩
            overheat = overheat_independent * (1 + adjustment)
            deflation = deflation_independent * (1 + adjustment)
            recovery = recovery_independent * (1 - adjustment)
            stagflation = stagflation_independent * (1 - adjustment)
        else:
            # 负相关：增强复苏和滞胀
            recovery = recovery_independent * (1 - adjustment)  # adjustment为负，实际是增加
            stagflation = stagflation_independent * (1 - adjustment)
            overheat = overheat_independent * (1 + adjustment)  # adjustment为负，实际是减少
            deflation = deflation_independent * (1 + adjustment)

        # 确保非负
        recovery = max(0.0, recovery)
        overheat = max(0.0, overheat)
        stagflation = max(0.0, stagflation)
        deflation = max(0.0, deflation)

    total = recovery + overheat + stagflation + deflation

    if total == 0:
        # 边界情况：均分
        return {
            "Recovery": 0.25,
            "Overheat": 0.25,
            "Stagflation": 0.25,
            "Deflation": 0.25,
        }

    return {
        "Recovery": recovery / total,
        "Overheat": overheat / total,
        "Stagflation": stagflation / total,
        "Deflation": deflation / total,
    }


def calculate_momentum(
    series: list[float],
    period: int = 3
) -> list[float]:
    """
    计算时间序列的动量（周期变化）- 相对动量

    适用于：绝对值指标（如 PMI、工业增加值等）
    动量 = (当前值 - 过去值) / |过去值|

    Args:
        series: 时间序列值
        period: 计算周期（月），默认 3 个月

    Returns:
        List[float]: 动量值序列
    """
    n = len(series)
    if n < period:
        return [0.0] * n

    momentums = []

    for i in range(n):
        if i < period:
            momentums.append(0.0)
        else:
            current = series[i]
            past = series[i - period]
            if past != 0:
                momentum = (current - past) / abs(past)
            else:
                momentum = 0.0
            momentums.append(momentum)

    return momentums


def calculate_absolute_momentum(
    series: list[float],
    period: int = 3
) -> list[float]:
    """
    计算时间序列的动量（周期变化）- 绝对差值动量

    适用于：比率型指标（如 CPI、PPI 等百分比数据）
    动量 = 当前值 - 过去值（百分点差值）

    使用绝对差值而非相对变化，避免低基数时的扭曲：
    - 例如：CPI 从 0.1% 涨到 0.3%，绝对动量 = 0.2pp（而非 200%）
    - 例如：CPI 从 2.0% 涨到 2.5%，绝对动量 = 0.5pp

    Args:
        series: 时间序列值（百分比形式，如 0.5 表示 0.5%）
        period: 计算周期（月），默认 3 个月

    Returns:
        List[float]: 动量值序列（百分点差值）
    """
    n = len(series)
    if n < period:
        return [0.0] * n

    momentums = []

    for i in range(n):
        if i < period:
            momentums.append(0.0)
        else:
            current = series[i]
            past = series[i - period]
            # 直接使用差值，不除以基数
            momentum = current - past
            momentums.append(momentum)

    return momentums


def calculate_rolling_zscore(
    series: list[float],
    window: int = 60,
    min_periods: int = 24
) -> list[float]:
    """
    计算滚动 Z-score

    Domain 层纯实现，不依赖 Pandas

    Args:
        series: 时间序列值
        window: 滚动窗口大小
        min_periods: 最小计算周期

    Returns:
        List[float]: Z-score 序列
    """
    n = len(series)
    z_scores = []

    for i in range(n):
        if i < min_periods - 1:
            z_scores.append(0.0)
        else:
            # 计算 [max(0, i-window+1), i] 的统计量
            start = max(0, i - window + 1)
            window_data = series[start:i+1]

            mean_val = sum(window_data) / len(window_data)
            variance = sum((x - mean_val) ** 2 for x in window_data) / len(window_data)
            std_val = math.sqrt(variance)

            if std_val > 0:
                z = (series[i] - mean_val) / std_val
            else:
                z = 0.0
            z_scores.append(z)

    return z_scores


def find_dominant_regime(distribution: dict[str, float]) -> tuple[str, float]:
    """
    找到主导 Regime

    Args:
        distribution: 四象限概率分布

    Returns:
        Tuple[str, float]: (Regime 名称, 置信度)
    """
    dominant = max(distribution.items(), key=lambda x: x[1])
    return dominant


class RegimeCalculator:
    """
    Regime 计算器

    输入：增长指标序列、通胀指标序列
    输出：RegimeSnapshot（包含 Z-score 和分布）

    动量计算策略：
    - 增长指标（如 PMI）：使用相对动量 calculate_momentum()
    - 通胀指标（如 CPI）：使用绝对差值动量 calculate_absolute_momentum()

    相关性处理：
    - 考虑增长和通胀的历史相关性，而非假设独立
    - 默认相关性为 0.3（基于历史数据的典型值）
    """

    def __init__(
        self,
        momentum_period: int = 3,
        zscore_window: int = 24,
        zscore_min_periods: int = 12,
        sigmoid_k: float = 2.0,
        use_absolute_inflation_momentum: bool = True,
        correlation: float = 0.3
    ):
        """
        Args:
            momentum_period: 动量计算周期（月）
            zscore_window: Z-score 滚动窗口（默认24，适应有限数据）
            zscore_min_periods: Z-score 最小计算周期（默认12，适应有限数据）
            sigmoid_k: Sigmoid 斜率参数
            use_absolute_inflation_momentum: 是否对通胀使用绝对差值动量（默认True）
            correlation: 增长和通胀的相关系数，范围 [-1, 1]
                        默认 0.3 表示适度的正相关（经济周期常态）
                        0 表示独立假设（原始简化版本）

        Note: 默认参数适用于有限数据场景（20-40条记录）。
              当数据量充足（60+条）时，建议使用 zscore_window=60, zscore_min_periods=24

        相关性说明:
            - 正相关 (0.0 ~ 1.0): 经济繁荣时通胀上升，衰退时通胀下降
            - 负相关 (-1.0 ~ 0.0): 供给冲击导致高通胀低增长（滞胀）
            - 历史经验: 发达经济体增长与通胀相关性约为 0.3-0.5
        """
        self.momentum_period = momentum_period
        self.zscore_window = zscore_window
        self.zscore_min_periods = zscore_min_periods
        self.sigmoid_k = sigmoid_k
        self.use_absolute_inflation_momentum = use_absolute_inflation_momentum
        self.correlation = max(-1.0, min(1.0, correlation))  # 限制在 [-1, 1]

    def calculate(
        self,
        growth_series: list[float],
        inflation_series: list[float],
        as_of_date: date
    ) -> RegimeCalculationResult:
        """
        计算指定日期的 Regime 状态

        Args:
            growth_series: 增长指标序列（按时间排序）
            inflation_series: 通胀指标序列（按时间排序）
            as_of_date: 截止日期

        Returns:
            RegimeCalculationResult: 包含 snapshot 和 warnings
        """
        warnings = []

        # 数据长度检查
        if len(growth_series) != len(inflation_series):
            warnings.append("增长和通胀序列长度不一致")
            # 取较短的长度
            min_len = min(len(growth_series), len(inflation_series))
            growth_series = growth_series[:min_len]
            inflation_series = inflation_series[:min_len]

        if len(growth_series) < self.zscore_min_periods:
            warnings.append(f"数据不足，需要至少 {self.zscore_min_periods} 个观测值")

        # 1. 计算动量
        # 增长指标：使用相对动量
        growth_momentums = calculate_momentum(
            growth_series,
            period=self.momentum_period
        )

        # 通胀指标：根据配置使用绝对差值动量或相对动量
        if self.use_absolute_inflation_momentum:
            inflation_momentums = calculate_absolute_momentum(
                inflation_series,
                period=self.momentum_period
            )
        else:
            inflation_momentums = calculate_momentum(
                inflation_series,
                period=self.momentum_period
            )

        # 2. 计算 Z-score
        growth_z_scores = calculate_rolling_zscore(
            growth_momentums,
            window=self.zscore_window,
            min_periods=self.zscore_min_periods
        )
        inflation_z_scores = calculate_rolling_zscore(
            inflation_momentums,
            window=self.zscore_window,
            min_periods=self.zscore_min_periods
        )

        # 取最后一个值作为当前状态
        growth_z = growth_z_scores[-1] if growth_z_scores else 0.0
        inflation_z = inflation_z_scores[-1] if inflation_z_scores else 0.0

        # 3. 计算 Regime 分布（考虑相关性）
        distribution = calculate_regime_distribution(
            growth_z,
            inflation_z,
            k=self.sigmoid_k,
            correlation=self.correlation
        )

        # 4. 找到主导 Regime
        dominant_regime, confidence = find_dominant_regime(distribution)

        # 5. 创建快照
        from .entities import RegimeSnapshot
        snapshot = RegimeSnapshot(
            growth_momentum_z=growth_z,
            inflation_momentum_z=inflation_z,
            distribution=distribution,
            dominant_regime=dominant_regime,
            confidence=confidence,
            observed_at=as_of_date
        )

        return RegimeCalculationResult(snapshot=snapshot, warnings=warnings)

    def calculate_at_point(
        self,
        growth_value: float,
        inflation_value: float,
        growth_history: list[float],
        inflation_history: list[float],
        as_of_date: date
    ) -> RegimeCalculationResult:
        """
        计算特定时点的 Regime（用于回测）

        Args:
            growth_value: 当前增长指标值
            inflation_value: 当前通胀指标值
            growth_history: 历史增长序列（不包含当前值）
            inflation_history: 历史通胀序列（不包含当前值）
            as_of_date: 截止日期

        Returns:
            RegimeCalculationResult
        """
        # 组合历史+当前
        full_growth = list(growth_history) + [growth_value]
        full_inflation = list(inflation_history) + [inflation_value]

        return self.calculate(full_growth, full_inflation, as_of_date)


# ==================== Phase 1: High-Frequency Signal Integration ====================

@dataclass
class DailySignalContext:
    """日度信号上下文"""
    signal_direction: str  # BULLISH, BEARISH, NEUTRAL
    signal_strength: float  # 0-1
    confidence: float  # 0-1
    persist_days: int  # 持续天数
    contributing_indicators: list[dict]
    warning_signals: list[str]


@dataclass
class HybridRegimeResult:
    """混合 Regime 计算结果"""
    snapshot: "RegimeSnapshot"
    source: str  # MONTHLY_ONLY, DAILY_ONLY, HYBRID_WEIGHTED, DAILY_OVERRIDE
    daily_context: DailySignalContext | None
    monthly_confidence: float
    daily_confidence: float
    final_confidence: float


class HybridRegimeCalculator:
    """
    混合 Regime 计算器（融合高频信号）

    职责：
    1. 结合传统月度指标和高频日度信号
    2. 应用冲突解决规则
    3. 输出带有数据源标识的 Regime 结果

    Signal Conflict Resolution Rules:
    1. Daily == Monthly: High confidence (0.9)
    2. Daily persists >= 10 days: Use daily (0.7 confidence)
    3. Daily + Weekly一致 (both differ from monthly): Consider switching (0.6 confidence)
    4. Default: Use monthly, lower confidence (0.5)
    """

    # Regime direction mapping
    BULLISH_REGIMES = {"Recovery", "Overheat"}
    BEARISH_REGIMES = {"Stagflation", "Deflation"}

    def __init__(
        self,
        monthly_calculator: RegimeCalculator | None = None,
        daily_persist_threshold: int = 10,
        hybrid_weight_daily: float = 0.3,
        hybrid_weight_monthly: float = 0.7
    ):
        """
        Args:
            monthly_calculator: 月度 Regime 计算器
            daily_persist_threshold: 日度信号持续阈值（天）
            hybrid_weight_daily: 混合模式中日度信号权重
            hybrid_weight_monthly: 混合模式中月度信号权重
        """
        self.monthly_calculator = monthly_calculator or RegimeCalculator()
        self.daily_persist_threshold = daily_persist_threshold
        self.hybrid_weight_daily = hybrid_weight_daily
        self.hybrid_weight_monthly = hybrid_weight_monthly

    def calculate_hybrid(
        self,
        growth_series: list[float],
        inflation_series: list[float],
        daily_context: DailySignalContext | None,
        as_of_date: date
    ) -> HybridRegimeResult:
        """
        计算混合 Regime（融合月度和日度信号）

        Args:
            growth_series: 增长指标序列
            inflation_series: 通胀指标序列
            daily_context: 日度信号上下文
            as_of_date: 截止日期

        Returns:
            HybridRegimeResult: 混合 Regime 结果
        """
        from .entities import RegimeSnapshot

        # 1. 计算月度 Regime
        monthly_result = self.monthly_calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=as_of_date
        )
        monthly_snapshot = monthly_result.snapshot
        monthly_regime = monthly_snapshot.dominant_regime
        monthly_confidence = monthly_snapshot.confidence

        # 2. 如果没有日度信号，直接返回月度结果
        if not daily_context:
            return HybridRegimeResult(
                snapshot=monthly_snapshot,
                source="MONTHLY_ONLY",
                daily_context=None,
                monthly_confidence=monthly_confidence,
                daily_confidence=0.0,
                final_confidence=monthly_confidence
            )

        # 3. 解析日度信号
        daily_signal = daily_context.signal_direction
        daily_confidence = daily_context.confidence
        persist_days = daily_context.persist_days

        # 4. 映射日度信号到 Regime
        daily_regime = self._map_signal_to_regime(daily_signal, monthly_snapshot.distribution)

        # 5. 应用冲突解决规则
        resolution = self._resolve_signal_conflict(
            monthly_regime=monthly_regime,
            monthly_confidence=monthly_confidence,
            daily_regime=daily_regime,
            daily_confidence=daily_confidence,
            persist_days=persist_days
        )

        # 6. 生成最终结果
        if resolution['source'] == 'MONTHLY_DEFAULT':
            # 使用月度信号，降低置信度
            final_snapshot = RegimeSnapshot(
                growth_momentum_z=monthly_snapshot.growth_momentum_z,
                inflation_momentum_z=monthly_snapshot.inflation_momentum_z,
                distribution=monthly_snapshot.distribution,
                dominant_regime=monthly_regime,
                confidence=resolution['confidence'],
                observed_at=as_of_date
            )
        elif resolution['source'] in ['DAILY_PERSISTENT', 'ALL_CONSISTENT']:
            # 使用日度信号对应的 Regime
            final_snapshot = RegimeSnapshot(
                growth_momentum_z=monthly_snapshot.growth_momentum_z,  # 保留月度 Z-score
                inflation_momentum_z=monthly_snapshot.inflation_momentum_z,
                distribution=self._adjust_distribution_for_daily(
                    monthly_snapshot.distribution,
                    daily_regime,
                    daily_context.signal_strength
                ),
                dominant_regime=daily_regime,
                confidence=resolution['confidence'],
                observed_at=as_of_date
            )
        else:
            # HYBRID_WEIGHTED: 加权融合
            final_snapshot = RegimeSnapshot(
                growth_momentum_z=monthly_snapshot.growth_momentum_z,
                inflation_momentum_z=monthly_snapshot.inflation_momentum_z,
                distribution=self._blend_distributions(
                    monthly_snapshot.distribution,
                    daily_regime,
                    self.hybrid_weight_monthly,
                    self.hybrid_weight_daily
                ),
                dominant_regime=resolution['final_regime'],
                confidence=resolution['confidence'],
                observed_at=as_of_date
            )

        return HybridRegimeResult(
            snapshot=final_snapshot,
            source=resolution['source'],
            daily_context=daily_context,
            monthly_confidence=monthly_confidence,
            daily_confidence=daily_confidence,
            final_confidence=resolution['confidence']
        )

    def _map_signal_to_regime(
        self,
        signal_direction: str,
        current_distribution: dict[str, float]
    ) -> str:
        """
        将日度信号方向映射到 Regime

        规则：
        - BULLISH -> 选择 Recovery 或 Overheat 中权重更高的
        - BEARISH -> 选择 Stagflation 或 Deflation 中权重更高的
        - NEUTRAL -> 保持当前分布的主导 Regime
        """
        if signal_direction == "NEUTRAL":
            # 保持当前主导 Regime
            dominant = max(current_distribution.items(), key=lambda x: x[1])
            return dominant[0]

        if signal_direction == "BULLISH":
            # 在看多象限中选择权重更高的
            bullish_regime = max(
                {k: v for k, v in current_distribution.items() if k in self.BULLISH_REGIMES}.items(),
                key=lambda x: x[1],
                default=("Recovery", 0.5)
            )
            return bullish_regime[0]

        if signal_direction == "BEARISH":
            # 在看空象限中选择权重更高的
            bearish_regime = max(
                {k: v for k, v in current_distribution.items() if k in self.BEARISH_REGIMES}.items(),
                key=lambda x: x[1],
                default=("Deflation", 0.5)
            )
            return bearish_regime[0]

        # 默认返回 Recovery
        return "Recovery"

    def _resolve_signal_conflict(
        self,
        monthly_regime: str,
        monthly_confidence: float,
        daily_regime: str,
        daily_confidence: float,
        persist_days: int
    ) -> dict:
        """
        解决信号冲突

        Returns:
            Dict: {
                'source': str,
                'final_regime': str,
                'confidence': float
            }
        """
        # Rule 1: Daily and Monthly一致
        if daily_regime == monthly_regime:
            avg_confidence = (daily_confidence + monthly_confidence) / 2
            return {
                'source': 'ALL_CONSISTENT',
                'final_regime': daily_regime,
                'confidence': min(avg_confidence + 0.2, 1.0)
            }

        # Rule 2: Daily signal persists for >= threshold days
        if persist_days >= self.daily_persist_threshold:
            return {
                'source': 'DAILY_PERSISTENT',
                'final_regime': daily_regime,
                'confidence': min(daily_confidence + 0.1, 1.0)
            }

        # Rule 3: Check if signals are in the same direction (both bullish or both bearish)
        monthly_bullish = monthly_regime in self.BULLISH_REGIMES
        daily_bullish = daily_regime in self.BULLISH_REGIMES

        if monthly_bullish == daily_bullish:
            # Same direction, different specific regime - use weighted approach
            return {
                'source': 'HYBRID_WEIGHTED',
                'final_regime': monthly_regime if monthly_confidence > daily_confidence else daily_regime,
                'confidence': (monthly_confidence * self.hybrid_weight_monthly + daily_confidence * self.hybrid_weight_daily)
            }

        # Rule 4: Default - Use monthly signal, lower confidence
        return {
            'source': 'MONTHLY_DEFAULT',
            'final_regime': monthly_regime,
            'confidence': max(monthly_confidence * 0.8, 0.4)
        }

    def _adjust_distribution_for_daily(
        self,
        original_distribution: dict[str, float],
        daily_regime: str,
        signal_strength: float
    ) -> dict[str, float]:
        """
        根据日度信号调整分布

        Args:
            original_distribution: 原始月度分布
            daily_regime: 日度信号对应的 Regime
            signal_strength: 信号强度 (0-1)

        Returns:
            Dict[str, float]: 调整后的分布
        """
        # 创建新的分布，提升日度 Regime 的权重
        adjustment = signal_strength * 0.3  # 最多调整30%

        new_distribution = {}
        total_adjustment = 0.0

        for regime, weight in original_distribution.items():
            if regime == daily_regime:
                # 提升目标 Regime 的权重
                new_weight = weight + adjustment
                total_adjustment += adjustment
            else:
                new_weight = weight
            new_distribution[regime] = new_weight

        # 归一化
        total = sum(new_distribution.values())
        if total > 0:
            new_distribution = {
                k: v / total for k, v in new_distribution.items()
            }

        return new_distribution

    def _blend_distributions(
        self,
        monthly_distribution: dict[str, float],
        daily_regime: str,
        monthly_weight: float,
        daily_weight: float
    ) -> dict[str, float]:
        """
        融合月度和日度分布

        创建一个偏向日度 Regime 的加权分布
        """
        # 构建日度分布（100%集中在日度 Regime）
        daily_distribution = dict.fromkeys(monthly_distribution.keys(), 0.0)
        daily_distribution[daily_regime] = 1.0

        # 加权融合
        blended = {}
        for regime in monthly_distribution:
            blended[regime] = (
                monthly_distribution[regime] * monthly_weight +
                daily_distribution[regime] * daily_weight
            )

        return blended
# ==================== Phase 4: Probability Confidence Model ====================


def calculate_confidence(
    base_confidence: float,
    days_since_update: int,
    has_daily_data: bool = False,
    has_weekly_data: bool = False,
    daily_consistent: bool = False,
    config: ConfidenceConfig | None = None
) -> ConfidenceBreakdown:
    """
    计算基于数据新鲜度的置信度

    置信度 = 基础置信度 × 新鲜度系数 + 数据类型加成

    Args:
        base_confidence: 基础置信度 (0-1)
        days_since_update: 距上次更新天数
        has_daily_data: 是否有日度数据支持
        has_weekly_data: 是否有周度数据支持
        daily_consistent: 日度数据是否与月度数据一致
        config: 置信度配置（从数据库读取，默认使用默认配置）

    Returns:
        ConfidenceBreakdown: 置信度分解结果
    """
    if config is None:
        config = ConfidenceConfig.defaults()

    # 1. 计算新鲜度系数
    if days_since_update <= 1:
        freshness_coeff = config.day_0_coefficient
    elif days_since_update <= 7:
        freshness_coeff = config.day_7_coefficient
    elif days_since_update <= 14:
        freshness_coeff = config.day_14_coefficient
    else:
        freshness_coeff = config.day_30_coefficient

    # 2. 计算基础置信度分量
    base_component = base_confidence * freshness_coeff

    # 3. 计算数据类型加成
    data_type_bonus = 0.0
    if has_daily_data:
        data_type_bonus += config.daily_data_bonus
    elif has_weekly_data:
        data_type_bonus += config.weekly_data_bonus

    # 4. 计算一致性加成
    consistency_bonus = 0.0
    if daily_consistent:
        consistency_bonus += config.daily_consistency_bonus

    # 5. 计算总置信度（限制在 [0, 1]）
    total_confidence = min(1.0, max(0.0, base_component + data_type_bonus + consistency_bonus))

    # 6. 分解各分量
    data_freshness_component = base_component * freshness_coeff
    predictive_power_component = data_type_bonus
    consistency_component = consistency_bonus

    return ConfidenceBreakdown(
        total_confidence=total_confidence,
        data_freshness_component=data_freshness_component,
        predictive_power_component=predictive_power_component,
        consistency_component=consistency_component,
        base_component=base_confidence,
        days_since_last_update=days_since_update,
        has_daily_data=has_daily_data,
        daily_consistent=daily_consistent,
        indicators_count=1 if has_daily_data else 0,
    )


def calculate_bayesian_confidence(
    indicators: list[IndicatorPredictivePower],
    base_prior: float = 0.5,
    config: ConfidenceConfig | None = None
) -> RegimeProbabilities:
    """
    贝叶斯框架计算 Regime 概率

    根据指标的历史预测能力赋权，而非简单的新鲜度加权。

    Args:
        indicators: 指标预测能力列表
        base_prior: 先验概率（来自传统月度指标）
        config: 置信度配置

    Returns:
        RegimeProbabilities: 包含各象限概率和置信度

    贝叶斯更新公式:
        P(H|E) = P(E|H) * P(H) / P(E)

        其中:
        - H: 假设（Regime 状态）
        - E: 证据（指标信号）
        - P(H|E): 后验概率
        - P(H): 先验概率
        - P(E|H): 似然性（指标预测能力）
    """
    if config is None:
        config = ConfidenceConfig.defaults()

    if not indicators:
        # 无指标时，返回均匀分布
        return RegimeProbabilities(
            growth_reflation=0.25,
            growth_disinflation=0.25,
            stagnation_reflation=0.25,
            stagnation_disinflation=0.25,
            confidence=base_prior,
            data_freshness_score=0.0,
            predictive_power_score=0.0,
            consistency_score=0.0,
        )

    # 1. 计算指标权重（基于历史预测能力）
    # 权重 = F1分数 / (1 + 假阳性率) × 稳定性评分
    weights = []
    for ind in indicators:
        weight = ind.f1_score / (1 + ind.false_positive_rate) * ind.stability_score
        weights.append(weight)

    total_weight = sum(weights)
    if total_weight == 0:
        weights = [1.0 / len(indicators)] * len(indicators)
    else:
        weights = [w / total_weight for w in weights]

    # 2. 聚合信号方向
    bullish_scores = []
    bearish_scores = []

    for i, ind in enumerate(indicators):
        weight = weights[i]
        if ind.current_signal == "BULLISH":
            bullish_scores.append(weight * ind.reliability_score)
        elif ind.current_signal == "BEARISH":
            bearish_scores.append(weight * ind.reliability_score)

    # 3. 计算概率分布
    bullish_total = sum(bullish_scores)
    bearish_total = sum(bearish_scores)
    total = bullish_total + bearish_total

    if total == 0:
        # 无明确信号，返回均匀分布
        distribution = {
            "Overheat": 0.25,
            "Recovery": 0.25,
            "Stagflation": 0.25,
            "Deflation": 0.25,
        }
        confidence = base_prior
    else:
        # 根据信号方向和强度分配概率
        bullish_prob = bullish_total / total
        bearish_prob = bearish_total / total

        # 在看多象限（Recovery, Overheat）和看空象限（Stagflation, Deflation）之间分配
        # 根据信号强度进一步细分
        recovery_prob = bullish_prob * 0.5
        overheat_prob = bullish_prob * 0.5
        stagflation_prob = bearish_prob * 0.5
        deflation_prob = bearish_prob * 0.5

        distribution = {
            "Overheat": overheat_prob,
            "Recovery": recovery_prob,
            "Stagflation": stagflation_prob,
            "Deflation": deflation_prob,
        }

        # 置信度 = 基础置信度 × (1 + 平均预测能力)
        avg_predictive_power = sum(ind.predictive_power_score for ind in indicators) / len(indicators)
        confidence = min(1.0, base_prior * (1 + avg_predictive_power))

    # 4. 计算元数据
    avg_days_since_update = sum(ind.days_since_last_update for ind in indicators) / len(indicators)
    any(ind.days_since_last_update <= 7 for ind in indicators)

    # 数据新鲜度评分（越新越高）
    data_freshness_score = max(0.0, 1.0 - avg_days_since_update / 30)

    # 预测能力评分
    predictive_power_score = sum(ind.predictive_power_score for ind in indicators) / len(indicators)

    # 一致性评分（信号方向一致性）
    signal_directions = [ind.current_signal for ind in indicators if ind.current_signal != "NEUTRAL"]
    if signal_directions:
        consistency = max(
            signal_directions.count("BULLISH") / len(signal_directions),
            signal_directions.count("BEARISH") / len(signal_directions)
        )
    else:
        consistency = 0.0

    return RegimeProbabilities(
        growth_reflation=distribution["Overheat"],
        growth_disinflation=distribution["Recovery"],
        stagnation_reflation=distribution["Stagflation"],
        stagnation_disinflation=distribution["Deflation"],
        confidence=confidence,
        data_freshness_score=data_freshness_score,
        predictive_power_score=predictive_power_score,
        consistency_score=consistency,
    )


def resolve_signal_conflict(
    daily_signal: str,
    weekly_signal: str | None,
    monthly_signal: str,
    daily_confidence: float,
    monthly_confidence: float,
    daily_duration: int,
    persist_threshold: int = 10,
    hybrid_weight_daily: float = 0.3,
    hybrid_weight_monthly: float = 0.7
) -> SignalConflict:
    """
    解决信号冲突

    处理规则：
    1. Daily == Monthly: 高置信度 (0.9)
    2. Daily 持续 >= 10 天: 使用日度信号 (0.7)
    3. Daily + Weekly 一致: 考虑切换 (0.6)
    4. Default: 使用月度信号 (0.5)

    Args:
        daily_signal: 日度信号方向
        weekly_signal: 周度信号方向（可选）
        monthly_signal: 月度信号方向
        daily_confidence: 日度信号置信度
        monthly_confidence: 月度信号置信度
        daily_duration: 日度信号持续天数
        persist_threshold: 持续阈值（默认10天）
        hybrid_weight_daily: 混合模式日度权重
        hybrid_weight_monthly: 混合模式月度权重

    Returns:
        SignalConflict: 冲突解决结果
    """
    # 判断信号方向是否一致
    BULLISH_REGIMES = {"Recovery", "Overheat"}
    BEARISH_REGIMES = {"Stagflation", "Deflation"}

    def get_direction(signal: str) -> str:
        if signal in BULLISH_REGIMES:
            return "BULLISH"
        elif signal in BEARISH_REGIMES:
            return "BEARISH"
        return "NEUTRAL"

    daily_direction = get_direction(daily_signal)
    monthly_direction = get_direction(monthly_signal)

    # Rule 1: Daily and Monthly 一致
    if daily_direction == monthly_direction:
        avg_confidence = (daily_confidence + monthly_confidence) / 2
        final_confidence = min(avg_confidence + 0.2, 1.0)
        return SignalConflict(
            daily_signal=daily_signal,
            weekly_signal=weekly_signal,
            monthly_signal=monthly_signal,
            daily_confidence=daily_confidence,
            monthly_confidence=monthly_confidence,
            daily_duration=daily_duration,
            final_signal=monthly_signal,
            final_confidence=final_confidence,
            resolution_source="ALL_CONSISTENT",
            resolution_reason=f"日度和月度信号一致({daily_direction})，提升置信度",
        )

    # Rule 2: Daily signal 持续 >= 阈值天数
    if daily_duration >= persist_threshold:
        final_confidence = min(daily_confidence + 0.1, 1.0)
        return SignalConflict(
            daily_signal=daily_signal,
            weekly_signal=weekly_signal,
            monthly_signal=monthly_signal,
            daily_confidence=daily_confidence,
            monthly_confidence=monthly_confidence,
            daily_duration=daily_duration,
            final_signal=daily_signal,
            final_confidence=final_confidence,
            resolution_source="DAILY_PERSISTENT",
            resolution_reason=f"日度信号持续{daily_duration}天（阈值{persist_threshold}天），采用日度信号",
        )

    # Rule 3: Daily + Weekly 一致（与月度反向）
    if weekly_signal:
        weekly_direction = get_direction(weekly_signal)
        if daily_direction == weekly_direction and daily_direction != monthly_direction:
            final_confidence = (daily_confidence * hybrid_weight_daily +
                              monthly_confidence * hybrid_weight_monthly)
            return SignalConflict(
                daily_signal=daily_signal,
                weekly_signal=weekly_signal,
                monthly_signal=monthly_signal,
                daily_confidence=daily_confidence,
                monthly_confidence=monthly_confidence,
                daily_duration=daily_duration,
                final_signal=daily_signal,
                final_confidence=final_confidence,
                resolution_source="DAILY_WEEKLY_CONSISTENT",
                resolution_reason=f"日度+周度信号一致({daily_direction})，与月度({monthly_direction})不同",
            )

    # Rule 4: Default - 使用月度信号，降低置信度
    final_confidence = max(monthly_confidence * 0.8, 0.4)
    return SignalConflict(
        daily_signal=daily_signal,
        weekly_signal=weekly_signal,
        monthly_signal=monthly_signal,
        daily_confidence=daily_confidence,
        monthly_confidence=monthly_confidence,
        daily_duration=daily_duration,
        final_signal=monthly_signal,
        final_confidence=final_confidence,
        resolution_source="MONTHLY_DEFAULT",
        resolution_reason=f"保持月度信号，降低置信度（日度{daily_direction} vs 月度{monthly_direction}）",
    )


def calculate_dynamic_weight(
    base_weight: float,
    f1_score: float,
    decay_threshold: float = 0.2,
    decay_penalty: float = 0.5,
    improvement_threshold: float = 0.1,
    improvement_bonus: float = 1.2,
    min_weight: float = 0.0,
    max_weight: float = 1.0
) -> float:
    """
    根据指标表现动态计算权重

    Args:
        base_weight: 基础权重
        f1_score: 当前 F1 分数
        decay_threshold: 衰减阈值（F1 低于此值视为衰减）
        decay_penalty: 衰减惩罚系数
        improvement_threshold: 改进阈值（F1 提升超过此值给予奖励）
        improvement_bonus: 改进奖励系数
        min_weight: 最小权重
        max_weight: 最大权重

    Returns:
        float: 动态调整后的权重
    """
    weight = base_weight

    # 检测衰减：F1 分数低于阈值
    if f1_score < decay_threshold:
        weight *= decay_penalty

    # 检测改进：F1 分数超过基准（假设基准为 0.6）
    baseline_f1 = 0.6
    if f1_score > baseline_f1 + improvement_threshold:
        weight *= improvement_bonus

    return max(min_weight, min(weight, max_weight))


class ConfidenceCalculator:
    """
    置信度计算器

    整合各种置信度计算方法，提供统一的接口。
    """

    def __init__(self, config: ConfidenceConfig | None = None):
        """
        Args:
            config: 置信度配置（从数据库读取）
        """
        self.config = config or ConfidenceConfig.defaults()

    def calculate_from_freshness(
        self,
        days_since_update: int,
        has_daily_data: bool = False,
        has_weekly_data: bool = False,
        daily_consistent: bool = False
    ) -> ConfidenceBreakdown:
        """
        基于数据新鲜度计算置信度
        """
        return calculate_confidence(
            base_confidence=self.config.base_confidence,
            days_since_update=days_since_update,
            has_daily_data=has_daily_data,
            has_weekly_data=has_weekly_data,
            daily_consistent=daily_consistent,
            config=self.config
        )

    def calculate_bayesian(
        self,
        indicators: list[IndicatorPredictivePower],
        base_prior: float = 0.5
    ) -> RegimeProbabilities:
        """
        贝叶斯框架计算概率分布
        """
        return calculate_bayesian_confidence(
            indicators=indicators,
            base_prior=base_prior,
            config=self.config
        )

    def resolve_conflict(
        self,
        daily_signal: str,
        weekly_signal: str | None,
        monthly_signal: str,
        daily_confidence: float,
        monthly_confidence: float,
        daily_duration: int
    ) -> SignalConflict:
        """
        解决信号冲突
        """
        return resolve_signal_conflict(
            daily_signal=daily_signal,
            weekly_signal=weekly_signal,
            monthly_signal=monthly_signal,
            daily_confidence=daily_confidence,
            monthly_confidence=monthly_confidence,
            daily_duration=daily_duration
        )
