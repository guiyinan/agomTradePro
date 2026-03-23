"""
Domain Entities for Filter Operations.

Pure data classes using only Python standard library.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class FilterType(Enum):
    """滤波器类型"""
    HP = "HP"  # Hodrick-Prescott 滤波
    KALMAN = "KALMAN"  # Kalman 滤波


@dataclass(frozen=True)
class HPFilterParams:
    """HP 滤波参数配置"""
    lamb: float = 129600  # 月度数据推荐值

    @classmethod
    def for_monthly_data(cls) -> "HPFilterParams":
        """月度数据的推荐参数"""
        return cls(lamb=129600)

    @classmethod
    def for_quarterly_data(cls) -> "HPFilterParams":
        """季度数据的推荐参数"""
        return cls(lamb=1600)

    @classmethod
    def for_annual_data(cls) -> "HPFilterParams":
        """年度数据的推荐参数"""
        return cls(lamb=100)


@dataclass(frozen=True)
class KalmanFilterParams:
    """Kalman 滤波参数配置"""
    level_variance: float = 0.01
    slope_variance: float = 0.001
    observation_variance: float = 1.0
    initial_level: float | None = None
    initial_slope: float = 0.0

    @classmethod
    def for_monthly_macro(cls) -> "KalmanFilterParams":
        """月度宏观数据的推荐参数"""
        return cls(
            level_variance=0.05,
            slope_variance=0.005,
            observation_variance=0.5,
        )


@dataclass(frozen=True)
class FilterResult:
    """滤波结果（单个时点）"""
    date: date
    original_value: float
    filtered_value: float
    trend: float | None = None  # 仅 Kalman 有
    slope: float | None = None  # 仅 Kalman 有


@dataclass(frozen=True)
class FilterSeries:
    """滤波序列结果"""
    indicator_code: str  # 指标代码 (e.g., "PMI", "CPI")
    filter_type: FilterType
    params: dict
    results: list[FilterResult]
    calculated_at: date

    @property
    def dates(self) -> list[date]:
        """获取日期列表"""
        return [r.date for r in self.results]

    @property
    def original_values(self) -> list[float]:
        """获取原始值列表"""
        return [r.original_value for r in self.results]

    @property
    def filtered_values(self) -> list[float]:
        """获取滤波后值列表"""
        return [r.filtered_value for r in self.results]

    @property
    def slopes(self) -> list[float | None]:
        """获取斜率列表（Kalman 滤波）"""
        return [r.slope for r in self.results]


@dataclass(frozen=True)
class KalmanFilterState:
    """Kalman 滤波器状态（可持久化）"""
    level: float
    slope: float
    level_variance: float
    slope_variance: float
    level_slope_cov: float
    updated_at: date

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "slope": self.slope,
            "level_variance": self.level_variance,
            "slope_variance": self.slope_variance,
            "level_slope_cov": self.level_slope_cov,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KalmanFilterState":
        return cls(
            level=d["level"],
            slope=d["slope"],
            level_variance=d["level_variance"],
            slope_variance=d["slope_variance"],
            level_slope_cov=d["level_slope_cov"],
            updated_at=date.fromisoformat(d["updated_at"]),
        )
