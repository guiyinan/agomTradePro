"""
个股分析模块 Domain 层实体定义

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class StockInfo:
    """个股基本信息（值对象）

    Attributes:
        stock_code: 股票代码（如 '000001.SZ'）
        name: 股票名称
        sector: 所属行业（申万一级行业）
        market: 交易市场（SH/SZ/BJ）
        list_date: 上市日期
    """
    stock_code: str
    name: str
    sector: str
    market: str
    list_date: date


@dataclass(frozen=True)
class FinancialData:
    """财务数据（值对象）

    Attributes:
        stock_code: 股票代码
        report_date: 报告期

        利润表（单位：元）:
        revenue: 营业收入
        net_profit: 净利润

        增长率（%）:
        revenue_growth: 营收增长率
        net_profit_growth: 净利润增长率

        资产负债表（单位：元）:
        total_assets: 总资产
        total_liabilities: 总负债
        equity: 股东权益

        财务指标（%）:
        roe: 净资产收益率
        roa: 总资产收益率
        debt_ratio: 资产负债率
    """
    stock_code: str
    report_date: date

    # 利润表（单位：元）
    revenue: Decimal
    net_profit: Decimal

    # 增长率（%）
    revenue_growth: float
    net_profit_growth: float

    # 资产负债表（单位：元）
    total_assets: Decimal
    total_liabilities: Decimal
    equity: Decimal

    # 财务指标（%）
    roe: float
    roa: float
    debt_ratio: float


@dataclass(frozen=True)
class ValuationMetrics:
    """估值指标（值对象）

    Attributes:
        stock_code: 股票代码
        trade_date: 交易日期

        估值指标:
        pe: 市盈率（动态）
        pb: 市净率
        ps: 市销率

        市值（单位：元）:
        total_mv: 总市值
        circ_mv: 流通市值

        其他指标:
        dividend_yield: 股息率（%）
    """
    stock_code: str
    trade_date: date

    pe: float
    pb: float
    ps: float
    total_mv: Decimal
    circ_mv: Decimal
    dividend_yield: float


@dataclass(frozen=True)
class TechnicalIndicators:
    """技术指标（值对象）

    Attributes:
        stock_code: 股票代码
        trade_date: 交易日期

        价格（元）:
        close: 收盘价

        均线:
        ma5: 5日均线
        ma20: 20日均线
        ma60: 60日均线

        MACD:
        macd: MACD 指标
        macd_signal: MACD 信号线
        macd_hist: MACD 柱状图

        其他:
        rsi: RSI（14日）
    """
    stock_code: str
    trade_date: date

    close: Decimal
    ma5: Optional[Decimal]
    ma20: Optional[Decimal]
    ma60: Optional[Decimal]

    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]

    rsi: Optional[float]
