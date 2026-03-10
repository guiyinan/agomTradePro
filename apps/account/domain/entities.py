"""
Account Domain Entities

用户账户领域的核心实体定义。
遵循四层架构约束：只使用 Python 标准库（dataclasses, typing, datetime, decimal）。
禁止依赖 Django、Pandas 等外部库。
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, List
from enum import Enum


# ============================================================
# 资产分类系统 - 多维度灵活分类
# ============================================================

class RiskTolerance(Enum):
    """风险偏好"""
    CONSERVATIVE = "conservative"  # 保守型
    MODERATE = "moderate"          # 稳健型
    AGGRESSIVE = "aggressive"      # 激进型


class PositionSource(Enum):
    """持仓来源"""
    MANUAL = "manual"      # 手动录入
    SIGNAL = "signal"      # 投资信号
    BACKTEST = "backtest"  # 回测结果


class PositionStatus(Enum):
    """持仓状态"""
    ACTIVE = "active"      # 持有中
    CLOSED = "closed"      # 已平仓


class AssetClassType(Enum):
    """资产大类（预定义，不可修改）"""
    EQUITY = "equity"           # 股票
    FIXED_INCOME = "fixed_income"  # 固定收益/债券
    COMMODITY = "commodity"     # 商品
    CURRENCY = "currency"       # 外汇
    CASH = "cash"               # 现金
    FUND = "fund"               # 基金
    DERIVATIVE = "derivative"   # 衍生品
    OTHER = "other"             # 其他


class Region(Enum):
    """地区/国别（预定义）"""
    CN = "CN"           # 中国境内
    US = "US"           # 美国
    EU = "EU"           # 欧洲
    JP = "JP"           # 日本
    EM = "EM"           # 新兴市场
    GLOBAL = "GLOBAL"   # 全球
    OTHER = "OTHER"     # 其他


class CrossBorderFlag(Enum):
    """跨境标识"""
    DOMESTIC = "domestic"       # 境内资产
    QDII = "qdii"               # QDII基金（境内购买境外）
    DIRECT_FOREIGN = "direct_foreign"  # 直接境外投资


class InvestmentStyle(Enum):
    """投资风格（预定义，可扩展）"""
    GROWTH = "growth"           # 成长
    VALUE = "value"             # 价值
    BLEND = "blend"             # 混合
    CYCLICAL = "cyclical"       # 周期
    DEFENSIVE = "defensive"     # 防御
    QUALITY = "quality"         # 质量
    MOMENTUM = "momentum"       # 动量
    UNKNOWN = "unknown"         # 未知/不适用


@dataclass(frozen=True)
class AssetMetadata:
    """
    资产元数据实体

    存储每个资产代码的完整分类信息。
    这是系统的资产数据库，由管理员维护，用户查看。

    示例：
    - INDEX_CODE: 宽基指数 -> Equity, CN, Domestic, Growth
    - ETF_CODE: 市场ETF -> Fund, CN, Domestic, Blend
    - VN_QDII: 越南QDII基金 -> Fund, EM, QDII, Growth
    - TSLA.US: 特斯拉股票 -> Equity, US, DirectForeign, Growth
    """
    asset_code: str           # 资产代码
    name: str                 # 资产名称
    asset_class: AssetClassType  # 资产大类
    region: Region            # 地区
    cross_border: CrossBorderFlag  # 跨境标识
    style: InvestmentStyle    # 投资风格
    sector: Optional[str]     # 行业板块（用户可自定义）
    sub_class: Optional[str]  # 子类（用户可自定义，如"科技股"、"消费股"）
    description: str          # 描述

    def get_full_classification(self) -> str:
        """获取完整分类描述"""
        parts = [
            self.asset_class.value.upper(),
            self.region.value,
            self.cross_border.value,
        ]
        if self.sector:
            parts.append(self.sector)
        if self.style != InvestmentStyle.UNKNOWN:
            parts.append(self.style.value)
        return " | ".join(parts)

    def is_eligible_for_regime(self, regime: str, eligibility_matrix: Dict[str, Dict[str, str]]) -> bool:
        """
        检查资产在给定Regime下是否适合

        Args:
            regime: 当前Regime (Recovery/Overheat/Stagflation/Deflation)
            eligibility_matrix: 准入矩阵，格式如 {"equity_CN": {"Recovery": "preferred"}}
        """
        # 构建分类键
        class_key = f"{self.asset_class.value}_{self.region.value}"

        if class_key in eligibility_matrix and regime in eligibility_matrix[class_key]:
            eligibility = eligibility_matrix[class_key][regime]
            return eligibility in ("preferred", "neutral")

        return True  # 默认允许


@dataclass(frozen=True)
class AccountProfile:
    """
    用户账户配置实体

    用户的风险偏好和初始资金配置，用于计算仓位大小和投资建议。
    """
    user_id: int
    display_name: str
    initial_capital: Decimal
    risk_tolerance: RiskTolerance
    created_at: datetime

    def get_max_position_pct(self) -> float:
        """
        获取单一资产最大仓位百分比

        根据风险偏好返回：
        - 保守型：5%
        - 稳健型：10%
        - 激进型：20%
        """
        return {
            RiskTolerance.CONSERVATIVE: 0.05,
            RiskTolerance.MODERATE: 0.10,
            RiskTolerance.AGGRESSIVE: 0.20,
        }[self.risk_tolerance]


@dataclass(frozen=True)
class Position:
    """
    持仓实体

    记录用户持有的资产信息，包括持仓数量、成本、盈亏等。
    资产分类信息通过 asset_code 关联到 AssetMetadata 获取。
    """
    id: Optional[int]  # 数据库ID，新建时为None
    portfolio_id: int
    user_id: int
    asset_code: str          # 资产代码，如 "ASSET_CODE"
    shares: float            # 持仓数量
    avg_cost: Decimal        # 平均成本价
    current_price: Decimal   # 当前市价
    market_value: Decimal    # 市值
    unrealized_pnl: Decimal  # 未实现盈亏
    unrealized_pnl_pct: float  # 未实现盈亏百分比
    opened_at: datetime      # 开仓时间
    status: PositionStatus   # 持仓状态
    source: PositionSource   # 持仓来源
    source_id: Optional[int] # 关联的signal_id或backtest_id
    # 以下是冗余字段，用于快速查询（从AssetMetadata同步）
    asset_class: AssetClassType  # 资产大类
    region: Region            # 地区
    cross_border: CrossBorderFlag  # 跨境标识

    def calculate_pnl(self) -> tuple[Decimal, float]:
        """
        计算盈亏

        Returns:
            (盈亏金额, 盈亏百分比)
        """
        pnl = (self.current_price - self.avg_cost) * Decimal(str(self.shares))
        pnl_pct = float((self.current_price / self.avg_cost - 1) * 100)
        return pnl, pnl_pct


@dataclass(frozen=True)
class PortfolioSnapshot:
    """
    组合快照

    某个时刻的投资组合完整状态。
    """
    portfolio_id: int
    user_id: int
    name: str
    snapshot_date: datetime
    cash_balance: Decimal     # 现金余额
    total_value: Decimal      # 总资产
    invested_value: Decimal   # 投资市值
    total_return: Decimal     # 总收益
    total_return_pct: float   # 总收益率
    positions: List[Position] # 持仓列表

    def get_cash_ratio(self) -> float:
        """计算现金仓位比例"""
        if self.total_value == 0:
            return 1.0
        return float(self.cash_balance / self.total_value)

    def get_invested_ratio(self) -> float:
        """计算投资仓位比例"""
        if self.total_value == 0:
            return 0.0
        return float(self.invested_value / self.total_value)


@dataclass(frozen=True)
class Transaction:
    """
    交易记录实体

    记录每一笔交易的详细信息。
    """
    id: Optional[int]
    portfolio_id: int
    user_id: int
    position_id: Optional[int]  # 关联的持仓ID，平仓时有值
    asset_code: str
    action: str                 # "buy" 或 "sell"
    shares: float
    price: Decimal
    notional: Decimal           # 交易金额
    commission: Decimal         # 手续费
    traded_at: datetime
    notes: str                  # 备注


@dataclass(frozen=True)
class AssetAllocation:
    """
    资产配置分布

    支持多维度统计：按大类、地区、风格等维度聚合。
    """
    dimension: str            # 统计维度：asset_class, region, cross_border, style, sector
    dimension_value: str      # 维度值（如 "equity", "CN", "domestic"）
    count: int                # 持仓数量
    market_value: Decimal     # 市值
    percentage: float         # 占比
    asset_codes: List[str]    # 包含的资产代码列表

    def get_display_name(self) -> str:
        """获取显示名称"""
        display_map = {
            # 资产大类
            "equity": "股票",
            "fixed_income": "债券",
            "commodity": "商品",
            "cash": "现金",
            "fund": "基金",
            # 地区
            "CN": "中国",
            "US": "美国",
            "EU": "欧洲",
            "EM": "新兴市场",
            "GLOBAL": "全球",
            # 跨境
            "domestic": "境内",
            "qdii": "QDII",
            "direct_foreign": "境外直投",
            # 风格
            "growth": "成长",
            "value": "价值",
            "blend": "混合",
            "defensive": "防御",
        }
        return display_map.get(self.dimension_value, self.dimension_value)


@dataclass(frozen=True)
class RegimeMatchAnalysis:
    """
    Regime匹配度分析

    分析当前持仓与Regime环境的匹配程度。
    """
    regime: str                # 当前Regime
    total_match_score: float   # 总体匹配度 (0-100)
    preferred_assets: List[str]      # 优选资产列表
    neutral_assets: List[str]        # 中性资产列表
    hostile_assets: List[str]        # 不匹配资产列表
    recommendations: List[str]        # 调仓建议


# ============================================================
# 止损止盈相关实体
# ============================================================

class StopLossType(Enum):
    """止损类型"""
    FIXED = "fixed"           # 固定止损（如 -10%）
    TRAILING = "trailing"     # 移动止损（随价格上涨上移）
    TIME_BASED = "time_based" # 时间止损（持仓超过N天）


class StopLossStatus(Enum):
    """止损状态"""
    ACTIVE = "active"         # 激活中
    TRIGGERED = "triggered"   # 已触发
    CANCELLED = "cancelled"   # 已取消
    EXPIRED = "expired"       # 已过期


@dataclass(frozen=True)
class StopLossConfig:
    """
    止损配置

    定义单个持仓的止损规则。
    """
    position_id: int          # 关联的持仓ID
    stop_loss_type: StopLossType  # 止损类型
    stop_loss_pct: float      # 止损百分比（如 -0.10 表示 -10%）
    trailing_stop_pct: Optional[float] = None  # 移动止损百分比
    max_holding_days: Optional[int] = None     # 最大持仓天数
    activated_at: Optional[datetime] = None    # 激活时间
    status: StopLossStatus = StopLossStatus.ACTIVE

    def calculate_stop_price(self, entry_price: float, current_price: float, highest_price: float) -> float:
        """
        计算止损价格

        Args:
            entry_price: 开仓价格
            current_price: 当前价格
            highest_price: 持仓期间最高价

        Returns:
            止损价格
        """
        if self.stop_loss_type == StopLossType.FIXED:
            # 固定止损：开仓价 * (1 - 止损百分比)
            return entry_price * (1 + self.stop_loss_pct)

        elif self.stop_loss_type == StopLossType.TRAILING:
            # 移动止损：最高价 * (1 - 移动止损百分比)
            trailing_pct = self.trailing_stop_pct or self.stop_loss_pct
            return highest_price * (1 - trailing_pct)

        elif self.stop_loss_type == StopLossType.TIME_BASED:
            # 时间止损不基于价格，返回0表示不触发
            return 0.0

        return entry_price * (1 + self.stop_loss_pct)


@dataclass(frozen=True)
class StopLossTrigger:
    """
    止损触发记录

    记录一次止损触发的详细信息。
    """
    id: Optional[int]
    position_id: int          # 关联的持仓ID
    trigger_type: StopLossType  # 触发类型
    trigger_price: float      # 触发时的价格
    trigger_time: datetime    # 触发时间
    trigger_reason: str       # 触发原因描述
    pnl: Decimal              # 触发时的盈亏金额
    pnl_pct: float            # 触发时的盈亏百分比
    notes: str                # 备注


@dataclass(frozen=True)
class TradingCostConfig:
    """
    交易费率配置

    每个投资组合可独立配置交易费率，遵循中国A股市场规则。
    """
    id: Optional[int]
    portfolio_id: int

    # 佣金（双向）
    commission_rate: float = 0.00025       # 佣金率（默认万2.5）
    min_commission: float = 5.0            # 最低佣金（元）

    # 印花税（仅卖出，A股特有）
    stamp_duty_rate: float = 0.001         # 印花税率（默认千1）

    # 过户费（双向，沪市股票）
    transfer_fee_rate: float = 0.00002     # 过户费率（默认万0.2）

    # 是否启用
    is_active: bool = True

    def calculate_buy_cost(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算买入总费用

        Args:
            amount: 成交金额（元）
            is_shanghai: 是否上海市场（影响过户费）

        Returns:
            各项费用明细
        """
        commission = max(amount * self.commission_rate, self.min_commission)
        transfer_fee = amount * self.transfer_fee_rate if is_shanghai else 0.0
        total = commission + transfer_fee

        return {
            "commission": round(commission, 2),
            "stamp_duty": 0.0,
            "transfer_fee": round(transfer_fee, 2),
            "total": round(total, 2),
        }

    def calculate_sell_cost(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算卖出总费用

        Args:
            amount: 成交金额（元）
            is_shanghai: 是否上海市场

        Returns:
            各项费用明细
        """
        commission = max(amount * self.commission_rate, self.min_commission)
        stamp_duty = amount * self.stamp_duty_rate
        transfer_fee = amount * self.transfer_fee_rate if is_shanghai else 0.0
        total = commission + stamp_duty + transfer_fee

        return {
            "commission": round(commission, 2),
            "stamp_duty": round(stamp_duty, 2),
            "transfer_fee": round(transfer_fee, 2),
            "total": round(total, 2),
        }


@dataclass(frozen=True)
class TakeProfitConfig:
    """
    止盈配置

    定义单个持仓的止盈规则。
    """
    position_id: int          # 关联的持仓ID
    take_profit_pct: float    # 止盈百分比（如 0.20 表示 +20%）
    partial_profit_levels: Optional[List[float]] = None  # 分批止盈点位
    is_active: bool = True    # 是否激活

    def calculate_take_profit_price(self, entry_price: float) -> float:
        """
        计算止盈价格

        Args:
            entry_price: 开仓价格

        Returns:
            止盈价格
        """
        return entry_price * (1 + self.take_profit_pct)
