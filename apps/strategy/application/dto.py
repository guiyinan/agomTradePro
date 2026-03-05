"""
Application 层 DTO（Data Transfer Objects）

用于 Application 层与 Interface 层之间的数据传输。
遵循项目架构约束：
- 不依赖 Django ORM
- 使用 dataclass 定义
- 可包含序列化/反序列化逻辑
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any

from apps.strategy.domain.entities import (
    OrderSide,
    OrderStatus,
    TimeInForce,
    DecisionAction,
    OrderIntent,
    DecisionResult,
    SizingResult,
    RiskSnapshot,
)


# ========================================================================
# 请求 DTO
# ========================================================================

@dataclass
class EvaluateExecutionRequestDTO:
    """执行评估请求 DTO"""
    strategy_id: int
    portfolio_id: int
    symbol: str
    side: str  # "buy" | "sell"
    signal_strength: Optional[float] = None
    signal_direction: Optional[str] = None
    signal_confidence: Optional[float] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubmitOrderIntentRequestDTO:
    """提交订单意图请求 DTO"""
    intent_id: str
    strategy_id: int
    portfolio_id: int
    symbol: str
    side: str
    qty: int
    limit_price: Optional[float] = None
    time_in_force: str = "day"
    reason: str = ""
    idempotency_key: Optional[str] = None


# ========================================================================
# 响应 DTO
# ========================================================================

@dataclass
class EvaluateExecutionResponseDTO:
    """执行评估响应 DTO"""
    # 决策结果
    action: str  # "allow" | "deny" | "watch"
    reason_codes: List[str]
    reason_text: str
    confidence: float

    # 仓位计算结果
    target_notional: float
    qty: int
    expected_risk_pct: float
    sizing_method: str
    sizing_explain: str

    # 风险快照
    risk_snapshot: Dict[str, Any]

    # 是否可以继续执行
    can_execute: bool
    requires_confirmation: bool

    @classmethod
    def from_domain(
        cls,
        decision: DecisionResult,
        sizing: SizingResult,
        risk_snapshot: RiskSnapshot
    ) -> 'EvaluateExecutionResponseDTO':
        """从领域对象创建 DTO"""
        return cls(
            action=decision.action.value,
            reason_codes=decision.reason_codes,
            reason_text=decision.reason_text,
            confidence=decision.confidence,
            target_notional=sizing.target_notional,
            qty=sizing.qty,
            expected_risk_pct=sizing.expected_risk_pct,
            sizing_method=sizing.sizing_method,
            sizing_explain=sizing.sizing_explain,
            risk_snapshot=risk_snapshot.to_dict(),
            can_execute=decision.action == DecisionAction.ALLOW,
            requires_confirmation=decision.action == DecisionAction.WATCH,
        )


@dataclass
class OrderIntentResponseDTO:
    """订单意图响应 DTO"""
    intent_id: str
    strategy_id: int
    portfolio_id: int
    symbol: str
    side: str
    qty: int
    limit_price: Optional[float]
    time_in_force: str
    status: str
    reason: str
    created_at: Optional[str]
    updated_at: Optional[str]

    # 决策信息
    decision_action: str
    decision_reasons: List[str]

    # 仓位信息
    sizing_method: str
    expected_risk_pct: float

    @classmethod
    def from_domain(cls, intent: OrderIntent) -> 'OrderIntentResponseDTO':
        """从领域对象创建 DTO"""
        return cls(
            intent_id=intent.intent_id,
            strategy_id=intent.strategy_id,
            portfolio_id=intent.portfolio_id,
            symbol=intent.symbol,
            side=intent.side.value,
            qty=intent.qty,
            limit_price=intent.limit_price,
            time_in_force=intent.time_in_force.value,
            status=intent.status.value,
            reason=intent.reason,
            created_at=intent.created_at.isoformat() if intent.created_at else None,
            updated_at=intent.updated_at.isoformat() if intent.updated_at else None,
            decision_action=intent.decision.action.value,
            decision_reasons=intent.decision.reason_codes,
            sizing_method=intent.sizing.sizing_method,
            expected_risk_pct=intent.sizing.expected_risk_pct,
        )


@dataclass
class OrderIntentListResponseDTO:
    """订单意图列表响应 DTO"""
    items: List[OrderIntentResponseDTO]
    total: int
    page: int
    page_size: int


@dataclass
class ExecutionAdapterResultDTO:
    """执行适配器结果 DTO"""
    success: bool
    broker_order_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    executed_qty: int = 0
    executed_price: Optional[float] = None
    timestamp: Optional[str] = None


# ========================================================================
# 风控 DTO
# ========================================================================

@dataclass
class PreTradeRiskCheckRequestDTO:
    """预交易风控检查请求 DTO"""
    intent_id: str
    symbol: str
    side: str
    qty: int
    limit_price: Optional[float]
    portfolio_id: int
    strategy_id: int


@dataclass
class PreTradeRiskCheckResponseDTO:
    """预交易风控检查响应 DTO"""
    passed: bool
    violations: List[str]
    warnings: List[str]
    details: Dict[str, Any] = field(default_factory=dict)
