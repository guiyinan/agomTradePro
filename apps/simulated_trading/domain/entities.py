"""
模拟盘Domain层实体定义

遵循DDD原则：
- 使用dataclass定义值对象和实体
- Domain层纯净：只使用Python标准库
- 所有金融逻辑在此层定义
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


class AccountType(Enum):
    """账户类型"""
    REAL = "real"           # 真实账户(未来扩展)
    SIMULATED = "simulated" # 模拟账户


class TradeAction(Enum):
    """交易动作"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"     # 待执行
    EXECUTED = "executed"   # 已执行
    CANCELLED = "cancelled" # 已取消
    FAILED = "failed"       # 执行失败


@dataclass(frozen=True)
class FeeConfig:
    """
    交易费率配置实体

    支持按资产类型分别配置费率，遵循中国A股市场规则
    """
    config_id: int
    config_name: str                    # 配置名称(如"标准费率"、"VIP费率")
    asset_type: str                     # 资产类型(equity/fund/bond/all)

    # 手续费(双向)
    commission_rate_buy: float = 0.0003    # 买入手续费率(默认0.03%)
    commission_rate_sell: float = 0.0003   # 卖出手续费率(默认0.03%)
    min_commission: float = 5.0            # 最低手续费(元,不足按此收取)

    # 印花税(仅卖出,A股特有)
    stamp_duty_rate: float = 0.001         # 印花税率(卖出,默认0.1%)

    # 过户费(双向,仅上海市场股票)
    transfer_fee_rate: float = 0.00002     # 过户费率(默认0.002%)
    min_transfer_fee: float = 0.0          # 最低过户费(元)

    # 滑点(模拟市场冲击)
    slippage_rate: float = 0.001           # 滑点率(默认0.1%)

    # 其他配置
    is_default: bool = False               # 是否为默认配置
    is_active: bool = True                 # 是否启用
    description: str = ""                  # 配置说明

    def calculate_buy_fee(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算买入费用

        Args:
            amount: 成交金额(元)
            is_shanghai: 是否上海市场(影响过户费)

        Returns:
            {
                'commission': 手续费,
                'transfer_fee': 过户费,
                'slippage': 滑点,
                'total_fee': 总费用
            }
        """
        # 1. 手续费(不低于最低手续费)
        commission = max(amount * self.commission_rate_buy, self.min_commission)

        # 2. 过户费(仅上海市场股票,基金/债券无)
        transfer_fee = 0.0
        if is_shanghai and self.asset_type == "equity":
            transfer_fee = max(amount * self.transfer_fee_rate, self.min_transfer_fee)

        # 3. 滑点
        slippage = amount * self.slippage_rate

        total_fee = commission + transfer_fee + slippage

        return {
            'commission': round(commission, 2),
            'transfer_fee': round(transfer_fee, 2),
            'stamp_duty': 0.0,  # 买入无印花税
            'slippage': round(slippage, 2),
            'total_fee': round(total_fee, 2)
        }

    def calculate_sell_fee(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算卖出费用

        Args:
            amount: 成交金额(元)
            is_shanghai: 是否上海市场

        Returns:
            {
                'commission': 手续费,
                'stamp_duty': 印花税,
                'transfer_fee': 过户费,
                'slippage': 滑点,
                'total_fee': 总费用
            }
        """
        # 1. 手续费
        commission = max(amount * self.commission_rate_sell, self.min_commission)

        # 2. 印花税(仅股票,基金/债券无)
        stamp_duty = 0.0
        if self.asset_type == "equity":
            stamp_duty = amount * self.stamp_duty_rate

        # 3. 过户费(仅上海市场股票)
        transfer_fee = 0.0
        if is_shanghai and self.asset_type == "equity":
            transfer_fee = max(amount * self.transfer_fee_rate, self.min_transfer_fee)

        # 4. 滑点
        slippage = amount * self.slippage_rate

        total_fee = commission + stamp_duty + transfer_fee + slippage

        return {
            'commission': round(commission, 2),
            'stamp_duty': round(stamp_duty, 2),
            'transfer_fee': round(transfer_fee, 2),
            'slippage': round(slippage, 2),
            'total_fee': round(total_fee, 2)
        }


@dataclass(frozen=True)
class SimulatedAccount:
    """模拟账户实体"""
    account_id: int
    account_name: str
    account_type: AccountType

    # 资金信息
    initial_capital: float          # 初始资金(元)
    current_cash: float             # 当前现金(元)
    current_market_value: float     # 当前持仓市值(元)
    total_value: float              # 总资产 = 现金 + 持仓市值

    # 绩效指标
    total_return: float = 0.0       # 总收益率(%)
    annual_return: float = 0.0      # 年化收益率(%)
    max_drawdown: float = 0.0       # 最大回撤(%)
    sharpe_ratio: float = 0.0       # 夏普比率
    win_rate: float = 0.0           # 胜率(%)

    # 交易统计
    total_trades: int = 0           # 总交易次数
    winning_trades: int = 0         # 盈利交易次数

    # 时间信息
    start_date: date = field(default_factory=date.today)
    last_trade_date: date | None = None
    is_active: bool = True

    # 策略配置
    auto_trading_enabled: bool = True  # 是否启用自动交易
    max_position_pct: float = 20.0     # 单个资产最大持仓比例(%)
    max_total_position_pct: float = 95.0  # 总持仓比例上限(%)
    stop_loss_pct: float | None = None  # 止损比例(%)

    # 费用配置
    commission_rate: float = 0.0003    # 手续费率(0.03%)
    slippage_rate: float = 0.001       # 滑点率(0.1%)

    def available_cash_for_buy(self) -> float:
        """可用于买入的现金"""
        return self.current_cash * (self.max_total_position_pct / 100.0)

    def max_position_value(self) -> float:
        """单个资产最大持仓市值"""
        return self.total_value * (self.max_position_pct / 100.0)


@dataclass
class Position:
    """持仓信息

    包含基本的持仓信息和证伪条件跟踪。
    """
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str  # equity/fund/bond

    # 持仓数量 (Decimal 支持非整数股份)
    quantity: float             # 持仓数量(股/份)
    available_quantity: float   # 可卖数量(T+1)

    # 成本信息
    avg_cost: float             # 平均成本(元)
    total_cost: float           # 总成本 = quantity * avg_cost

    # 当前信息
    current_price: float        # 当前价格(元)
    market_value: float         # 市值 = quantity * current_price

    # 盈亏信息
    unrealized_pnl: float       # 浮动盈亏(元)
    unrealized_pnl_pct: float   # 浮动盈亏率(%)

    # 时间信息
    first_buy_date: date
    last_update_date: date

    # 关联信号
    signal_id: int | None = None
    entry_reason: str = ""

    # ==================== 证伪条件跟踪 ====================
    # 从信号继承的证伪条件（副本，即使信号被删除也不影响）
    invalidation_rule_json: str | None = None      # JSON 格式的证伪规则
    invalidation_description: str | None = None    # 人类可读的证伪描述

    # 证伪状态
    is_invalidated: bool = False                     # 是否已被证伪
    invalidation_reason: str | None = None         # 证伪原因
    invalidation_checked_at: datetime | None = None  # 最后检查时间
    # =====================================================

    @property
    def has_invalidation_rule(self) -> bool:
        """是否有证伪规则"""
        return self.invalidation_rule_json is not None

    @property
    def should_close(self) -> bool:
        """是否应该平仓（已证伪）"""
        return self.is_invalidated


@dataclass
class SimulatedTrade:
    """模拟交易记录"""
    trade_id: int
    account_id: int

    # 资产信息
    asset_code: str
    asset_name: str
    asset_type: str

    # 交易信息
    action: TradeAction         # BUY/SELL
    quantity: float             # 交易数量
    price: float                # 成交价格(元)
    amount: float               # 成交金额(元)

    # 时间信息(必须字段,无默认值)
    order_date: date            # 订单日期
    execution_date: date        # 执行日期
    execution_time: datetime    # 执行时间

    # 费用(有默认值)
    commission: float = 0.0     # 手续费(元)
    slippage: float = 0.0       # 滑点损失(元)
    total_cost: float = 0.0     # 总成本 = amount + commission + slippage

    # 盈亏(仅SELL时有)
    realized_pnl: float | None = None      # 已实现盈亏(元)
    realized_pnl_pct: float | None = None  # 已实现盈亏率(%)

    # 交易原因
    reason: str = ""            # 交易原因(如"信号触发"、"信号失效")
    signal_id: int | None = None

    # 状态
    status: OrderStatus = OrderStatus.PENDING


# ============================================================================
# 账户业绩与估值 Domain Entities
# ============================================================================

class CashFlowType(Enum):
    """统一账户外部现金流类型"""
    INITIAL_CAPITAL = "initial_capital"  # 初始入金
    DEPOSIT = "deposit"                  # 追加入金
    WITHDRAWAL = "withdrawal"            # 取款出金
    DIVIDEND = "dividend"               # 股息/分红
    INTEREST = "interest"               # 利息
    ADJUSTMENT = "adjustment"           # 手工调整


@dataclass(frozen=True)
class BenchmarkComponent:
    """
    账户基准成分（值对象）

    一个账户可配置多个基准成分（加权组合基准），
    权重之和必须大于 0 并由应用层归一化到 1。
    """
    account_id: int
    benchmark_code: str      # 指数代码，如 "000300.SH"
    weight: float            # 权重（归一化后，如 0.6）
    display_name: str        # 显示名称，如 "沪深300"
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class UnifiedAccountCashFlow:
    """
    统一账户外部现金流（值对象）

    真实盘从 CapitalFlowModel 回填并持续镜像；
    模拟盘默认写入一笔 initial_capital 初始入金。
    """
    flow_id: int
    account_id: int
    flow_type: CashFlowType
    amount: float            # 正数=入金，负数=出金
    flow_date: date
    source_app: str          # 来源 app，如 "account" 或 "simulated_trading"
    source_id: str = ""      # 来源记录 ID（如 CapitalFlowModel.id）
    notes: str = ""


@dataclass(frozen=True)
class ValuationRow:
    """
    持仓时点估值行（值对象）

    表示某日持仓中一只资产的估值快照。
    """
    asset_code: str
    asset_name: str
    asset_type: str
    quantity: float
    avg_cost: float
    close_price: float
    market_value: float
    weight: float            # 占总仓位市值的比例
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass(frozen=True)
class AccountValuationSummary:
    """账户整体估值摘要"""
    total_value: float
    cash: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float  # 相对于总成本


@dataclass(frozen=True)
class CoverageInfo:
    """数据覆盖范围说明"""
    data_start: Optional[date]
    data_end: Optional[date]
    warnings: List[str]


@dataclass(frozen=True)
class ValuationSnapshot:
    """
    账户时点持仓估值表（值对象）

    对应 GET /accounts/{id}/valuation-snapshot/?as_of_date=...
    """
    as_of_date: date
    account_summary: AccountValuationSummary
    rows: List[ValuationRow]
    coverage: CoverageInfo


@dataclass(frozen=True)
class ValuationTimelinePoint:
    """
    账户净值时间线上的一个时点（值对象）

    对应 valuation-timeline 响应中的 points 数组元素。
    """
    date: date
    cash: float
    market_value: float
    total_value: float
    net_value: float          # 单位净值（以初始净值=1 为基准）
    twr_cumulative: float     # 链式 TWR 累计收益（%）
    drawdown: float           # 当前回撤（%，正数表示回撤幅度）


@dataclass(frozen=True)
class PerformancePeriod:
    """业绩报告统计区间"""
    start_date: date
    end_date: date
    days: int


@dataclass(frozen=True)
class PerformanceReturns:
    """收益指标"""
    twr: Optional[float]             # 时间加权收益率（%）
    mwr: Optional[float]             # 资金加权收益率/XIRR（%）
    annualized_twr: Optional[float]  # 年化 TWR（%）
    annualized_mwr: Optional[float]  # 年化 MWR（%）


@dataclass(frozen=True)
class PerformanceRisk:
    """风险指标"""
    volatility: Optional[float]           # 年化波动率（%）
    downside_volatility: Optional[float]  # 下行波动率（%）
    max_drawdown: Optional[float]         # 最大回撤（%）


@dataclass(frozen=True)
class PerformanceRatios:
    """风险调整后收益比率"""
    sharpe: Optional[float]
    sortino: Optional[float]
    calmar: Optional[float]
    treynor: Optional[float]


@dataclass(frozen=True)
class BenchmarkStats:
    """相对基准指标"""
    benchmark_return: Optional[float]   # 基准收益率（%）
    excess_return: Optional[float]      # 超额收益（%）
    beta: Optional[float]
    alpha: Optional[float]
    tracking_error: Optional[float]     # 跟踪误差（%）
    information_ratio: Optional[float]  # 信息比率


@dataclass(frozen=True)
class TradeStats:
    """交易统计（基于已闭合交易）"""
    win_rate: Optional[float]      # 胜率（%）
    profit_factor: Optional[float] # 盈利因子
    total_closed_trades: int


@dataclass(frozen=True)
class PerformanceReport:
    """
    账户区间业绩报告（值对象）

    对应 GET /accounts/{id}/performance-report/?start_date=...&end_date=...
    """
    period: PerformancePeriod
    returns: PerformanceReturns
    risk: PerformanceRisk
    ratios: PerformanceRatios
    benchmark: Optional[BenchmarkStats]
    trade_stats: TradeStats
    coverage: CoverageInfo
    warnings: List[str]
