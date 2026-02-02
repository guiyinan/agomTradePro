"""
Domain Entities for Macro Data.

This file defines pure data classes using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, Tuple
from enum import Enum


# 单位转换因子（相对于"元"的倍数）
UNIT_CONVERSION_FACTORS: Dict[str, float] = {
    '元': 1,
    '万元': 10000,
    '万元': 10000,
    '亿元': 100000000,
    '万亿元': 1000000000000,
    '百万美元': 1000000,
    '亿美元': 100000000,
    '十亿美元': 1000000000,
}


def normalize_currency_unit(
    value: float,
    unit: str,
    exchange_rate: float = 1.0
) -> Tuple[float, str]:
    """
    将货币类数据统一转换为"元"层级

    Args:
        value: 原始值
        unit: 原始单位
        exchange_rate: USD/CNY 汇率（仅对美元单位有效）
                     ⚠️ 默认值 1.0 仅用于系统兜底，不用于历史回测的精确分析
                     回测场景必须使用历史汇率！

    Returns:
        tuple: (转换后的值, "元")

    Examples:
        >>> normalize_currency_unit(1.0, "亿美元", exchange_rate=7.2)
        (720000000.0, "元")
        >>> normalize_currency_unit(1.5, "亿元")
        (150000000.0, "元")

    语义定义:
        exchange_rate: USD/CNY 汇率，表示 1 美元兑换多少人民币
                     如 7.2 表示 1 美元 = 7.2 人民币
    """
    if unit in UNIT_CONVERSION_FACTORS:
        factor = UNIT_CONVERSION_FACTORS[unit]

        # 🔧 修复：美元单位需要额外乘汇率
        if "美元" in unit or "USD" in unit.upper():
            converted_value = value * factor * exchange_rate
            return (converted_value, "元")

        # 人民币单位直接转换
        return (value * factor, "元")

    # 未知单位，保持原值
    return (value, unit)


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
        value: 指标值（统一存储为"元"或原始单位，取决于指标类型）
        reporting_period: 报告期（时点数据=观测日，期间数据=期末日）
        period_type: 期间类型（D/W/M/Q/Y）
        unit: 存储单位（货币类统一为"元"，其他类为原始单位）
        original_unit: 原始数据单位（数据源返回的单位，用于展示）
        published_at: 实际发布日期
        source: 数据源
    """
    code: str
    value: float
    reporting_period: date
    period_type: PeriodType = PeriodType.DAY
    unit: str = ""  # 存储单位
    original_unit: str = ""  # 原始单位（用于展示）
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
