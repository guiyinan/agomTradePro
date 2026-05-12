"""
Domain 层实体定义

遵循项目架构约束：
- 只使用 Python 标准库（dataclasses, typing, enum, abc）
- 使用 @dataclass(frozen=True) 定义值对象
- 使用 @dataclass 定义实体
- 在 __post_init__ 中进行数据验证
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ========================================================================
# 枚举类型
# ========================================================================

class StrategyType(Enum):
    """策略类型"""
    RULE_BASED = "rule_based"      # 规则驱动
    SCRIPT_BASED = "script_based"  # 脚本驱动
    HYBRID = "hybrid"              # 混合模式
    AI_DRIVEN = "ai_driven"        # AI驱动


class RuleType(Enum):
    """规则类型"""
    MACRO = "macro"            # 宏观指标
    REGIME = "regime"          # Regime判定
    SIGNAL = "signal"          # 投资信号
    TECHNICAL = "technical"    # 技术指标
    COMPOSITE = "composite"    # 组合条件


class ActionType(Enum):
    """动作类型"""
    BUY = "buy"        # 买入
    SELL = "sell"      # 卖出
    HOLD = "hold"      # 持有
    WEIGHT = "weight"  # 设置权重


class ApprovalMode(Enum):
    """审核模式"""
    ALWAYS = "always"              # 必须人工审核
    CONDITIONAL = "conditional"    # 条件审核
    AUTO = "auto"                  # 自动执行


# ========================================================================
# 值对象
# ========================================================================

@dataclass(frozen=True)
class RiskControlParams:
    """风控参数（值对象）"""
    max_position_pct: float = 20.0
    max_total_position_pct: float = 95.0
    stop_loss_pct: float | None = None

    def __post_init__(self):
        """验证数据有效性"""
        if not 0 <= self.max_position_pct <= 100:
            raise ValueError(f"max_position_pct 必须在 0-100 之间: {self.max_position_pct}")

        if not 0 <= self.max_total_position_pct <= 100:
            raise ValueError(f"max_total_position_pct 必须在 0-100 之间: {self.max_total_position_pct}")

        if self.stop_loss_pct is not None:
            if not 0 <= self.stop_loss_pct <= 100:
                raise ValueError(f"stop_loss_pct 必须在 0-100 之间: {self.stop_loss_pct}")


@dataclass(frozen=True)
class StrategyConfig:
    """策略配置（值对象）"""
    strategy_type: StrategyType
    risk_params: RiskControlParams
    description: str = ""


@dataclass(frozen=True)
class ScriptConfig:
    """脚本配置（值对象）"""
    script_code: str
    script_language: str = "python"
    allowed_modules: list[str] = field(default_factory=list)
    sandbox_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证脚本语言"""
        if self.script_language not in ["python"]:
            raise ValueError(f"不支持的脚本语言: {self.script_language}")


@dataclass(frozen=True)
class AIConfig:
    """AI 配置（值对象）"""
    approval_mode: ApprovalMode = ApprovalMode.CONDITIONAL
    confidence_threshold: float = 0.8
    temperature: float = 0.7
    max_tokens: int = 2000
    prompt_template_id: int | None = None
    chain_config_id: int | None = None
    ai_provider_id: int | None = None

    def __post_init__(self):
        """验证参数"""
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError(f"confidence_threshold 必须在 0-1 之间: {self.confidence_threshold}")

        if not 0 <= self.temperature <= 2:
            raise ValueError(f"temperature 必须在 0-2 之间: {self.temperature}")

        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens 必须大于 0: {self.max_tokens}")


# ========================================================================
# 实体
# ========================================================================

@dataclass
class Strategy:
    """策略实体"""
    strategy_id: int | None  # None 表示未持久化
    name: str
    strategy_type: StrategyType
    version: int
    is_active: bool
    created_by_id: int

    # 配置
    config: StrategyConfig
    risk_params: RiskControlParams

    # 可选配置（根据策略类型）
    rule_conditions: list['RuleCondition'] | None = None
    script_config: ScriptConfig | None = None
    ai_config: AIConfig | None = None

    # 元数据
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        """验证数据一致性"""
        # 验证策略类型与配置的一致性
        if self.strategy_type == StrategyType.RULE_BASED:
            if self.rule_conditions is None or len(self.rule_conditions) == 0:
                raise ValueError("规则驱动策略必须包含至少一个规则条件")

        elif self.strategy_type == StrategyType.SCRIPT_BASED:
            if self.script_config is None:
                raise ValueError("脚本驱动策略必须包含脚本配置")

        elif self.strategy_type == StrategyType.AI_DRIVEN:
            if self.ai_config is None:
                raise ValueError("AI驱动策略必须包含AI配置")


@dataclass
class RuleCondition:
    """规则条件实体"""
    rule_id: int | None  # None 表示未持久化
    strategy_id: int | None

    # 规则标识
    rule_name: str
    rule_type: RuleType

    # 条件表达式（JSON格式）
    condition_json: dict[str, Any]

    # 触发动作
    action: ActionType
    weight: float | None = None
    target_assets: list[str] = field(default_factory=list)

    # 控制参数
    priority: int = 0
    is_enabled: bool = True

    # 元数据
    created_at: datetime | None = None

    def __post_init__(self):
        """验证数据"""
        # 验证权重范围
        if self.weight is not None:
            if not 0 <= self.weight <= 1:
                raise ValueError(f"weight 必须在 0-1 之间: {self.weight}")

        # 验证 condition_json 格式
        if not isinstance(self.condition_json, dict):
            raise ValueError("condition_json 必须是字典类型")

        if 'operator' not in self.condition_json:
            raise ValueError("condition_json 必须包含 'operator' 字段")


@dataclass
class SignalRecommendation:
    """信号推荐（策略执行结果）"""
    asset_code: str
    asset_name: str
    action: ActionType
    weight: float | None = None
    quantity: int | None = None
    reason: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """验证数据"""
        if self.weight is not None:
            if not 0 <= self.weight <= 1:
                raise ValueError(f"weight 必须在 0-1 之间: {self.weight}")

        if self.confidence < 0 or self.confidence > 1:
            raise ValueError(f"confidence 必须在 0-1 之间: {self.confidence}")


@dataclass
class StrategyExecutionResult:
    """策略执行结果"""
    strategy_id: int
    portfolio_id: int
    execution_time: datetime
    execution_duration_ms: int

    # 执行结果
    signals: list[SignalRecommendation]
    is_success: bool
    error_message: str = ""

    # 上下文信息
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        return {
            'strategy_id': self.strategy_id,
            'portfolio_id': self.portfolio_id,
            'execution_time': self.execution_time.isoformat(),
            'execution_duration_ms': self.execution_duration_ms,
            'signals': [
                {
                    'asset_code': s.asset_code,
                    'asset_name': s.asset_name,
                    'action': s.action.value,
                    'weight': s.weight,
                    'quantity': s.quantity,
                    'reason': s.reason,
                    'confidence': s.confidence,
                    'metadata': s.metadata
                }
                for s in self.signals
            ],
            'is_success': self.is_success,
            'error_message': self.error_message,
            'context': self.context
        }


# ========================================================================
# M0: 执行升级 - 订单意图与状态机
# ========================================================================

class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """订单状态"""
    DRAFT = "draft"                    # 草稿
    PENDING_APPROVAL = "pending_approval"  # 待审批
    APPROVED = "approved"              # 已批准
    REJECTED = "rejected"              # 已拒绝
    SENT = "sent"                      # 已发送
    PARTIAL_FILLED = "partial_filled"  # 部分成交
    FILLED = "filled"                  # 全部成交
    CANCELED = "canceled"              # 已取消
    FAILED = "failed"                  # 失败


class OrderEvent(Enum):
    """订单事件"""
    SUBMIT = "submit"          # 提交审批
    APPROVE = "approve"        # 批准
    REJECT = "reject"          # 拒绝
    SEND = "send"              # 发送到交易所
    PARTIAL_FILL = "partial_fill"  # 部分成交
    FILL = "fill"              # 全部成交
    CANCEL = "cancel"          # 取消
    FAIL = "fail"              # 失败


class TimeInForce(Enum):
    """订单时效"""
    DAY = "day"          # 当日有效
    GTC = "gtc"          # 撤销前有效
    IOC = "ioc"          # 立即成交或取消
    FOK = "fok"          # 全部成交或取消


class DecisionAction(Enum):
    """决策动作"""
    ALLOW = "allow"      # 允许交易
    DENY = "deny"        # 拒绝交易
    WATCH = "watch"      # 观察模式（需人工确认）


@dataclass(frozen=True)
class RiskSnapshot:
    """风险快照（值对象）- 记录下单时的风险状态"""
    # 账户风险
    total_equity: float
    cash_balance: float
    total_position_value: float
    daily_pnl_pct: float

    # 持仓集中度
    max_single_position_pct: float
    top3_position_pct: float

    # 市场状态
    current_regime: str
    regime_confidence: float
    volatility_index: float | None = None

    # 风控参数
    max_position_limit_pct: float = 20.0
    daily_loss_limit_pct: float = 5.0
    daily_trade_limit: int = 10

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'total_equity': self.total_equity,
            'cash_balance': self.cash_balance,
            'total_position_value': self.total_position_value,
            'daily_pnl_pct': self.daily_pnl_pct,
            'max_single_position_pct': self.max_single_position_pct,
            'top3_position_pct': self.top3_position_pct,
            'current_regime': self.current_regime,
            'regime_confidence': self.regime_confidence,
            'volatility_index': self.volatility_index,
            'max_position_limit_pct': self.max_position_limit_pct,
            'daily_loss_limit_pct': self.daily_loss_limit_pct,
            'daily_trade_limit': self.daily_trade_limit,
        }


@dataclass(frozen=True)
class SizingResult:
    """仓位计算结果（值对象）"""
    target_notional: float       # 目标名义金额
    qty: int                      # 数量
    expected_risk_pct: float      # 预期风险比例
    sizing_method: str            # 计算方法
    sizing_explain: str           # 计算说明

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'target_notional': self.target_notional,
            'qty': self.qty,
            'expected_risk_pct': self.expected_risk_pct,
            'sizing_method': self.sizing_method,
            'sizing_explain': self.sizing_explain,
        }


@dataclass(frozen=True)
class DecisionResult:
    """决策结果（值对象）"""
    action: DecisionAction
    reason_codes: list[str]
    reason_text: str
    valid_until: datetime | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'action': self.action.value,
            'reason_codes': self.reason_codes,
            'reason_text': self.reason_text,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'confidence': self.confidence,
        }


@dataclass
class OrderIntent:
    """订单意图实体 - 策略决策与执行解耦的核心对象"""
    # 唯一标识
    intent_id: str                        # UUID，全局唯一
    strategy_id: int                      # 关联策略
    portfolio_id: int                     # 关联投资组合

    # 订单基本信息
    symbol: str                           # 资产代码
    side: OrderSide                       # 买卖方向
    qty: int                              # 数量
    decision: DecisionResult              # 决策结果
    sizing: SizingResult                  # 仓位计算结果
    risk_snapshot: RiskSnapshot           # 风险快照
    limit_price: float | None = None   # 限价（None 表示市价单）
    time_in_force: TimeInForce = TimeInForce.DAY

    # 元数据
    reason: str = ""                      # 下单原因
    idempotency_key: str = ""             # 幂等键
    status: OrderStatus = OrderStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        """验证数据"""
        if self.qty <= 0:
            raise ValueError(f"qty 必须大于 0: {self.qty}")

        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError(f"limit_price 必须大于 0: {self.limit_price}")

        if not self.intent_id:
            raise ValueError("intent_id 不能为空")

        if not self.idempotency_key:
            # 默认使用 intent_id 作为幂等键
            object.__setattr__(self, 'idempotency_key', self.intent_id)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于序列化）"""
        return {
            'intent_id': self.intent_id,
            'strategy_id': self.strategy_id,
            'portfolio_id': self.portfolio_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'qty': self.qty,
            'limit_price': self.limit_price,
            'time_in_force': self.time_in_force.value,
            'decision': self.decision.to_dict(),
            'sizing': self.sizing.to_dict(),
            'risk_snapshot': self.risk_snapshot.to_dict(),
            'reason': self.reason,
            'idempotency_key': self.idempotency_key,
            'status': self.status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
