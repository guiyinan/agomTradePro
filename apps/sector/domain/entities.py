"""
板块分析模块 - Domain 层实体定义

遵循项目架构约束：
- 使用 dataclasses 定义值对象
- 不依赖任何外部库（pandas、numpy、django等）
- 只使用 Python 标准库
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class SectorInfo:
    """板块基本信息（值对象）

    Attributes:
        sector_code: 板块代码（如 '801010' 表示申万一级行业）
        sector_name: 板块名称（如 '农林牧渔'）
        level: 板块级别（SW1=申万一级, SW2=申万二级, SW3=申万三级）
        parent_code: 父级板块代码（对于一级板块为 None）
    """
    sector_code: str
    sector_name: str
    level: str  # 'SW1', 'SW2', 'SW3'
    parent_code: str | None = None


@dataclass(frozen=True)
class SectorIndex:
    """板块指数数据（值对象）

    Attributes:
        sector_code: 板块代码
        trade_date: 交易日期
        open_price: 开盘点位
        high: 最高点位
        low: 最低点位
        close: 收盘点位
        volume: 成交量（手）
        amount: 成交额（元）
        change_pct: 涨跌幅（%）
        turnover_rate: 换手率（%）
    """
    sector_code: str
    trade_date: date
    open_price: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int  # 成交量（手）
    amount: Decimal  # 成交额（元）
    change_pct: float  # 涨跌幅（%）
    turnover_rate: float | None = None  # 换手率（%）


@dataclass(frozen=True)
class SectorRelativeStrength:
    """板块相对强弱指标（值对象）

    Attributes:
        sector_code: 板块代码
        trade_date: 交易日期
        relative_strength: 相对强弱（相对于大盘指数，如沪深300）
        momentum: 动量指标（近期涨跌幅）
        beta: 贝塔系数（相对于大盘）
    """
    sector_code: str
    trade_date: date
    relative_strength: float  # 相对强弱（板块收益率 / 大盘收益率）
    momentum: float  # 动量（N日累计收益率，%）
    beta: float | None = None  # 贝塔系数


@dataclass(frozen=True)
class SectorScore:
    """板块综合评分（值对象）

    Attributes:
        sector_code: 板块代码
        sector_name: 板块名称
        trade_date: 评分日期
        momentum_score: 动量评分（0-100）
        relative_strength_score: 相对强弱评分（0-100）
        regime_fit_score: Regime 适配度评分（0-100）
        total_score: 综合评分（0-100）
        rank: 排名
    """
    sector_code: str
    sector_name: str
    trade_date: date
    momentum_score: float
    relative_strength_score: float
    regime_fit_score: float
    total_score: float
    rank: int
