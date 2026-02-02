"""
Domain Services for Regime Calculation.

纯业务逻辑，只使用 Python 标准库。
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Tuple, Optional


@dataclass(frozen=True)
class RegimeCalculationResult:
    """Regime 计算结果"""
    snapshot: "RegimeSnapshot"
    warnings: List[str]


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
    try:
        return 1.0 / (1.0 + math.exp(-k * x))
    except OverflowError:
        # 防止数值溢出
        return 1.0 if x > 0 else 0.0


def calculate_regime_distribution(
    growth_z: float,
    inflation_z: float,
    k: float = 2.0,
    correlation: float = 0.3
) -> Dict[str, float]:
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
    series: List[float],
    period: int = 3
) -> List[float]:
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
    series: List[float],
    period: int = 3
) -> List[float]:
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
    series: List[float],
    window: int = 60,
    min_periods: int = 24
) -> List[float]:
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


def find_dominant_regime(distribution: Dict[str, float]) -> Tuple[str, float]:
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
        growth_series: List[float],
        inflation_series: List[float],
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
        growth_history: List[float],
        inflation_history: List[float],
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
