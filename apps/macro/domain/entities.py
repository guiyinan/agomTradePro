"""
Domain Entities for Macro Data.

This file defines pure data classes using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, Optional, Tuple

# 单位转换因子（相对于"元"的倍数）
UNIT_CONVERSION_FACTORS: dict[str, float] = {
    '元': 1,
    '万元': 10000,
    '亿元': 100000000,
    '万亿元': 1000000000000,
    '万美元': 10000,
    '百万美元': 1000000,
    '亿美元': 100000000,
    '十亿美元': 1000000000,
}


def normalize_currency_unit(
    value: float,
    unit: str,
    exchange_rate: float = 1.0
) -> tuple[float, str]:
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


class RegimeSensitivity(Enum):
    """指标对Regime变化的敏感度"""
    HIGH = 'HIGH'      # 高敏感：期限利差、信用利差等
    MEDIUM = 'MEDIUM'  # 中敏感：国债收益率、商品指数
    LOW = 'LOW'        # 低敏感：辅助指标


class SignalDirection(Enum):
    """信号方向"""
    BULLISH = 'BULLISH'      # 看多：增长预期上升
    BEARISH = 'BEARISH'      # 看空：衰退预期上升
    NEUTRAL = 'NEUTRAL'      # 中性：无明确信号


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
    published_at: date | None = None
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


@dataclass(frozen=True)
class HighFrequencyIndicator:
    """高频宏观指标值对象

    用于日度/周度级别的高频宏观数据，如国债收益率、期限利差、信用利差等。
    这些指标用于减少 Regime 判定的滞后性。

    Attributes:
        code: 指标代码（如 CN_BOND_10Y, CN_TERM_SPREAD_10Y2Y）
        name: 指标名称（如 "10年期国债收益率"）
        value: 指标值
        unit: 单位（%, BP, 点）
        date: 观测日期
        period_type: 期间类型（D=日度, W=周度）
        regime_sensitivity: Regime敏感度（HIGH/MEDIUM/LOW）
        predictive_power: 预测能力评分（0-1，基于历史回测）
        lead_time_months: 领先月数（如：6表示领先6个月）
        source: 数据源（akshare, wind, etc.）
    """
    code: str
    name: str
    value: float
    unit: str
    date: date
    period_type: PeriodType
    regime_sensitivity: RegimeSensitivity
    predictive_power: float = 0.5
    lead_time_months: int | None = None
    source: str = "unknown"

    def to_macro_indicator(self) -> MacroIndicator:
        """转换为 MacroIndicator 实体（用于存储）"""
        return MacroIndicator(
            code=self.code,
            value=self.value,
            reporting_period=self.date,
            period_type=self.period_type,
            unit=self.unit,
            original_unit=self.unit,
            published_at=self.date,
            source=self.source
        )


@dataclass(frozen=True)
class RegimeSignal:
    """Regime信号值对象

    表示基于高频指标生成的 Regime 切换信号。

    Attributes:
        indicator_code: 触发信号的指标代码
        direction: 信号方向（BULLISH/BEARISH/NEUTRAL）
        strength: 信号强度（0-1）
        confidence: 信号置信度（0-1）
        signal_date: 信号生成日期
        regime_sensitivity: 指标敏感度
        lead_time_months: 领先月数
        source: 信号来源（DAILY_HIGH_FREQ, WEEKLY, MONTHLY）
    """
    indicator_code: str
    direction: SignalDirection
    strength: float
    confidence: float
    signal_date: date
    regime_sensitivity: RegimeSensitivity
    lead_time_months: int | None = None
    source: str = "DAILY_HIGH_FREQ"

    @property
    def is_bullish(self) -> bool:
        """是否为看多信号"""
        return self.direction == SignalDirection.BULLISH

    @property
    def is_bearish(self) -> bool:
        """是否为看空信号"""
        return self.direction == SignalDirection.BEARISH

    @property
    def is_neutral(self) -> bool:
        """是否为中性信号"""
        return self.direction == SignalDirection.NEUTRAL

    @property
    def is_high_confidence(self) -> bool:
        """是否为高置信度信号"""
        return self.confidence >= 0.7

    @property
    def is_high_sensitivity(self) -> bool:
        """是否来自高敏感度指标"""
        return self.regime_sensitivity == RegimeSensitivity.HIGH


@dataclass(frozen=True)
class BondYieldCurve:
    """国债收益率曲线值对象

    表示某日的国债收益率曲线状态。

    Attributes:
        date: 观测日期
        bond_10y: 10年期国债收益率
        bond_5y: 5年期国债收益率
        bond_2y: 2年期国债收益率
        bond_1y: 1年期国债收益率（可选）
        term_spread_10y2y: 期限利差(10Y-2Y)
        term_spread_10y1y: 期限利差(10Y-1Y)
        is_inverted: 曲线是否倒挂
        inversion_severity: 倒挂严重程度（BP，0表示未倒挂）
    """
    date: date
    bond_10y: float
    bond_5y: float
    bond_2y: float
    bond_1y: float | None = None
    term_spread_10y2y: float = 0.0
    term_spread_10y1y: float | None = None
    is_inverted: bool = False
    inversion_severity: float = 0.0

    @property
    def curve_shape(self) -> str:
        """收益率曲线形状"""
        if self.is_inverted:
            return "INVERTED"
        elif self.term_spread_10y2y < 0.5:
            return "FLAT"
        elif self.term_spread_10y2y > 1.5:
            return "STEEP"
        else:
            return "NORMAL"


@dataclass(frozen=True)
class CreditSpreadIndicator:
    """信用利差指标值对象

    表示某日的信用利差状态。

    Attributes:
        date: 观测日期
        spread_10y: 10年期信用利差（BP）
        aaa_yield: AAA级企业债收益率（%）
        baa_yield: BAA级企业债收益率（%）
        treasury_10y: 10年期国债收益率（%）
        warning_level: 预警等级（NORMAL/WARNING/DANGER）
        spread_percentile: 历史分位数（0-100）
    """
    date: date
    spread_10y: float
    aaa_yield: float
    baa_yield: float
    treasury_10y: float
    warning_level: str = "NORMAL"
    spread_percentile: float = 50.0

    @property
    def is_stressed(self) -> bool:
        """信用市场是否压力状态"""
        return self.warning_level in ["WARNING", "DANGER"]

    @property
    def stress_level(self) -> float:
        """压力等级（0-1）"""
        return self.spread_percentile / 100.0
