"""
Domain Services for Regime Calculation (New Version)

新版本：基于绝对水平而非动量判定 Regime

核心改进：
1. 使用 PMI > 50 判定增长/收缩（而非动量）
2. 使用 CPI 阈值判定通胀水平（而非动量）
3. 动量作为趋势预测指标（独立展示）
4. 阈值可配置（从数据库读取）
"""

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Tuple, Optional, Protocol
from enum import Enum


class RegimeType(Enum):
    """Regime 类型枚举"""
    RECOVERY = "Recovery"      # 复苏：增长↑，通胀↓
    OVERHEAT = "Overheat"      # 过热：增长↑，通胀↑
    STAGFLATION = "Stagflation" # 滞胀：增长↓，通胀↑
    DEFLATION = "Deflation"    # 通缩：增长↓，通胀↓


@dataclass(frozen=True)
class ThresholdConfig:
    """阈值配置"""
    # PMI 阈值
    pmi_expansion: float = 50.0  # PMI > 50 为扩张
    pmi_contraction: float = 50.0  # PMI < 50 为收缩

    # CPI 阈值
    cpi_high: float = 2.0  # CPI > 2% 为高通胀
    cpi_low: float = 1.0   # CPI < 1% 为低通胀
    cpi_deflation: float = 0.0  # CPI < 0 为通缩

    # 动量权重（用于趋势预测）
    momentum_weight: float = 0.3  # 趋势权重，0-1 之间

    # 置信度阈值
    high_confidence_threshold: float = 0.6


@dataclass(frozen=True)
class TrendIndicator:
    """趋势指标（用于预测）"""
    indicator_code: str
    current_value: float
    momentum: float
    momentum_z: float
    direction: str  # 'up', 'down', 'neutral'
    strength: str  # 'strong', 'moderate', 'weak'


@dataclass(frozen=True)
class RegimeCalculationResult:
    """Regime 计算结果（新版本）"""
    regime: RegimeType
    confidence: float
    growth_level: float  # PMI 当前值
    inflation_level: float  # CPI 当前值
    growth_state: str  # 'expansion', 'contraction'
    inflation_state: str  # 'high', 'low', 'deflation'
    distribution: Dict[str, float]  # 四象限概率分布
    trend_indicators: List[TrendIndicator]  # 趋势指标
    warnings: List[str] = field(default_factory=list)
    prediction: Optional[str] = None  # 趋势预测


def calculate_regime_by_level(
    pmi_value: float,
    cpi_value: float,
    config: Optional[ThresholdConfig] = None
) -> RegimeType:
    """
    基于绝对水平判定 Regime

    Args:
        pmi_value: PMI 当前值
        cpi_value: CPI 当前值（百分比，如 0.8 表示 0.8%）
        config: 阈值配置

    Returns:
        RegimeType: 判定的 Regime 类型
    """
    if config is None:
        config = ThresholdConfig()

    # 判定增长状态
    growth_state = "expansion" if pmi_value >= config.pmi_expansion else "contraction"

    # 判定通胀状态
    if cpi_value < config.cpi_deflation:
        inflation_state = "deflation"
    elif cpi_value < config.cpi_low:
        inflation_state = "low"
    elif cpi_value > config.cpi_high:
        inflation_state = "high"
    else:
        inflation_state = "moderate"

    # 映射到 Regime
    if growth_state == "expansion" and inflation_state == "high":
        return RegimeType.OVERHEAT
    if growth_state == "expansion":
        return RegimeType.RECOVERY
    if inflation_state == "high":
        return RegimeType.STAGFLATION
    return RegimeType.DEFLATION


def calculate_regime_distribution_by_level(
    pmi_value: float,
    cpi_value: float,
    config: Optional[ThresholdConfig] = None
) -> Dict[str, float]:
    """
    基于绝对水平计算四象限概率分布

    使用距离加权方法：
    - 距离各象限"中心"越近，概率越高
    - PMI = 50 是增长中心
    - CPI = 2% 是通胀中心

    Args:
        pmi_value: PMI 当前值
        cpi_value: CPI 当前值
        config: 阈值配置

    Returns:
        Dict[str, float]: 四象限概率分布
    """
    if config is None:
        config = ThresholdConfig()

    # 定义各象限的"理想"中心点
    centers = {
        "Recovery": (config.pmi_expansion + 2, config.cpi_low / 2),  # (52, 0.5)
        "Overheat": (config.pmi_expansion + 2, config.cpi_high + 1),  # (52, 3)
        "Stagflation": (config.pmi_contraction - 2, config.cpi_high + 1),  # (48, 3)
        "Deflation": (config.pmi_contraction - 2, config.cpi_low / 2),  # (48, 0.5)
    }

    # 计算距离各中心的"距离"（归一化后）
    distances = {}
    for regime, (center_pmi, center_cpi) in centers.items():
        # 使用相对距离
        pmi_dist = abs(pmi_value - center_pmi) / 10  # PMI 通常在 45-55 之间
        cpi_dist = abs(cpi_value - center_cpi) / 3   # CPI 通常在 -1 到 5 之间
        distance = math.sqrt(pmi_dist ** 2 + cpi_dist ** 2)
        distances[regime] = distance

    # 转换为概率（距离越小，概率越高）
    # 使用带温度的 softmax: exp(-alpha * distance) / sum(...)
    alpha = 2.0
    weights = {r: math.exp(-alpha * d) for r, d in distances.items()}
    total = sum(weights.values())

    if total == 0:
        return {r: 0.25 for r in centers}

    probabilities = {r: w / total for r, w in weights.items()}

    return probabilities


def calculate_momentum_simple(
    series: List[float],
    period: int = 3
) -> Tuple[float, float]:
    """
    计算简单的动量

    Returns:
        (momentum_value, momentum_direction)
        - momentum_value: 动量值
        - momentum_direction: -1 (下降), 0 (持平), 1 (上升)
    """
    if len(series) < period + 1:
        return 0.0, 0

    current = series[-1]
    past = series[-period - 1]
    momentum = current - past

    # 判定方向
    if abs(momentum) < 0.1:  # 变化小于阈值则视为持平
        direction = 0
    else:
        direction = 1 if momentum > 0 else -1

    return momentum, direction


def calculate_zscore_simple(
    series: List[float],
    value: float
) -> float:
    """
    计算单个值的 Z-score（相对于历史均值）
    """
    if len(series) < 3:
        return 0.0

    mean_val = sum(series) / len(series)
    variance = sum((x - mean_val) ** 2 for x in series) / len(series)
    std_val = math.sqrt(variance)

    if std_val == 0:
        return 0.0

    return (value - mean_val) / std_val


def classify_momentum_strength(z_score: float) -> str:
    """根据 Z-score 分类动量强度"""
    abs_z = abs(z_score)
    if abs_z < 0.5:
        return "weak"
    elif abs_z < 1.5:
        return "moderate"
    else:
        return "strong"


def generate_prediction(
    current_regime: RegimeType,
    pmi_trend: int,
    cpi_trend: int,
    trend_indicators: List[TrendIndicator]
) -> Optional[str]:
    """
    生成趋势预测

    基于当前 Regime 和动量方向，预测未来可能的变化
    """
    predictions = []

    # PMI 趋势预测
    if pmi_trend == 1:
        predictions.append("PMI 上升，经济动能增强")
    elif pmi_trend == -1:
        predictions.append("PMI 下降，经济动能减弱")

    # CPI 趋势预测
    if cpi_trend == 1:
        predictions.append("通胀上升，需关注压力")
    elif cpi_trend == -1:
        predictions.append("通胀回落，压力减轻")

    # Regime 转换预测
    if current_regime == RegimeType.DEFLATION:
        if pmi_trend == 1 and cpi_trend == 1:
            return "可能转向滞胀或复苏（取决于哪个先起）"
        elif pmi_trend == 1 and cpi_trend <= 0:
            return "可能转向复苏（增长改善，通胀受控）"
    elif current_regime == RegimeType.OVERHEAT:
        if pmi_trend == -1 or cpi_trend == -1:
            return "可能开始降温"

    if predictions:
        return "; ".join(predictions)

    return None


class RegimeCalculatorV2:
    """
    新版 Regime 计算器

    基于绝对水平判定，而非动量
    """

    def __init__(self, config: Optional[ThresholdConfig] = None):
        """
        Args:
            config: 阈值配置，如果为 None 则使用默认配置
        """
        self.config = config or ThresholdConfig()

    def calculate(
        self,
        pmi_series: List[float],
        cpi_series: List[float],
        as_of_date: date
    ) -> RegimeCalculationResult:
        """
        计算 Regime

        Args:
            pmi_series: PMI 时间序列（按时间排序）
            cpi_series: CPI 时间序列（按时间排序）
            as_of_date: 计算日期

        Returns:
            RegimeCalculationResult: 计算结果
        """
        warnings = []

        # 数据验证
        if not pmi_series or not cpi_series:
            warnings.append("数据为空")
            return self._empty_result(as_of_date, warnings)

        pmi_value = pmi_series[-1]
        cpi_value = cpi_series[-1]

        # 1. 判定 Regime（基于绝对水平）
        regime = calculate_regime_by_level(pmi_value, cpi_value, self.config)

        # 2. 计算概率分布
        distribution = calculate_regime_distribution_by_level(pmi_value, cpi_value, self.config)
        confidence = distribution[regime.value]

        # 3. 计算趋势指标
        trend_indicators = []

        # PMI 趋势
        pmi_period = min(3, max(1, len(pmi_series) - 1))
        pmi_momentum, pmi_direction = calculate_momentum_simple(pmi_series, period=pmi_period)
        pmi_z = calculate_zscore_simple(pmi_series, pmi_value)
        pmi_strength = classify_momentum_strength(pmi_z)
        pmi_dir_str = "up" if pmi_direction > 0 else ("down" if pmi_direction < 0 else "neutral")

        trend_indicators.append(TrendIndicator(
            indicator_code="PMI",
            current_value=pmi_value,
            momentum=pmi_momentum,
            momentum_z=pmi_z,
            direction=pmi_dir_str,
            strength=pmi_strength
        ))

        # CPI 趋势
        cpi_period = min(3, max(1, len(cpi_series) - 1))
        cpi_momentum, cpi_direction = calculate_momentum_simple(cpi_series, period=cpi_period)
        cpi_z = calculate_zscore_simple(cpi_series, cpi_value)
        cpi_strength = classify_momentum_strength(cpi_z)
        cpi_dir_str = "up" if cpi_direction > 0 else ("down" if cpi_direction < 0 else "neutral")

        trend_indicators.append(TrendIndicator(
            indicator_code="CPI",
            current_value=cpi_value,
            momentum=cpi_momentum,
            momentum_z=cpi_z,
            direction=cpi_dir_str,
            strength=cpi_strength
        ))

        # 4. 判定状态描述
        growth_state = "expansion" if pmi_value >= self.config.pmi_expansion else "contraction"
        inflation_state = self._classify_inflation_state(cpi_value)

        # 5. 生成预测
        prediction = generate_prediction(regime, pmi_direction, cpi_direction, trend_indicators)

        return RegimeCalculationResult(
            regime=regime,
            confidence=confidence,
            growth_level=pmi_value,
            inflation_level=cpi_value,
            growth_state=growth_state,
            inflation_state=inflation_state,
            distribution=distribution,
            trend_indicators=trend_indicators,
            warnings=warnings,
            prediction=prediction
        )

    def _classify_inflation_state(self, cpi_value: float) -> str:
        """分类通胀状态"""
        if cpi_value < 0:
            return "deflation"
        elif cpi_value < self.config.cpi_low:
            return "low"
        elif cpi_value > self.config.cpi_high:
            return "high"
        else:
            return "moderate"

    def _empty_result(self, as_of_date: date, warnings: List[str]) -> RegimeCalculationResult:
        """返回空结果"""
        return RegimeCalculationResult(
            regime=RegimeType.DEFLATION,
            confidence=0.0,
            growth_level=0.0,
            inflation_level=0.0,
            growth_state="unknown",
            inflation_state="unknown",
            distribution={r.value: 0.25 for r in RegimeType},
            trend_indicators=[],
            warnings=warnings
        )


# 便捷函数
def calculate_regime_with_defaults(
    pmi_series: List[float],
    cpi_series: List[float],
    as_of_date: date
) -> RegimeCalculationResult:
    """使用默认配置计算 Regime"""
    calculator = RegimeCalculatorV2()
    return calculator.calculate(pmi_series, cpi_series, as_of_date)
