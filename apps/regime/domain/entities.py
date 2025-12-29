"""
Domain Entities for Regime Calculation.

Pure data classes using only Python standard library.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict


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

    def is_high_confidence(self, threshold: float = 0.3) -> bool:
        return self.confidence >= threshold

    @property
    def confidence_percent(self) -> float:
        """置信度百分比 (0-100)"""
        return self.confidence * 100
