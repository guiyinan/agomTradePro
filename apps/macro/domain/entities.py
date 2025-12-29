"""
Domain Entities for Macro Data.

This file defines pure data classes using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from enum import Enum


class PeriodType(Enum):
    """期间类型"""
    DAY = 'D'      # 时点数据：某日收盘价、SHIBOR日利率
    WEEK = 'W'     # 周度数据
    MONTH = 'M'    # 月度数据：PMI、CPI、M2
    QUARTER = 'Q'  # 季度数据：GDP
    HALF_YEAR = 'H' # 半年度数据：半年度财报
    YEAR = 'Y'     # 年度数据


@dataclass(frozen=True)
class MacroIndicator:
    """宏观指标值对象

    Attributes:
        code: 指标代码（如 CN_PMI, SHIBOR）
        value: 指标值
        reporting_period: 报告期（时点数据=观测日，期间数据=期末日）
        period_type: 期间类型（D/W/M/Q/Y）
        published_at: 实际发布日期
        source: 数据源
    """
    code: str
    value: float
    reporting_period: date
    period_type: PeriodType = PeriodType.DAY
    published_at: Optional[date] = None
    source: str = "unknown"

    @property
    def observed_at(self) -> date:
        """兼容旧 API：observed_at 别名"""
        return self.reporting_period

    @property
    def is_point_data(self) -> bool:
        """是否为时点数据"""
        return self.period_type == PeriodType.DAY

    @property
    def is_period_data(self) -> bool:
        """是否为期间数据"""
        return self.period_type in [PeriodType.WEEK, PeriodType.MONTH, PeriodType.QUARTER, PeriodType.HALF_YEAR, PeriodType.YEAR]

    def __post_init__(self):
        """验证数据一致性"""
        if isinstance(self.period_type, str):
            # 如果传入的是字符串，转换为枚举
            object.__setattr__(self, 'period_type', PeriodType(self.period_type))
