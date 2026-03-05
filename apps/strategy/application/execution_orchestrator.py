"""
执行编排 UseCase - Application 层

M3 核心组件：编排订单执行流程

遵循项目架构约束：
- 通过依赖注入使用 Protocol 接口
- 不直接依赖 ORM Model
- 编排业务逻辑流程

执行流程：
1. 接收交易请求
2. 调用 DecisionPolicyEngine 做决策
3. 调用 SizingEngine 计算仓位
4. 调用 PreTradeRiskGate 做风控检查
5. 构建 OrderIntent
6. 使用 ExecutionAdapter 提交订单
7. 记录审计日志
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from apps.strategy.domain.entities import (
    OrderIntent,
    OrderSide,
    OrderStatus,
    DecisionResult,
    DecisionAction,
    SizingResult,
    RiskSnapshot,
)
from apps.strategy.domain.protocols import (
    ExecutionAdapterProtocol,
    OrderIntentRepositoryProtocol,
)
from apps.strategy.domain.services import (
    DecisionPolicyEngine,
    SizingEngine,
    PreTradeRiskGate,
)

logger = logging.getLogger(__name__)


# ========================================================================
# 执行模式
# ========================================================================

class ExecutionMode:
    """执行模式"""
    PAPER = "paper"
    BROKER = "broker"
    CANARY = "canary"  # 金丝雀模式：部分实盘


# ========================================================================
# 执行配置
# ========================================================================

@dataclass
class ExecutionConfig:
    """执行配置"""
    mode: str = ExecutionMode.PAPER
    broker_canary_ratio: float = 0.0  # 金丝雀比例 (0.0 - 1.0)
    require_confirmation_for_watch: bool = True  # WATCH 状态是否需要人工确认

    # 决策引擎配置
    signal_threshold: float = 0.6
    confidence_threshold: float = 0.7
    regime_alignment_required: bool = True

    # 仓位引擎配置
    default_sizing_method: str = "fixed_fraction"
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0

    # 风控配置
    max_single_position_pct: float = 20.0
    max_daily_trades: int = 10
    max_daily_loss_pct: float = 5.0


# ========================================================================
# 执行结果
# ========================================================================

@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    intent_id: str
    broker_order_id: Optional[str] = None
    status: str = "draft"
    error_message: Optional[str] = None
    decision_result: Optional[DecisionResult] = None
    sizing_result: Optional[SizingResult] = None
    risk_check_passed: bool = False
    risk_violations: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)


# ========================================================================
# 执行编排器
# ========================================================================

class ExecutionOrchestrator:
    """
    执行编排器

    职责：
    1. 接收交易请求
    2. 调用决策引擎判断是否应该交易
    3. 调用仓位引擎计算交易量
    4. 调用风控门检查风险
    5. 构建订单意图
    6. 选择执行适配器
    7. 提交订单
    8. 记录审计日志
    """

    def __init__(
        self,
        intent_repository: OrderIntentRepositoryProtocol,
        paper_adapter: ExecutionAdapterProtocol,
        broker_adapter: Optional[ExecutionAdapterProtocol],
        config: ExecutionConfig,
        audit_logger: Optional[Any] = None,
    ):
        """
        初始化执行编排器

        Args:
            intent_repository: 订单意图仓储
            paper_adapter: 模拟执行适配器
            broker_adapter: 券商执行适配器（可选）
            config: 执行配置
            audit_logger: 审计日志记录器（可选）
        """
        self.intent_repository = intent_repository
        self.paper_adapter = paper_adapter
        self.broker_adapter = broker_adapter
        self.config = config
        self.audit_logger = audit_logger

        # 初始化引擎
        self.decision_engine = DecisionPolicyEngine(
            signal_threshold=config.signal_threshold,
            confidence_threshold=config.confidence_threshold,
            regime_alignment_required=config.regime_alignment_required,
        )

        self.sizing_engine = SizingEngine(
            default_method=config.default_sizing_method,
            risk_per_trade_pct=config.risk_per_trade_pct,
            max_position_pct=config.max_position_pct,
        )

        self.risk_gate = PreTradeRiskGate(
            max_single_position_pct=config.max_single_position_pct,
            max_daily_trades=config.max_daily_trades,
            max_daily_loss_pct=config.max_daily_loss_pct,
        )

    def execute(
        self,
        strategy_id: int,
        portfolio_id: int,
        symbol: str,
        side: str,
        signal_strength: float,
        signal_confidence: float,
        current_price: float,
        account_equity: float,
        current_position_value: float,
        daily_trade_count: int,
        daily_pnl_pct: float,
        regime: str = "Unknown",
        regime_confidence: float = 0.5,
        stop_loss_price: Optional[float] = None,
        atr: Optional[float] = None,
        reason: str = "",
        idempotency_key: Optional[str] = None,
        target_regime: Optional[str] = None,
        volatility_z: Optional[float] = None,
        avg_volume: Optional[float] = None,
    ) -> ExecutionResult:
        """
        执行交易

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID
            symbol: 资产代码
            side: 买卖方向 (buy/sell)
            signal_strength: 信号强度
            signal_confidence: 信号置信度
            current_price: 当前价格
            account_equity: 账户权益
            current_position_value: 当前持仓市值
            daily_trade_count: 当日交易次数
            daily_pnl_pct: 当日盈亏比例
            regime: 当前 Regime
            regime_confidence: Regime 置信度
            stop_loss_price: 止损价
            atr: ATR 值
            reason: 下单原因
            idempotency_key: 幂等键（可选）
            target_regime: 目标 Regime
            volatility_z: 波动率 Z 分数
            avg_volume: 平均成交量

        Returns:
            执行结果
        """
        intent_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        final_idempotency_key = idempotency_key or intent_id

        try:
            # 0. 幂等检查：相同幂等键直接返回已有意图
            existing_intent = self.intent_repository.get_by_idempotency_key(final_idempotency_key)
            if existing_intent is not None:
                return ExecutionResult(
                    success=True,
                    intent_id=existing_intent.intent_id,
                    status=existing_intent.status.value,
                    error_message="idempotent_replay",
                )

            # 1. 决策检查
            decision_action, reason_codes, reason_text, valid_until = self.decision_engine.evaluate(
                signal_strength=signal_strength,
                signal_direction=side,
                signal_confidence=signal_confidence,
                regime=regime,
                regime_confidence=regime_confidence,
                daily_pnl_pct=daily_pnl_pct,
                daily_trade_count=daily_trade_count,
                volatility_z=volatility_z,
                target_regime=target_regime,
            )

            # 构建决策结果
            decision_result = DecisionResult(
                action=DecisionAction(decision_action),
                reason_codes=reason_codes,
                reason_text=reason_text,
                valid_until=datetime.now(timezone.utc) + timedelta(seconds=valid_until) if valid_until else None,
                confidence=signal_confidence,
            )

            # 2. 如果决策是 DENY，直接返回
            if decision_result.action == DecisionAction.DENY:
                return ExecutionResult(
                    success=False,
                    intent_id=intent_id,
                    status="denied",
                    decision_result=decision_result,
                    error_message=reason_text,
                )

            # 3. 仓位计算
            target_notional, qty, expected_risk_pct, sizing_method, sizing_explain = self.sizing_engine.calculate(
                method=self.config.default_sizing_method,
                account_equity=account_equity,
                current_price=current_price,
                stop_loss_price=stop_loss_price,
                atr=atr,
                current_position_value=current_position_value,
            )

            sizing_result = SizingResult(
                target_notional=target_notional,
                qty=qty,
                expected_risk_pct=expected_risk_pct,
                sizing_method=sizing_method,
                sizing_explain=sizing_explain,
            )

            # 4. 鉄风控检查
            passed, violations, warnings, details = self.risk_gate.check(
                symbol=symbol,
                side=side,
                qty=qty,
                price=current_price,
                account_equity=account_equity,
                current_position_value=current_position_value,
                daily_trade_count=daily_trade_count,
                daily_pnl_pct=daily_pnl_pct,
                avg_volume=avg_volume,
            )

            if not passed:
                return ExecutionResult(
                    success=False,
                    intent_id=intent_id,
                    status="rejected",
                    decision_result=decision_result,
                    sizing_result=sizing_result,
                    risk_check_passed=False,
                    risk_violations=violations,
                    risk_warnings=warnings,
                    error_message="; ".join(violations),
                )

            # 5. 构建风险快照
            risk_snapshot = RiskSnapshot(
                total_equity=account_equity,
                cash_balance=account_equity - current_position_value,
                total_position_value=current_position_value,
                daily_pnl_pct=daily_pnl_pct,
                max_single_position_pct=(current_position_value + qty * current_price) / account_equity * 100,
                top3_position_pct=current_position_value / account_equity * 100,  # 简化
                current_regime=regime,
                regime_confidence=regime_confidence,
                volatility_index=volatility_z,
                max_position_limit_pct=self.config.max_single_position_pct,
                daily_loss_limit_pct=self.config.max_daily_loss_pct,
                daily_trade_limit=self.config.max_daily_trades,
            )

            # 6. 构建订单意图
            intent = OrderIntent(
                intent_id=intent_id,
                strategy_id=strategy_id,
                portfolio_id=portfolio_id,
                symbol=symbol,
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                qty=qty,
                limit_price=current_price,
                decision=decision_result,
                sizing=sizing_result,
                risk_snapshot=risk_snapshot,
                reason=reason,
                idempotency_key=final_idempotency_key,
                status=OrderStatus.DRAFT,
                created_at=datetime.now(timezone.utc),
            )

            # 7. 保存订单意图
            saved_intent = self.intent_repository.save(intent)

            # 8. 处理 WATCH 状态
            if decision_result.action == DecisionAction.WATCH:
                if self.config.require_confirmation_for_watch:
                    self.intent_repository.update_status(intent_id, OrderStatus.PENDING_APPROVAL)
                    # 需要人工确认，保存为待审批状态
                    return ExecutionResult(
                        success=True,
                        intent_id=intent_id,
                        status="pending_approval",
                        decision_result=decision_result,
                        sizing_result=sizing_result,
                        risk_check_passed=True,
                        risk_warnings=warnings,
                    )

            # 9. 选择执行适配器
            adapter = self._select_adapter(portfolio_id)

            # 10. 提交订单
            try:
                broker_order_id = adapter.submit_order(saved_intent)

                # 更新状态为已发送
                self.intent_repository.update_status(intent_id, OrderStatus.SENT)

                # 11. 记录审计日志
                self._log_execution(
                    intent=saved_intent,
                    broker_order_id=broker_order_id,
                    adapter_name=adapter.get_name(),
                    duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                )

                return ExecutionResult(
                    success=True,
                    intent_id=intent_id,
                    broker_order_id=broker_order_id,
                    status="sent",
                    decision_result=decision_result,
                    sizing_result=sizing_result,
                    risk_check_passed=True,
                    risk_warnings=warnings,
                )

            except Exception as e:
                # 订单提交失败
                self.intent_repository.update_status(intent_id, OrderStatus.FAILED)
                logger.error(f"Order submission failed: {e}")

                return ExecutionResult(
                    success=False,
                    intent_id=intent_id,
                    status="failed",
                    decision_result=decision_result,
                    sizing_result=sizing_result,
                    risk_check_passed=True,
                    error_message=str(e),
                )

        except Exception as e:
            logger.error(f"Execution orchestration failed: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                intent_id=intent_id,
                status="error",
                error_message=str(e),
            )

    def _select_adapter(self, portfolio_id: int) -> ExecutionAdapterProtocol:
        """
        选择执行适配器

        根据配置模式选择适配器：
        - paper: 使用模拟适配器
        - broker: 使用券商适配器
        - canary: 根据比例随机选择

        Args:
            portfolio_id: 投资组合ID

        Returns:
            执行适配器
        """
        import random

        mode = self.config.mode

        if mode == ExecutionMode.PAPER:
            return self.paper_adapter

        elif mode == ExecutionMode.BROKER:
            if self.broker_adapter is None:
                logger.warning("Broker adapter not configured, falling back to paper adapter")
                return self.paper_adapter
            return self.broker_adapter

        elif mode == ExecutionMode.CANARY:
            # 金丝雀模式：根据比例随机选择
            if self.broker_adapter is None:
                return self.paper_adapter

            if random.random() < self.config.broker_canary_ratio:
                return self.broker_adapter
            return self.paper_adapter

        else:
            logger.warning(f"Unknown execution mode: {mode}, falling back to paper adapter")
            return self.paper_adapter

    def _log_execution(
        self,
        intent: OrderIntent,
        broker_order_id: str,
        adapter_name: str,
        duration_ms: int,
    ) -> None:
        """
        记录执行审计日志

        Args:
            intent: 订单意图
            broker_order_id: 券商订单ID
            adapter_name: 适配器名称
            duration_ms: 执行时长（毫秒）
        """
        if self.audit_logger is None:
            return

        try:
            log_entry = {
                'event_type': 'ORDER_SUBMITTED',
                'intent_id': intent.intent_id,
                'strategy_id': intent.strategy_id,
                'portfolio_id': intent.portfolio_id,
                'symbol': intent.symbol,
                'side': intent.side.value,
                'qty': intent.qty,
                'limit_price': intent.limit_price,
                'broker_order_id': broker_order_id,
                'adapter_name': adapter_name,
                'decision_action': intent.decision.action.value,
                'decision_reasons': intent.decision.reason_codes,
                'sizing_method': intent.sizing.sizing_method,
                'expected_risk_pct': intent.sizing.expected_risk_pct,
                'duration_ms': duration_ms,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

            self.audit_logger.log(log_entry)

        except Exception as e:
            logger.error(f"Failed to log execution audit: {e}")
