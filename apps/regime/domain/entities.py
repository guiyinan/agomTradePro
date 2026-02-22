"""
Domain Entities for Regime Calculation.

Pure data classes using only Python standard library.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List


@dataclass(frozen=True)
class KalmanFilterParams:
    """Kalman 滤波参数配置"""

    level_variance: float = 0.01
    slope_variance: float = 0.001
    observation_variance: float = 1.0
    initial_level: Optional[float] = None
    initial_slope: float = 0.0
    initial_level_var: float = 10.0
    initial_slope_var: float = 1.0

    @classmethod
    def for_monthly_macro(cls) -> "KalmanFilterParams":
        """月度宏观数据的推荐参数"""
        return cls(
            level_variance=0.05,
            slope_variance=0.005,
            observation_variance=0.5,
        )


@dataclass(frozen=True)
class KalmanState:
    """Kalman 滤波器的当前状态（可持久化）"""
    level: float
    slope: float
    level_variance: float
    slope_variance: float
    level_slope_cov: float

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "slope": self.slope,
            "level_variance": self.level_variance,
            "slope_variance": self.slope_variance,
            "level_slope_cov": self.level_slope_cov,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KalmanState":
        return cls(**d)


@dataclass(frozen=True)
class RegimeSnapshot:
    """Regime 状态快照"""
    growth_momentum_z: float
    inflation_momentum_z: float
    distribution: Dict[str, float]
    dominant_regime: str
    confidence: float
    observed_at: date
    data_source: str = "calculated"  # calculated, fallback, degraded
    fallback_count: int = 0  # 降级次数

    def is_high_confidence(self, threshold: float = 0.3) -> bool:
        return self.confidence >= threshold

    @property
    def confidence_percent(self) -> float:
        """置信度百分比 (0-100)"""
        return self.confidence * 100

    @property
    def is_degraded(self) -> bool:
        """是否为降级数据"""
        return self.data_source in ("fallback", "degraded")


# ==================== Phase 4: Probability Confidence Model ====================

@dataclass(frozen=True)
class RegimeProbabilities:
    """Regime 概率分布

    包含四个象限的概率分布和整体置信度。
    置信度基于数据新鲜度、历史预测能力和指标一致性计算。
    """
    growth_reflation: float  # 增长+通胀 (Overheat)
    growth_disinflation: float  # 增长+通缩 (Recovery)
    stagnation_reflation: float  # 停滞+通胀 (Stagflation)
    stagnation_disinflation: float  # 停滞+通缩 (Deflation)

    confidence: float  # 0-1，基于数据新鲜度

    # 元数据
    data_freshness_score: float  # 数据新鲜度评分 (0-1)
    predictive_power_score: float  # 预测能力评分 (0-1)
    consistency_score: float  # 指标一致性评分 (0-1)

    @property
    def distribution(self) -> Dict[str, float]:
        """返回四象限分布字典"""
        return {
            "Overheat": self.growth_reflation,
            "Recovery": self.growth_disinflation,
            "Stagflation": self.stagnation_reflation,
            "Deflation": self.stagnation_disinflation,
        }

    @property
    def dominant_regime(self) -> str:
        """返回概率最高的 Regime"""
        return max(self.distribution.items(), key=lambda x: x[1])[0]

    def normalize(self) -> "RegimeProbabilities":
        """归一化概率分布（确保总和为1）"""
        total = sum([self.growth_reflation, self.growth_disinflation,
                     self.stagnation_reflation, self.stagnation_disinflation])
        if total == 0:
            return self

        return RegimeProbabilities(
            growth_reflation=self.growth_reflation / total,
            growth_disinflation=self.growth_disinflation / total,
            stagnation_reflation=self.stagnation_reflation / total,
            stagnation_disinflation=self.stagnation_disinflation / total,
            confidence=self.confidence,
            data_freshness_score=self.data_freshness_score,
            predictive_power_score=self.predictive_power_score,
            consistency_score=self.consistency_score,
        )


@dataclass(frozen=True)
class ConfidenceConfig:
    """置信度配置（从数据库读取）

    所有阈值可配置，支持动态调整。
    """
    # 新鲜度系数
    day_0_coefficient: float  # 发布当天系数
    day_7_coefficient: float  # 发布 1 周后系数
    day_14_coefficient: float  # 发布 2 周后系数
    day_30_coefficient: float  # 发布 1 个月后系数

    # 数据类型加成
    daily_data_bonus: float  # 有日度数据支持加成
    weekly_data_bonus: float  # 有周度数据支持加成
    daily_consistency_bonus: float  # 日度数据一致加成

    # 基础置信度
    base_confidence: float  # 基础置信度

    @classmethod
    def defaults(cls) -> "ConfidenceConfig":
        """默认配置"""
        return cls(
            day_0_coefficient=0.6,
            day_7_coefficient=0.5,
            day_14_coefficient=0.4,
            day_30_coefficient=0.3,
            daily_data_bonus=0.2,
            weekly_data_bonus=0.1,
            daily_consistency_bonus=0.1,
            base_confidence=0.5,
        )


@dataclass(frozen=True)
class IndicatorPredictivePower:
    """指标预测能力（基于历史回测）

    存储指标的历史预测表现，用于贝叶斯置信度计算。
    """
    indicator_code: str  # CN_TERM_SPREAD_10Y1Y

    # 历史预测表现
    true_positive_rate: float  # 真阳性率 (TP / (TP + FN))
    false_positive_rate: float  # 假阳性率 (FP / (FP + TN))
    precision: float  # 精确率 (TP / (TP + FP))
    f1_score: float  # F1 分数

    # 领先时间统计
    lead_time_mean: float  # 平均领先月数
    lead_time_std: float  # 领先时间标准差
    lead_time_min: float  # 最小领先月数
    lead_time_max: float  # 最大领先月数

    # 子样本期稳定性
    pre_2015_correlation: float  # 2015 年前相关性
    post_2015_correlation: float  # 2015 年后相关性
    stability_score: float  # 稳定性评分 (0-1)

    # 当前状态
    current_signal: str  # "BEARISH" / "NEUTRAL" / "BULLISH"
    signal_strength: float  # 信号强度 (0-1)
    days_since_last_update: int  # 距上次更新天数

    # 权重配置
    base_weight: float  # 基础权重 (0-1)
    current_weight: float  # 当前动态权重 (0-1)

    @property
    def predictive_power_score(self) -> float:
        """综合预测能力评分 (0-1)"""
        # 结合 F1 分数和稳定性评分
        return (self.f1_score * 0.7 + self.stability_score * 0.3)

    @property
    def reliability_score(self) -> float:
        """可靠性评分 (0-1)

        考虑真阳性率和假阳性率
        """
        # 高真阳性率 + 低假阳性率 = 高可靠性
        return (self.true_positive_rate * 0.6 +
                (1 - self.false_positive_rate) * 0.4)

    @property
    def is_decay_detected(self) -> bool:
        """检测是否出现信号衰减"""
        # 简单判断：如果最近表现远低于历史平均水平
        return self.current_weight < self.base_weight * 0.7


@dataclass(frozen=True)
class SignalConflict:
    """信号冲突记录"""
    daily_signal: str  # BULLISH, BEARISH, NEUTRAL
    weekly_signal: Optional[str]
    monthly_signal: str

    daily_confidence: float
    monthly_confidence: float

    daily_duration: int  # 日度信号持续天数

    # 冲突解决结果
    final_signal: str
    final_confidence: float
    resolution_source: str  # ALL_CONSISTENT, DAILY_PERSISTENT, HYBRID_WEIGHTED, MONTHLY_DEFAULT
    resolution_reason: str


@dataclass(frozen=True)
class ConfidenceBreakdown:
    """置信度分解

    展示置信度的各组成部分。
    """
    total_confidence: float  # 总置信度 (0-1)

    # 分量
    data_freshness_component: float  # 数据新鲜度贡献
    predictive_power_component: float  # 预测能力贡献
    consistency_component: float  # 一致性贡献
    base_component: float  # 基础置信度贡献

    # 元数据
    days_since_last_update: int  # 距上次更新天数
    has_daily_data: bool  # 是否有日度数据
    daily_consistent: bool  # 日度数据是否一致
    indicators_count: int  # 参与指标数量

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "total_confidence": self.total_confidence,
            "data_freshness_component": self.data_freshness_component,
            "predictive_power_component": self.predictive_power_component,
            "consistency_component": self.consistency_component,
            "base_component": self.base_component,
            "days_since_last_update": self.days_since_last_update,
            "has_daily_data": self.has_daily_data,
            "daily_consistent": self.daily_consistent,
            "indicators_count": self.indicators_count,
        }
