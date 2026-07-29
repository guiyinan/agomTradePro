"""Pulse Module Domain Entities — 纯 Python，不依赖外部库。"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType


class PulseDimension:
    """脉搏维度常量"""

    GROWTH = "growth"
    INFLATION = "inflation"
    LIQUIDITY = "liquidity"
    SENTIMENT = "sentiment"


@dataclass(frozen=True)
class PulseIndicatorReading:
    """单个脉搏指标的读数"""

    code: str  # 指标代码，如 'CN_TERM_SPREAD_10Y2Y'
    name: str  # 人类可读名称，如 '国债利差(10Y-2Y)'
    dimension: str  # 所属维度：growth/inflation/liquidity/sentiment
    value: float  # 当前值
    z_score: float  # 相对历史的 z-score
    direction: str  # 'improving', 'deteriorating', 'stable'
    signal: str  # 'bullish', 'bearish', 'neutral'
    signal_score: float  # -1 to +1
    weight: float  # 维度内权重（Phase 1 等权 = 1.0）
    data_age_days: int  # 数据距今天数
    is_stale: bool  # 数据是否过期
    observed_at: date | None = None  # 指标值本身的实际观测日期
    source_kind: str = "observation"  # macro_fact / price_bar_close / quote_current_price


@dataclass(frozen=True)
class DimensionScore:
    """单个维度的汇总分数"""

    dimension: str  # growth/inflation/liquidity/sentiment
    score: float  # -1 to +1
    signal: str  # 'bullish', 'bearish', 'neutral'
    indicator_count: int  # 该维度有效指标数
    description: str  # "增长脉搏偏弱" 等


@dataclass(frozen=True)
class PulseSnapshot:
    """Pulse 脉搏快照 — Pulse 模块的核心输出"""

    observed_at: date
    regime_context: str  # 当前 regime 名称

    # 4 维度分数
    dimension_scores: list[DimensionScore]

    # 综合评估
    composite_score: float  # -1 to +1
    regime_strength: str  # 'strong', 'moderate', 'weak'

    # 转折预警
    transition_warning: bool
    transition_direction: str | None  # 预警的转折方向
    transition_reasons: list[str]

    # 明细
    indicator_readings: list[PulseIndicatorReading]

    # 元数据
    data_source: str = "calculated"  # calculated, stale, degraded
    stale_indicator_count: int = 0

    @property
    def is_reliable(self) -> bool:
        """数据是否可靠（非过期非降级）"""
        return self.data_source == "calculated" and self.stale_indicator_count == 0

    @property
    def dimension_dict(self) -> dict[str, float]:
        """维度分数字典"""
        return {ds.dimension: ds.score for ds in self.dimension_scores}


@dataclass(frozen=True)
class PulseConfig:
    """Pulse 配置"""

    # Z-score 阈值
    bullish_z_threshold: float = 1.0
    bearish_z_threshold: float = -1.0

    # 方向判定阈值
    direction_change_threshold: float = 0.1

    # 数据过期天数
    daily_stale_days: int = 7
    monthly_stale_days: int = 45

    # 维度权重（Phase 1 等权）
    dimension_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "growth": 0.25,
            "inflation": 0.25,
            "liquidity": 0.25,
            "sentiment": 0.25,
        }
    )

    # 转折预警阈值
    transition_warning_threshold: float = -0.3

    def __post_init__(self) -> None:
        """Validate and detach runtime decision thresholds."""

        finite_fields = {
            "bullish_z_threshold": self.bullish_z_threshold,
            "bearish_z_threshold": self.bearish_z_threshold,
            "direction_change_threshold": self.direction_change_threshold,
            "transition_warning_threshold": self.transition_warning_threshold,
        }
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            for value in finite_fields.values()
        ):
            raise ValueError("pulse_config_threshold_invalid")
        if self.bearish_z_threshold >= self.bullish_z_threshold:
            raise ValueError("pulse_config_z_thresholds_invalid")
        if not 0 <= self.direction_change_threshold <= 2:
            raise ValueError("pulse_direction_change_threshold_invalid")
        if not -1 <= self.transition_warning_threshold <= 1:
            raise ValueError("pulse_transition_warning_threshold_invalid")
        if (
            isinstance(self.daily_stale_days, bool)
            or not isinstance(self.daily_stale_days, int)
            or not 1 <= self.daily_stale_days <= 366
            or isinstance(self.monthly_stale_days, bool)
            or not isinstance(self.monthly_stale_days, int)
            or not 1 <= self.monthly_stale_days <= 3660
        ):
            raise ValueError("pulse_stale_days_invalid")

        expected_dimensions = {"growth", "inflation", "liquidity", "sentiment"}
        weights = dict(self.dimension_weights)
        if set(weights) != expected_dimensions or any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in weights.values()
        ):
            raise ValueError("pulse_dimension_weights_invalid")
        normalized_weights = {key: float(value) for key, value in weights.items()}
        if not math.isclose(sum(normalized_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("pulse_dimension_weights_total_invalid")
        object.__setattr__(
            self,
            "dimension_weights",
            MappingProxyType(normalized_weights),
        )

    @classmethod
    def defaults(cls) -> "PulseConfig":
        return cls()
