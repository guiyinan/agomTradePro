"""
Domain Entities for Attribution Analysis.

This module contains the core data entities for the audit module.
Following four-layer architecture, this file uses ONLY Python standard library.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Optional
from enum import Enum


class LossSource(Enum):
    """损失来源归因"""
    REGIME_TIMING_ERROR = "regime_timing"  # Regime 判断错误
    ASSET_SELECTION_ERROR = "asset_selection"  # 资产选择错误
    POLICY_INTERVENTION = "policy_intervention"  # 政策干预
    MARKET_VOLATILITY = "market_volatility"  # 市场波动
    TRANSACTION_COST = "transaction_cost"  # 交易成本
    UNKNOWN = "unknown"


class RegimeTransition(Enum):
    """Regime 转换类型"""
    SAME = "same"  # 保持不变
    CORRECT_PREDICTION = "correct_prediction"  # 正确预测转换
    MISSED_PREDICTION = "missed_prediction"  # 错过转换
    WRONG_PREDICTION = "wrong_prediction"  # 错误预测


class AttributionMethod(Enum):
    """归因方法"""
    HEURISTIC = "heuristic"  # 启发式方法（30%/50% 规则）
    BRINSON = "brinson"  # 标准 Brinson 模型


@dataclass(frozen=True)
class RegimePeriod:
    """Regime 周期"""
    start_date: date
    end_date: date
    regime: str
    actual_regime: Optional[str] = None  # 实际发生的 Regime（用于验证）
    confidence: float = 0.0

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days


@dataclass(frozen=True)
class PeriodPerformance:
    """周期表现"""
    period: RegimePeriod
    portfolio_return: float
    benchmark_return: float
    best_asset_return: float  # 该周期表现最好的资产收益
    worst_asset_return: float  # 该周期表现最差的资产收益
    asset_returns: Dict[str, float]  # 各资产收益


@dataclass(frozen=True)
class AttributionResult:
    """归因分析结果

    ⚠️ 归因方法说明：
    - HEURISTIC: 启发式方法（30%/50% 规则），用于快速识别收益来源
    - BRINSON: 标准 Brinson 模型，提供严格的配置/选股/交互效应分解

    启发式方法注意事项：
    - 择时收益：正收益的 30% 归因于 Regime 择时
    - 选资产收益：超额收益的 50% 归因于资产选择
    - 这是简化估算，如需严格归因应使用 Brinson 模型
    """
    # 收益归因
    total_return: float
    regime_timing_pnl: float  # 择时收益（Regime 判断正确带来的收益）
    asset_selection_pnl: float  # 选资产收益（在正确 Regime 下选对资产）
    interaction_pnl: float  # 交互收益
    transaction_cost_pnl: float  # 交易成本

    # 损失分析
    loss_source: LossSource
    loss_amount: float  # 损失金额
    loss_periods: List[RegimePeriod]  # 亏损周期

    # 经验总结
    lesson_learned: str
    improvement_suggestions: List[str]

    # 详细分解
    period_attributions: List[Dict]  # 每个周期的归因

    # 归因方法标识（放在最后，因为有默认值）
    attribution_method: AttributionMethod = AttributionMethod.HEURISTIC  # 使用的归因方法


@dataclass(frozen=True)
class BrinsonAttributionResult:
    """Brinson 归因模型结果

    标准 Brinson 模型将超额收益分解为：
    - Allocation Effect: 配置效应（资产配置偏离基准的收益）
    - Selection Effect: 选股效应（同类资产内选股能力的收益）
    - Interaction Effect: 交互效应（配置和选股的交互影响）

    公式:
    - Allocation Effect = Σ(wp_i - wb_i) * (rb_i - rb)
    - Selection Effect = Σ wb_i * (rp_i - rb_i)
    - Interaction Effect = Σ(wp_i - wb_i) * (rp_i - rb_i)

    其中:
    - wp_i: 组合中资产 i 的权重
    - wb_i: 基准中资产 i 的权重
    - rp_i: 组合中资产 i 的收益
    - rb_i: 基准中资产 i 的收益
    - rb: 基准整体收益
    """
    # 总体指标
    benchmark_return: float  # 基准收益率
    portfolio_return: float  # 组合收益率
    excess_return: float  # 超额收益 = portfolio_return - benchmark_return

    # Brinson 分解
    allocation_effect: float  # 配置效应
    selection_effect: float  # 选股效应
    interaction_effect: float  # 交互效应

    # 验证：三项之和应等于超额收益
    attribution_sum: float  # allocation + selection + interaction

    # 分时段分解
    period_breakdown: List[Dict]  # 各时段的 Brinson 分解

    # 分资产类别分解
    sector_breakdown: Dict[str, Dict]  # 各资产类别的详细分解
    # 格式: {asset_class: {"allocation": float, "selection": float, "interaction": float}}


@dataclass(frozen=True)
class AttributionConfig:
    """归因分析配置"""
    risk_free_rate: float = 0.03  # 无风险利率
    benchmark_return: float = 0.08  # 基准收益（年化）
    min_confidence_threshold: float = 0.3  # 最低置信度阈值
    attribution_method: AttributionMethod = AttributionMethod.HEURISTIC  # 归因方法


# ============ 指标表现评估相关实体 ============

class ValidationStatus(Enum):
    """验证状态"""
    PENDING = "pending"  # 待验证
    IN_PROGRESS = "in_progress"  # 验证中
    PASSED = "passed"  # 通过验证
    FAILED = "failed"  # 未通过验证
    SHADOW_RUN = "shadow_run"  # 影子模式运行


class RecommendedAction(Enum):
    """建议操作"""
    KEEP = "keep"  # 保持当前配置
    INCREASE = "increase"  # 增加权重
    DECREASE = "decrease"  # 降低权重
    REMOVE = "remove"  # 移除指标


@dataclass(frozen=True)
class IndicatorPerformanceReport:
    """指标表现报告

    评估单个指标对 Regime 判断的预测能力。
    """
    indicator_code: str
    evaluation_period_start: date
    evaluation_period_end: date

    # 混淆矩阵
    true_positive_count: int
    false_positive_count: int
    true_negative_count: int
    false_negative_count: int

    # 统计指标
    precision: float
    recall: float
    f1_score: float
    accuracy: float

    # 领先时间（月）
    lead_time_mean: float
    lead_time_std: float

    # 稳定性（分段相关性）
    pre_2015_correlation: Optional[float]
    post_2015_correlation: Optional[float]
    stability_score: float

    # 建议
    recommended_action: str  # "KEEP" / "INCREASE" / "DECREASE" / "REMOVE"
    recommended_weight: float
    confidence_level: float

    # 详细分析
    decay_rate: float = 0.0  # 信号衰减率
    signal_strength: float = 0.0  # 信号强度


@dataclass(frozen=True)
class IndicatorThresholdConfig:
    """指标阈值配置（Domain 层值对象）"""
    indicator_code: str
    indicator_name: str

    # 阈值定义
    level_low: Optional[float]
    level_high: Optional[float]

    # 权重配置
    base_weight: float = 1.0
    min_weight: float = 0.0
    max_weight: float = 1.0

    # 验证阈值（可调整）
    decay_threshold: float = 0.2  # F1 分数低于此值视为衰减
    decay_penalty: float = 0.5  # 衰减惩罚系数
    improvement_threshold: float = 0.1  # 改进阈值
    improvement_bonus: float = 1.2  # 改进奖励系数

    # 行为阈值
    keep_min_f1: float = 0.6  # 保持当前权重的最低 F1
    reduce_min_f1: float = 0.4  # 降低权重的最高 F1
    remove_max_f1: float = 0.3  # 建议移除的最高 F1


@dataclass(frozen=True)
class ThresholdValidationReport:
    """阈值验证报告

    验证历史阈值配置的表现。
    """
    validation_run_id: str
    run_date: date
    evaluation_period_start: date
    evaluation_period_end: date

    total_indicators: int
    approved_indicators: int  # 通过验证
    rejected_indicators: int  # 未通过验证
    pending_indicators: int  # 需要更多数据

    # 各指标的详细报告
    indicator_reports: List[IndicatorPerformanceReport]

    # 总体建议
    overall_recommendation: str

    # 验证状态
    status: ValidationStatus


@dataclass(frozen=True)
class DynamicWeightConfig:
    """动态权重配置

    根据指标表现动态调整权重。
    """
    indicator_code: str
    current_weight: float
    original_weight: float

    # 调整依据
    f1_score: float
    stability_score: float
    decay_rate: float

    # 调整参数
    adjustment_factor: float  # 调整系数
    new_weight: float  # 调整后权重

    # 调整原因
    reason: str
    confidence: float


@dataclass(frozen=True)
class SignalEvent:
    """信号事件"""
    indicator_code: str
    signal_date: date
    signal_type: str  # "BULLISH" / "BEARISH" / "NEUTRAL"
    signal_value: float
    threshold_used: float
    confidence: float


@dataclass(frozen=True)
class RegimeSnapshot:
    """Regime 快照（用于验证）"""
    observed_at: date
    dominant_regime: str
    confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    distribution: Dict[str, float]  # 各 Regime 的概率分布
