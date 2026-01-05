"""
Domain 层实体定义

遵循项目架构约束：
- 只使用 Python 标准库（dataclasses, typing, enum, abc）
- 使用 @dataclass(frozen=True) 定义值对象
- 使用 @dataclass 定义实体
- 在 __post_init__ 中进行数据验证
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Dict, Optional, Any


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
    stop_loss_pct: Optional[float] = None

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
    allowed_modules: List[str] = field(default_factory=list)
    sandbox_config: Dict[str, Any] = field(default_factory=dict)

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
    prompt_template_id: Optional[int] = None
    chain_config_id: Optional[int] = None
    ai_provider_id: Optional[int] = None

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
    strategy_id: Optional[int]  # None 表示未持久化
    name: str
    strategy_type: StrategyType
    version: int
    is_active: bool
    created_by_id: int

    # 配置
    config: StrategyConfig
    risk_params: RiskControlParams

    # 可选配置（根据策略类型）
    rule_conditions: Optional[List['RuleCondition']] = None
    script_config: Optional[ScriptConfig] = None
    ai_config: Optional[AIConfig] = None

    # 元数据
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    rule_id: Optional[int]  # None 表示未持久化
    strategy_id: Optional[int]

    # 规则标识
    rule_name: str
    rule_type: RuleType

    # 条件表达式（JSON格式）
    condition_json: Dict[str, Any]

    # 触发动作
    action: ActionType
    weight: Optional[float] = None
    target_assets: List[str] = field(default_factory=list)

    # 控制参数
    priority: int = 0
    is_enabled: bool = True

    # 元数据
    created_at: Optional[datetime] = None

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
    weight: Optional[float] = None
    quantity: Optional[int] = None
    reason: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

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
    signals: List[SignalRecommendation]
    is_success: bool
    error_message: str = ""

    # 上下文信息
    context: Dict[str, Any] = field(default_factory=dict)

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
