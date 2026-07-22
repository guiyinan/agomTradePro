"""Decision precheck, execution, cancellation, and quota configuration use cases."""

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone

from apps.account.application.repository_provider import get_account_position_repository
from apps.alpha_trigger.domain.entities import AlphaCandidate, CandidateStatus
from apps.events.domain.entities import EventType, create_event

from ..domain.entities import (
    DecisionQuota,
    DecisionRequest,
    ExecutionStatus,
    ExecutionTarget,
    QuotaPeriod,
)
from ..domain.services import (
    CandidateStatusStateMachine,
    ExecutionResult,
    ExecutionStatusStateMachine,
    PrecheckResult,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    InvalidOperation,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class _SimulatedExecutionInput:
    """Validated fields required by a simulated execution."""

    account_id: int
    asset_code: str
    action: Literal["buy", "sell"]
    quantity: int
    price: float


@dataclass(frozen=True)
class _AccountExecutionInput:
    """Validated fields required by an account position execution."""

    portfolio_id: int
    asset_code: str
    shares: int
    avg_cost: Decimal
    current_price: Decimal


def update_or_create_account_position(
    *,
    portfolio_id: int,
    asset_code: str,
    shares: int | float,
    avg_cost: Decimal,
    current_price: Decimal,
    source: str,
) -> Any:
    """Persist one legacy account position through the owning account repository."""

    position_repo = get_account_position_repository()
    return position_repo.update_or_create_position(
        portfolio_id=portfolio_id,
        asset_code=asset_code,
        shares=shares,
        avg_cost=avg_cost,
        current_price=current_price,
        source=source,
    )


@dataclass
class PrecheckRequest:
    """
    预检查请求

    Attributes:
        candidate_id: 候选 ID
    """

    candidate_id: str


@dataclass
class PrecheckResponse:
    """
    预检查响应

    Attributes:
        success: 是否成功（业务阻断也返回 success=True）
        result: 预检查结果
        error: 系统错误信息
    """

    success: bool
    result: PrecheckResult | None = None
    error: str | None = None


@dataclass
class ExecuteDecisionRequest:
    """
    执行决策请求

    Attributes:
        request_id: 决策请求 ID
        target: 执行目标 (SIMULATED/ACCOUNT)
        # 模拟盘参数
        sim_account_id: 模拟账户 ID
        asset_code: 资产代码
        action: 交易动作 (buy/sell)
        quantity: 数量
        price: 价格
        reason: 原因
        # 实盘账户参数
        portfolio_id: 投资组合 ID
        shares: 持仓股数
        avg_cost: 平均成本
        current_price: 当前价格
    """

    request_id: str
    target: ExecutionTarget
    # 模拟盘参数
    sim_account_id: int | None = None
    asset_code: str | None = None
    action: str | None = None  # "buy" or "sell"
    quantity: int | None = None
    price: float | None = None
    signal_id: int | None = None
    reason: str = ""
    # 实盘账户参数
    portfolio_id: int | None = None
    shares: int | None = None
    avg_cost: float | None = None
    current_price: float | None = None


@dataclass
class ExecuteDecisionResponse:
    """
    执行决策响应

    Attributes:
        success: 是否成功
        result: 执行结果
        error: 错误信息
    """

    success: bool
    result: ExecutionResult | None = None
    error: str | None = None


@dataclass
class CancelDecisionRequest:
    """
    取消决策请求

    Attributes:
        request_id: 决策请求 ID
        reason: 取消原因
    """

    request_id: str
    reason: str = ""


@dataclass
class CancelDecisionResponse:
    """
    取消决策响应

    Attributes:
        success: 是否成功
        request_id: 决策请求 ID
        status: 执行状态
        reason: 取消原因
        error: 错误信息
    """

    success: bool
    request_id: str | None = None
    status: str | None = None
    reason: str = ""
    error: str | None = None


@dataclass
class UpdateQuotaConfigRequest:
    """
    更新配额配置请求

    Attributes:
        account_id: 账户 ID
        period: 配额周期
        max_decisions: 最大决策次数
        max_executions: 最大执行次数
    """

    account_id: str = "default"
    period: QuotaPeriod = QuotaPeriod.WEEKLY
    max_decisions: int = 10
    max_executions: int = 5


@dataclass
class UpdateQuotaConfigResponse:
    """
    更新配额配置响应

    Attributes:
        success: 是否成功
        quota: 更新后的配额
        created: 是否新建
        error: 错误信息
    """

    success: bool
    quota: DecisionQuota | None = None
    created: bool = False
    error: str | None = None


class PrecheckDecisionUseCase:
    """
    预检查决策用例

    在提交决策前进行预检查，验证候选是否可以提交决策。

    检查项：
    1. 候选是否存在
    2. 候选状态是否有效（非过期/证伪/已执行）
    3. Beta Gate 是否通过
    4. 配额是否充足
    5. 冷却期是否就绪

    Attributes:
        candidate_repo: 候选仓储
        quota_repo: 配额仓储
        cooldown_repo: 冷却期仓储
        regime_provider: Regime 提供器
        policy_provider: Policy 提供器
        beta_gate_config_selector: Beta Gate 配置选择器

    Example:
        >>> use_case = PrecheckDecisionUseCase(...)
        >>> response = use_case.execute(PrecheckRequest(candidate_id="cand_xxx"))
    """

    def __init__(
        self,
        candidate_repo: Any,
        quota_repo: Any,
        cooldown_repo: Any,
        regime_provider: Any | None = None,
        policy_provider: Any | None = None,
        beta_gate_config_selector: Any | None = None,
    ) -> None:
        """
        初始化用例

        Args:
            candidate_repo: 候选仓储
            quota_repo: 配额仓储
            cooldown_repo: 冷却期仓储
            regime_provider: Regime 提供器（可选）
            policy_provider: Policy 提供器（可选）
            beta_gate_config_selector: Beta Gate 配置选择器（可选）
        """
        self.candidate_repo = candidate_repo
        self.quota_repo = quota_repo
        self.cooldown_repo = cooldown_repo
        self.regime_provider = regime_provider
        self.policy_provider = policy_provider
        self.beta_gate_config_selector = beta_gate_config_selector

    def execute(self, request: PrecheckRequest) -> PrecheckResponse:
        """
        执行预检查

        Args:
            request: 预检查请求

        Returns:
            预检查响应
        """
        warnings: list[str] = []
        errors: list[str] = []
        details: dict[str, Any] = {}

        try:
            # 1. 检查候选是否存在
            candidate = self.candidate_repo.get_by_id(request.candidate_id)
            if candidate is None:
                return PrecheckResponse(
                    success=True,  # 业务阻断也返回 success=True
                    result=PrecheckResult(
                        candidate_id=request.candidate_id,
                        candidate_valid=False,
                        errors=[f"候选不存在: {request.candidate_id}"],
                    ),
                )

            # 2. 检查候选状态是否有效
            if candidate.is_executed:
                errors.append("候选已执行")
            elif candidate.is_expired:
                errors.append("候选已过期")
            elif str(candidate.status) in ["CANCELLED", "INVALIDATED"]:
                errors.append(f"候选状态无效: {candidate.status}")
            elif candidate.status != CandidateStatus.ACTIONABLE:
                errors.append(f"候选状态不是 ACTIONABLE，当前状态: {candidate.status}")

            # 3. 检查 Beta Gate
            beta_gate_passed = True
            if self.regime_provider and self.policy_provider and self.beta_gate_config_selector:
                try:
                    from apps.beta_gate.domain.services import BetaGateEvaluator

                    current_regime = self.regime_provider.get_current_regime()
                    regime_confidence = self.regime_provider.get_regime_confidence()
                    policy_level = self.policy_provider.get_current_policy_level()

                    config = self.beta_gate_config_selector.get_config_for_regime(current_regime)
                    evaluator = BetaGateEvaluator(config)
                    decision = evaluator.evaluate(
                        asset_code=candidate.asset_code,
                        asset_class=candidate.asset_class,
                        current_regime=current_regime,
                        regime_confidence=regime_confidence,
                        policy_level=policy_level,
                    )
                    beta_gate_passed = decision.is_passed is True
                    details["beta_gate_decision"] = (
                        decision.to_dict() if hasattr(decision, "to_dict") else {}
                    )
                    if not beta_gate_passed:
                        errors.append(f"Beta Gate 未通过: {decision.blocking_reason}")
                except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                    warnings.append(f"Beta Gate 检查失败（跳过）: {e}")

            # 4. 检查配额
            quota_ok = True
            try:
                quota = self.quota_repo.get_quota(QuotaPeriod.WEEKLY)
                if quota and quota.is_quota_exceeded:
                    quota_ok = False
                    errors.append("配额已耗尽")
                details["quota_status"] = quota.to_dict() if quota else {}
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                warnings.append(f"配额检查失败（跳过）: {e}")

            # 5. 检查冷却期
            cooldown_ok = True
            try:
                cooldown = self.cooldown_repo.get_active_cooldown(candidate.asset_code)
                if cooldown and not cooldown.is_decision_ready:
                    cooldown_ok = False
                    errors.append(f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时")
                details["cooldown_status"] = cooldown.to_dict() if cooldown else None
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                warnings.append(f"冷却期检查失败（跳过）: {e}")

            result = PrecheckResult(
                candidate_id=request.candidate_id,
                beta_gate_passed=beta_gate_passed,
                quota_ok=quota_ok,
                cooldown_ok=cooldown_ok,
                candidate_valid=len(errors) == 0 or not any("候选" in e for e in errors),
                warnings=warnings,
                errors=errors,
                details=details,
            )

            return PrecheckResponse(success=True, result=result)

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Precheck failed: {e}", exc_info=True)
            return PrecheckResponse(success=False, error=str(e))


class ExecuteDecisionUseCase:
    """
    执行决策用例

    执行已批准的决策请求。支持模拟盘和实盘账户两种执行路径。

    状态机约束：
    - DecisionRequest: PENDING -> EXECUTED/FAILED
    - AlphaCandidate: ACTIONABLE -> EXECUTED（仅通过此 API）

    Attributes:
        request_repo: 决策请求仓储
        candidate_repo: 候选仓储
        simulated_account_repo: 模拟账户仓储（可选）
        position_repo: 持仓仓储（可选）
        trade_repo: 交易记录仓储（可选）
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = ExecuteDecisionUseCase(...)
        >>> response = use_case.execute(ExecuteDecisionRequest(
        ...     request_id="req_xxx",
        ...     target=ExecutionTarget.SIMULATED,
        ...     sim_account_id=1,
        ...     asset_code="000001.SH",
        ...     action="buy",
        ...     quantity=1000,
        ...     price=12.35,
        ... ))
    """

    def __init__(
        self,
        request_repo: Any,
        candidate_repo: Any,
        simulated_account_repo: Any | None = None,
        position_repo: Any | None = None,
        trade_repo: Any | None = None,
        signal_repo: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        """
        初始化用例

        Args:
            request_repo: 决策请求仓储
            candidate_repo: 候选仓储
            simulated_account_repo: 模拟账户仓储（可选）
            position_repo: 持仓仓储（可选）
            trade_repo: 交易记录仓储（可选）
            signal_repo: 信号查询仓储（可选）
            event_bus: 事件总线（可选）
        """
        self.request_repo = request_repo
        self.candidate_repo = candidate_repo
        self.simulated_account_repo = simulated_account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.signal_repo = signal_repo
        self.event_bus = event_bus

    def execute(self, request: ExecuteDecisionRequest) -> ExecuteDecisionResponse:
        """
        执行决策

        Args:
            request: 执行请求

        Returns:
            执行响应
        """
        try:
            # 1. 获取决策请求
            decision_request = self.request_repo.get_by_id(request.request_id)
            if decision_request is None:
                return ExecuteDecisionResponse(
                    success=False,
                    error=f"决策请求不存在: {request.request_id}",
                )

            # 2. 验证执行状态迁移
            current_status = decision_request.execution_status.value
            if not ExecutionStatusStateMachine.can_transition(current_status, "EXECUTED"):
                return ExecuteDecisionResponse(
                    success=False,
                    error=f"决策请求状态不允许执行: {current_status}",
                )

            # 3. 如果有关联候选，验证候选状态
            candidate: AlphaCandidate | None = None
            if decision_request.candidate_id:
                candidate = self.candidate_repo.get_by_id(decision_request.candidate_id)
                if candidate:
                    # 验证候选状态迁移
                    can_transition, reason = CandidateStatusStateMachine.validate_transition(
                        str(candidate.status), "EXECUTED", via_api=True
                    )
                    if not can_transition:
                        return ExecuteDecisionResponse(
                            success=False,
                            error=f"候选状态不允许执行: {reason}",
                        )

            # 4. 根据执行目标执行
            execution_ref: dict[str, Any]
            if request.target == ExecutionTarget.SIMULATED:
                execution_ref = self._execute_simulated(request, decision_request)
            elif request.target == ExecutionTarget.ACCOUNT:
                execution_ref = self._execute_account(request, decision_request)
            else:
                return ExecuteDecisionResponse(
                    success=False,
                    error=f"不支持的执行目标: {request.target}",
                )

            # 5. 更新决策请求状态
            self.request_repo.update_execution_status(
                request_id=request.request_id,
                execution_status=ExecutionStatus.EXECUTED,
                executed_at=timezone.now(),
                execution_ref=execution_ref,
            )

            # 6. 更新候选状态
            candidate_status = None
            if candidate:
                self.candidate_repo.update_status(
                    candidate_id=candidate.candidate_id,
                    status=CandidateStatus.EXECUTED,
                )
                self.candidate_repo.update_execution_tracking(
                    candidate_id=candidate.candidate_id,
                    decision_request_id=request.request_id,
                    execution_status="EXECUTED",
                )
                candidate_status = "EXECUTED"

            # 7. 发布事件
            self._publish_event(decision_request, candidate, execution_ref)

            result = ExecutionResult(
                request_id=request.request_id,
                execution_status="EXECUTED",
                executed_at=timezone.now(),
                execution_ref=execution_ref,
                candidate_status=candidate_status,
            )

            logger.info(
                f"Decision executed: {request.request_id} "
                f"-> {request.target.value}, ref={execution_ref}"
            )

            return ExecuteDecisionResponse(success=True, result=result)

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Execute decision failed: {e}", exc_info=True)
            # 更新决策请求为失败状态
            try:
                self.request_repo.update_execution_status(
                    request_id=request.request_id,
                    execution_status=ExecutionStatus.FAILED,
                )
            except (DatabaseError, RuntimeError, TypeError, ValueError) as status_error:
                logger.warning(
                    "Failed to mark decision request %s as FAILED after execution error: %s",
                    request.request_id,
                    status_error,
                )
            return ExecuteDecisionResponse(success=False, error=str(e))

    def _execute_simulated(
        self,
        request: ExecuteDecisionRequest,
        decision_request: DecisionRequest,
    ) -> dict[str, Any]:
        """
        执行模拟盘交易

        Args:
            request: 执行请求
            decision_request: 决策请求

        Returns:
            执行引用
        """
        if not self.simulated_account_repo or not self.position_repo or not self.trade_repo:
            raise ValueError("模拟盘仓储未配置")

        execution_input = self._validate_simulated_execution_input(request)

        from apps.simulated_trading.application.use_cases import (
            ExecuteBuyOrderUseCase,
            ExecuteSellOrderUseCase,
        )

        if execution_input.action == "buy":
            signal_id = self._resolve_simulated_buy_signal_id(request, decision_request)
            buy_use_case = ExecuteBuyOrderUseCase(
                account_repo=self.simulated_account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
                signal_repo=self.signal_repo,
            )
            trade = buy_use_case.execute(
                account_id=execution_input.account_id,
                asset_code=execution_input.asset_code,
                asset_name=execution_input.asset_code,  # 简化处理
                asset_type="equity",
                quantity=execution_input.quantity,
                price=execution_input.price,
                reason=request.reason,
                signal_id=signal_id,
            )
        else:
            sell_use_case = ExecuteSellOrderUseCase(
                account_repo=self.simulated_account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
            )
            trade = sell_use_case.execute(
                account_id=execution_input.account_id,
                asset_code=execution_input.asset_code,
                quantity=execution_input.quantity,
                price=execution_input.price,
                reason=request.reason,
            )

        return {
            "trade_id": trade.trade_id,
            "account_id": execution_input.account_id,
            "action": execution_input.action,
            "quantity": execution_input.quantity,
            "price": execution_input.price,
        }

    @staticmethod
    def _validate_simulated_execution_input(
        request: ExecuteDecisionRequest,
    ) -> _SimulatedExecutionInput:
        """Validate and narrow fields required by simulated trading."""

        if request.sim_account_id is None:
            raise ValueError("sim_account_id is required for simulated execution")
        if not request.asset_code:
            raise ValueError("asset_code is required for simulated execution")
        if request.action == "buy":
            action: Literal["buy", "sell"] = "buy"
        elif request.action == "sell":
            action = "sell"
        else:
            raise ValueError("action must be 'buy' or 'sell'")
        if request.quantity is None or request.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if request.price is None or request.price <= 0:
            raise ValueError("price must be greater than zero")
        return _SimulatedExecutionInput(
            account_id=request.sim_account_id,
            asset_code=request.asset_code,
            action=action,
            quantity=request.quantity,
            price=request.price,
        )

    def _resolve_simulated_buy_signal_id(
        self,
        request: ExecuteDecisionRequest,
        decision_request: DecisionRequest,
    ) -> int | None:
        """Resolve the most traceable signal for a simulated buy path."""
        if request.signal_id:
            return request.signal_id

        candidate = None
        if self.candidate_repo and decision_request.candidate_id:
            try:
                candidate = self.candidate_repo.get_by_id(decision_request.candidate_id)
            except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
                candidate = None

        for field_name in ("signal_id", "source_signal_id"):
            value: object = getattr(candidate, field_name, None)
            signal_id = self._coerce_signal_id(value)
            if signal_id is not None:
                return signal_id
            if value not in (None, ""):
                logger.warning("Unsupported candidate signal id: %s", value)

        if not self.signal_repo or not request.asset_code:
            return None

        try:
            summaries = self.signal_repo.get_valid_signal_summaries([request.asset_code])
        except (DatabaseError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("Failed to resolve signal id for %s: %s", request.asset_code, exc)
            return None

        if not summaries:
            return None

        raw_signal_id: object = summaries[0].get("id")
        signal_id = self._coerce_signal_id(raw_signal_id)
        if signal_id is None and raw_signal_id is not None:
            logger.warning("Unsupported signal summary id: %s", raw_signal_id)
        return signal_id

    @staticmethod
    def _coerce_signal_id(value: object) -> int | None:
        """Convert supported signal ID values without accepting arbitrary objects."""

        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _execute_account(
        self,
        request: ExecuteDecisionRequest,
        decision_request: DecisionRequest,
    ) -> dict[str, Any]:
        """
        执行实盘账户操作（记录持仓）

        P2-11: 改用仓储而非直接操作 ORM

        Args:
            request: 执行请求
            decision_request: 决策请求

        Returns:
            执行引用
        """
        execution_input = self._validate_account_execution_input(request)

        position = update_or_create_account_position(
            portfolio_id=execution_input.portfolio_id,
            asset_code=execution_input.asset_code,
            shares=execution_input.shares,
            avg_cost=execution_input.avg_cost,
            current_price=execution_input.current_price,
            source="decision",
        )

        return {
            "position_id": position.id,
            "portfolio_id": execution_input.portfolio_id,
            "asset_code": execution_input.asset_code,
            "shares": execution_input.shares,
            "avg_cost": float(execution_input.avg_cost),
        }

    @staticmethod
    def _validate_account_execution_input(
        request: ExecuteDecisionRequest,
    ) -> _AccountExecutionInput:
        """Validate and narrow fields required by account execution."""

        if request.portfolio_id is None:
            raise ValueError("portfolio_id is required for account execution")
        if not request.asset_code:
            raise ValueError("asset_code is required for account execution")
        if request.shares is None or request.shares <= 0:
            raise ValueError("shares must be greater than zero")
        if request.avg_cost is None or request.avg_cost <= 0:
            raise ValueError("avg_cost must be greater than zero")
        if request.current_price is None or request.current_price <= 0:
            raise ValueError("current_price must be greater than zero")
        return _AccountExecutionInput(
            portfolio_id=request.portfolio_id,
            asset_code=request.asset_code,
            shares=request.shares,
            avg_cost=Decimal(str(request.avg_cost)),
            current_price=Decimal(str(request.current_price)),
        )

    def _publish_event(
        self,
        decision_request: DecisionRequest,
        candidate: AlphaCandidate | None,
        execution_ref: dict[str, Any],
    ) -> None:
        """发布事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,  # P1-5: 使用正确的事件类型
            payload={
                "request_id": decision_request.request_id,
                "candidate_id": decision_request.candidate_id,
                "execution_status": "EXECUTED",
                "execution_ref": execution_ref,
                "asset_code": decision_request.asset_code,
            },
        )

        self.event_bus.publish(event)


class CancelDecisionRequestUseCase:
    """
    取消决策请求用例

    将执行状态从 PENDING/FAILED 迁移到 CANCELLED，并同步候选执行跟踪。
    """

    def __init__(self, request_repo: Any, candidate_repo: Any) -> None:
        self.request_repo = request_repo
        self.candidate_repo = candidate_repo

    def execute(self, request: CancelDecisionRequest) -> CancelDecisionResponse:
        try:
            decision_request = self.request_repo.get_by_id(request.request_id)
            if decision_request is None:
                return CancelDecisionResponse(
                    success=False,
                    error=f"Request not found: {request.request_id}",
                )

            current_status = (
                decision_request.execution_status.value
                if hasattr(decision_request.execution_status, "value")
                else str(decision_request.execution_status)
            )
            if not ExecutionStatusStateMachine.can_transition(
                current_status,
                ExecutionStatus.CANCELLED.value,
            ):
                return CancelDecisionResponse(
                    success=False,
                    error=f"Cannot cancel request with status: {current_status}",
                )

            self.request_repo.update_execution_status(
                request.request_id,
                ExecutionStatus.CANCELLED,
            )

            if decision_request.candidate_id:
                try:
                    self.candidate_repo.update_execution_tracking(
                        decision_request.candidate_id,
                        decision_request_id=request.request_id,
                        execution_status=ExecutionStatus.CANCELLED.value,
                    )
                except (DatabaseError, RuntimeError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Failed to update candidate execution tracking during cancel: %s",
                        exc,
                    )

            return CancelDecisionResponse(
                success=True,
                request_id=request.request_id,
                status=ExecutionStatus.CANCELLED.value,
                reason=request.reason,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as exc:
            logger.error(f"Cancel decision failed: {exc}", exc_info=True)
            return CancelDecisionResponse(success=False, error=str(exc))


class UpdateQuotaConfigUseCase:
    """
    更新配额配置用例

    通过注入的配额仓储更新或创建账户级配额配置。
    """

    def __init__(self, quota_repo: Any) -> None:
        self.quota_repo = quota_repo

    def execute(self, request: UpdateQuotaConfigRequest) -> UpdateQuotaConfigResponse:
        try:
            if request.max_decisions <= 0 or request.max_executions < 0:
                return UpdateQuotaConfigResponse(
                    success=False,
                    error="max_decisions must be > 0 and max_executions must be >= 0",
                )

            existing = self.quota_repo.get_quota(
                request.period,
                account_id=request.account_id,
            )
            now = timezone.now()

            quota = DecisionQuota(
                period=request.period,
                max_decisions=request.max_decisions,
                max_execution_count=request.max_executions,
                used_decisions=existing.used_decisions if existing else 0,
                used_executions=existing.used_executions if existing else 0,
                period_start=existing.period_start if existing else now,
                period_end=existing.period_end if existing else None,
                quota_id=existing.quota_id if existing else f"quota_{uuid4().hex[:12]}",
                account_id=request.account_id,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )

            saved = self.quota_repo.save(quota)
            return UpdateQuotaConfigResponse(
                success=True,
                quota=saved,
                created=existing is None,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as exc:
            logger.error(f"Update quota config failed: {exc}", exc_info=True)
            return UpdateQuotaConfigResponse(success=False, error=str(exc))


__all__ = [
    "PrecheckRequest",
    "PrecheckResponse",
    "ExecuteDecisionRequest",
    "ExecuteDecisionResponse",
    "CancelDecisionRequest",
    "CancelDecisionResponse",
    "UpdateQuotaConfigRequest",
    "UpdateQuotaConfigResponse",
    "PrecheckDecisionUseCase",
    "ExecuteDecisionUseCase",
    "CancelDecisionRequestUseCase",
    "UpdateQuotaConfigUseCase",
]
