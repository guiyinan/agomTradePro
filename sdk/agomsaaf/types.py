"""
AgomSAAF SDK 类型定义

定义所有 API 返回的数据类型。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

# =============================================================================
# Regime 相关类型
# =============================================================================

RegimeType = Literal["Recovery", "Overheat", "Stagflation", "Repression"]
GrowthLevel = Literal["up", "down", "neutral"]
InflationLevel = Literal["up", "down", "neutral"]


@dataclass(frozen=True)
class RegimeState:
    """
    宏观象限状态

    Attributes:
        dominant_regime: 主导象限（Recovery/Overheat/Stagflation/Repression）
        observed_at: 观测日期
        growth_level: 增长水平（up/down/neutral）
        inflation_level: 通胀水平（up/down/neutral）
        growth_indicator: 增长指标（如 PMI）
        inflation_indicator: 通胀指标（如 CPI）
        growth_value: 增长指标值
        inflation_value: 通胀指标值
        confidence: 置信度（可选）
    """

    dominant_regime: RegimeType
    observed_at: date
    growth_level: GrowthLevel
    inflation_level: InflationLevel
    growth_indicator: str
    inflation_indicator: str
    growth_value: Optional[float] = None
    inflation_value: Optional[float] = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class RegimeCalculationParams:
    """
    Regime 计算参数

    Attributes:
        as_of_date: 计算日期（None 表示最新）
        growth_indicator: 增长指标代码
        inflation_indicator: 通胀指标代码
        use_kalman: 是否使用 Kalman 滤波
    """

    as_of_date: Optional[date] = None
    growth_indicator: str = "PMI"
    inflation_indicator: str = "CPI"
    use_kalman: bool = True


# =============================================================================
# Signal 相关类型
# =============================================================================

SignalStatus = Literal["pending", "approved", "rejected", "invalidated"]


@dataclass(frozen=True)
class InvestmentSignal:
    """
    投资信号

    Attributes:
        id: 信号 ID
        asset_code: 资产代码
        logic_desc: 逻辑描述
        invalidation_logic: 证伪逻辑
        invalidation_threshold: 证伪阈值
        status: 信号状态
        created_at: 创建时间
        approved_at: 审批时间
        invalidated_at: 失效时间
        created_by: 创建人
    """

    id: int
    asset_code: str
    logic_desc: str
    status: SignalStatus
    created_at: datetime
    invalidation_logic: Optional[str] = None
    invalidation_threshold: Optional[float] = None
    approved_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    created_by: Optional[str] = None


@dataclass(frozen=True)
class SignalEligibilityResult:
    """
    信号准入检查结果

    Attributes:
        is_eligible: 是否准入
        regime_match: 是否匹配当前象限
        policy_match: 是否匹配政策档位
        rejection_reason: 拒绝原因
        current_regime: 当前象限
        policy_status: 政策状态
    """

    is_eligible: bool
    regime_match: bool
    policy_match: bool
    current_regime: Optional[RegimeType] = None
    policy_status: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class CreateSignalParams:
    """
    创建投资信号参数

    Attributes:
        asset_code: 资产代码
        logic_desc: 逻辑描述
        invalidation_logic: 证伪逻辑
        invalidation_threshold: 证伪阈值
        target_regime: 目标象限（可选）
    """

    asset_code: str
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: float
    target_regime: Optional[RegimeType] = None


# =============================================================================
# Macro 相关类型
# =============================================================================

@dataclass(frozen=True)
class MacroIndicator:
    """
    宏观指标

    Attributes:
        code: 指标代码
        name: 指标名称
        unit: 单位
        frequency: 频率
        data_source: 数据源
    """

    code: str
    name: str
    unit: str
    frequency: str
    data_source: str


@dataclass(frozen=True)
class MacroDataPoint:
    """
    宏观数据点

    Attributes:
        indicator_code: 指标代码
        date: 日期
        value: 数值
        unit: 单位
    """

    indicator_code: str
    date: date
    value: float
    unit: str


# =============================================================================
# Policy 相关类型
# =============================================================================

PolicyGear = Literal["stimulus", "neutral", "tightening"]
PolicyLevel = Literal["P0", "P1", "P2", "P3"]
GateLevel = Literal["L0", "L1", "L2", "L3"]
EventType = Literal["policy", "hotspot", "sentiment", "mixed"]


@dataclass(frozen=True)
class PolicyStatus:
    """
    政策状态

    Attributes:
        current_gear: 当前档位
        observed_at: 观测日期
        recent_events: 最近事件
    """

    current_gear: PolicyGear
    observed_at: date
    recent_events: list = field(default_factory=list)


@dataclass(frozen=True)
class PolicyEvent:
    """
    政策事件

    Attributes:
        id: 事件 ID
        event_date: 事件日期
        event_type: 事件类型
        description: 描述
        gear: 政策档位
    """

    id: int
    event_date: date
    event_type: str
    description: str
    gear: PolicyGear


@dataclass(frozen=True)
class WorkbenchSummary:
    """
    工作台概览

    Attributes:
        policy_level: 当前政策档位 (P0-P3)
        policy_level_name: 政策档位名称
        gate_level: 热点情绪闸门等级 (L0-L3)
        gate_level_name: 闸门等级名称
        global_heat: 全局热度评分 (0-100)
        global_sentiment: 全局情绪评分 (-1.0 ~ +1.0)
        pending_review_count: 待审核数量
        sla_exceeded_count: SLA 超时数量
        today_events_count: 今日新增事件数量
    """

    policy_level: PolicyLevel
    policy_level_name: str
    gate_level: Optional[GateLevel] = None
    gate_level_name: Optional[str] = None
    global_heat: Optional[float] = None
    global_sentiment: Optional[float] = None
    pending_review_count: int = 0
    sla_exceeded_count: int = 0
    today_events_count: int = 0


@dataclass(frozen=True)
class WorkbenchEvent:
    """
    工作台事件

    Attributes:
        id: 事件 ID
        event_date: 事件日期
        event_type: 事件类型 (policy/hotspot/sentiment/mixed)
        level: 政策档位 (P0-P3)
        title: 标题
        description: 描述
        gate_level: 闸门等级 (L0-L3)
        gate_effective: 是否已生效
        audit_status: 审核状态
        ai_confidence: AI 置信度
        heat_score: 热度评分
        sentiment_score: 情绪评分
        asset_class: 资产分类
        created_at: 创建时间
    """

    id: int
    event_date: date
    event_type: EventType
    level: PolicyLevel
    title: str
    description: Optional[str] = None
    gate_level: Optional[GateLevel] = None
    gate_effective: bool = False
    audit_status: str = "pending_review"
    ai_confidence: Optional[float] = None
    heat_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    asset_class: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class WorkbenchItemsResult:
    """
    工作台事件列表结果

    Attributes:
        items: 事件列表
        total_count: 总数量
        page: 当前页码
        page_size: 每页数量
    """

    items: list[WorkbenchEvent] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class SentimentGateState:
    """
    热点情绪闸门状态

    Attributes:
        gate_level: 闸门等级 (L0-L3)
        global_heat: 全局热度评分
        global_sentiment: 全局情绪评分
        max_position_cap: 最大仓位上限
        signal_paused: 信号是否暂停
    """

    gate_level: GateLevel
    global_heat: float
    global_sentiment: float
    max_position_cap: Optional[float] = None
    signal_paused: bool = False


# =============================================================================
# Backtest 相关类型
# =============================================================================

@dataclass(frozen=True)
class BacktestParams:
    """
    回测参数

    Attributes:
        strategy_name: 策略名称
        start_date: 开始日期
        end_date: 结束日期
        initial_capital: 初始资金
    """

    strategy_name: str
    start_date: date
    end_date: date
    initial_capital: float


@dataclass(frozen=True)
class BacktestResult:
    """
    回测结果

    Attributes:
        id: 回测 ID
        status: 状态
        total_return: 总收益率
        annual_return: 年化收益率
        max_drawdown: 最大回撤
        sharpe_ratio: 夏普比率
    """

    id: int
    status: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: Optional[float] = None


# =============================================================================
# Account 相关类型
# =============================================================================

@dataclass(frozen=True)
class Position:
    """
    持仓信息

    Attributes:
        asset_code: 资产代码
        quantity: 数量
        avg_cost: 平均成本
        current_price: 当前价格
        market_value: 市值
        profit_loss: 盈亏
    """

    asset_code: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    profit_loss: float


@dataclass(frozen=True)
class Portfolio:
    """
    投资组合

    Attributes:
        id: 组合 ID
        name: 名称
        total_value: 总市值
        cash: 现金
        positions: 持仓列表
    """

    id: int
    name: str
    total_value: float
    cash: float
    positions: list[Position] = field(default_factory=list)
