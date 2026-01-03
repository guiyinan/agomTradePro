"""
基金分析模块 - Domain 层实体定义

遵循项目架构约束：
- 使用 dataclasses 定义值对象
- 不依赖任何外部库（pandas、numpy、django等）
- 只使用 Python 标准库
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, List


@dataclass(frozen=True)
class FundInfo:
    """基金基本信息（值对象）

    Attributes:
        fund_code: 基金代码（如 '110011'）
        fund_name: 基金名称
        fund_type: 基金类型（股票型/债券型/混合型/指数型/货币型/QDII等）
        investment_style: 投资风格（成长/价值/平衡/商品等）
        setup_date: 成立日期
        management_company: 管理人
        custodian: 托管人
        fund_scale: 基金规模（元）
    """
    fund_code: str
    fund_name: str
    fund_type: str  # '股票型', '债券型', '混合型', '指数型', '货币型', 'QDII', '商品型'
    investment_style: Optional[str] = None  # '成长', '价值', '平衡', '商品', '稳健'
    setup_date: Optional[date] = None
    management_company: Optional[str] = None
    custodian: Optional[str] = None
    fund_scale: Optional[Decimal] = None  # 单位：元


@dataclass(frozen=True)
class FundManager:
    """基金经理信息（值对象）

    Attributes:
        fund_code: 基金代码
        manager_name: 经理姓名
        tenure_start: 任职开始日期
        tenure_end: 任职结束日期（None 表示在任）
        total_tenure_days: 任期天数
        fund_return: 任期期间基金收益率
    """
    fund_code: str
    manager_name: str
    tenure_start: date
    tenure_end: Optional[date] = None
    total_tenure_days: Optional[int] = None
    fund_return: Optional[float] = None  # %


@dataclass(frozen=True)
class FundNetValue:
    """基金净值数据（值对象）

    Attributes:
        fund_code: 基金代码
        nav_date: 净值日期
        unit_nav: 单位净值
        accum_nav: 累计净值
        daily_return: 日收益率（%）
        daily_return_optional: 可选的日收益率（某些情况下可能为空）
    """
    fund_code: str
    nav_date: date
    unit_nav: Decimal
    accum_nav: Decimal
    daily_return: Optional[float] = None


@dataclass(frozen=True)
class FundHolding:
    """基金持仓数据（值对象）

    Attributes:
        fund_code: 基金代码
        report_date: 报告期
        stock_code: 股票代码
        stock_name: 股票名称
        holding_amount: 持有数量（股）
        holding_value: 持有市值（元）
        holding_ratio: 占净值比例（%）
    """
    fund_code: str
    report_date: date
    stock_code: str
    stock_name: str
    holding_amount: Optional[int] = None
    holding_value: Optional[Decimal] = None
    holding_ratio: Optional[float] = None


@dataclass(frozen=True)
class FundSectorAllocation:
    """基金行业配置（值对象）

    Attributes:
        fund_code: 基金代码
        report_date: 报告期
        sector_name: 行业名称
        allocation_ratio: 配置比例（%）
    """
    fund_code: str
    report_date: date
    sector_name: str
    allocation_ratio: float


@dataclass(frozen=True)
class FundPerformance:
    """基金业绩指标（值对象）

    Attributes:
        fund_code: 基金代码
        start_date: 计算起始日期
        end_date: 计算结束日期
        total_return: 区间收益率（%）
        annualized_return: 年化收益率（%）
        volatility: 波动率（%）
        sharpe_ratio: 夏普比率
        max_drawdown: 最大回撤（%）
        beta: 贝塔系数
        alpha: 阿尔法（%）
    """
    fund_code: str
    start_date: date
    end_date: date
    total_return: float
    annualized_return: Optional[float] = None
    volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    beta: Optional[float] = None
    alpha: Optional[float] = None


@dataclass(frozen=True)
class FundScore:
    """基金综合评分（值对象）

    Attributes:
        fund_code: 基金代码
        fund_name: 基金名称
        score_date: 评分日期
        performance_score: 业绩评分（0-100）
        regime_fit_score: Regime 适配度评分（0-100）
        risk_score: 风险评分（0-100）
        scale_score: 规模评分（0-100）
        total_score: 综合评分（0-100）
        rank: 排名
    """
    fund_code: str
    fund_name: str
    score_date: date
    performance_score: float
    regime_fit_score: float
    risk_score: float
    scale_score: float
    total_score: float
    rank: int
