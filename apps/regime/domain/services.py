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
    k: float = 2.0
) -> Dict[str, float]:
    """
    计算四象限 Regime 的模糊权重分布

    使用 Sigmoid 函数将 Z-score 转换为概率，
    得到四个象限的归一化权重。

    Args:
        growth_z: 增长动量的 Z-score
        inflation_z: 通胀动量的 Z-score
        k: Sigmoid 斜率参数

    Returns:
        Dict[str, float]: 四个象限的概率分布，总和为 1
    """
    p_growth_up = sigmoid(growth_z, k)
    p_inflation_up = sigmoid(inflation_z, k)

    recovery = p_growth_up * (1 - p_inflation_up)
    overheat = p_growth_up * p_inflation_up
    stagflation = (1 - p_growth_up) * p_inflation_up
    deflation = (1 - p_growth_up) * (1 - p_inflation_up)

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
    计算时间序列的动量（周期变化）

    Args:
        series: 时间序列值
        period: 计算周期（月），默认 3 个月

    Returns:
        List[float]: 动量值序列（前面 period-1 个值为 None）
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
    """

    def __init__(
        self,
        momentum_period: int = 3,
        zscore_window: int = 60,
        zscore_min_periods: int = 24,
        sigmoid_k: float = 2.0
    ):
        """
        Args:
            momentum_period: 动量计算周期（月）
            zscore_window: Z-score 滚动窗口
            zscore_min_periods: Z-score 最小计算周期
            sigmoid_k: Sigmoid 斜率参数
        """
        self.momentum_period = momentum_period
        self.zscore_window = zscore_window
        self.zscore_min_periods = zscore_min_periods
        self.sigmoid_k = sigmoid_k

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
        growth_momentums = calculate_momentum(
            growth_series,
            period=self.momentum_period
        )
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

        # 3. 计算 Regime 分布
        distribution = calculate_regime_distribution(
            growth_z,
            inflation_z,
            k=self.sigmoid_k
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
