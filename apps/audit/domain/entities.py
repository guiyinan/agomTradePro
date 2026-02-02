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
    """归因分析结果"""
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


@dataclass(frozen=True)
class AttributionConfig:
    """归因分析配置"""
    risk_free_rate: float = 0.03  # 无风险利率
    benchmark_return: float = 0.08  # 基准收益（年化）
    min_confidence_threshold: float = 0.3  # 最低置信度阈值
