"""
Decision Rhythm Application Use Cases

决策频率约束和配额管理的用例编排层。
负责协调配额管理、冷却控制和决策调度。

仅依赖 Domain 层和事件总线，不直接依赖 ORM 或外部 API。
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils import timezone

from apps.alpha_trigger.domain.entities import CandidateStatus
from apps.events.domain.entities import DomainEvent, EventType, create_event
from core.integration.account_positions import update_or_create_account_position

from ..domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    ExecutionStatus,
    ExecutionTarget,
    QuotaPeriod,
    RhythmConfig,
)
from ..domain.services import (
    CandidateStatusStateMachine,
    CooldownCheckResult,
    CooldownManager,
    DecisionScheduler,
    ExecutionResult,
    ExecutionStatusStateMachine,
    PrecheckResult,
    QuotaCheckResult,
    QuotaManager,
    RhythmManager,
)

if TYPE_CHECKING:
    from ..domain.entities import (
        DecisionFeatureSnapshot,
        GatePenalties,
        ModelParamAuditLog,
        ModelParamConfig,
        ModelWeights,
        UnifiedRecommendation,
    )


logger = logging.getLogger(__name__)

RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


# ========== DTOs ==========


@dataclass
class SubmitDecisionRequestRequest:
    """
    提交决策请求

    Attributes:
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向 ("BUY", "SELL")
        priority: 优先级
        trigger_id: 触发器 ID（可选）
        candidate_id: 候选 ID（可选）
        reason: 原因
        expected_confidence: 预期置信度
        quantity: 数量（可选）
        notional: 名义金额（可选）
        quota_period: 使用的配额周期
    """

    asset_code: str
    asset_class: str
    direction: str
    priority: DecisionPriority
    trigger_id: str | None = None
    candidate_id: str | None = None
    reason: str = ""
    expected_confidence: float = 0.0
    quantity: int | None = None
    notional: float | None = None
    quota_period: QuotaPeriod = QuotaPeriod.WEEKLY


@dataclass
class SubmitDecisionRequestResponse:
    """
    提交决策请求响应

    Attributes:
        success: 是否成功
        response: 决策响应
        error: 错误信息
    """

    success: bool
    response: DecisionResponse | None = None
    decision_request: DecisionRequest | None = None
    error: str | None = None


@dataclass
class GetQuotaStatusRequest:
    """
    获取配额状态请求

    Attributes:
        period: 配额周期
    """

    period: QuotaPeriod = QuotaPeriod.WEEKLY


@dataclass
class GetQuotaStatusResponse:
    """
    获取配额状态响应

    Attributes:
        success: 是否成功
        status: 配额状态
        error: 错误信息
    """

    success: bool
    status: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class GetRhythmSummaryRequest:
    """
    获取节奏摘要请求

    空请求，获取所有摘要信息。
    """

    pass


@dataclass
class GetRhythmSummaryResponse:
    """
    获取节奏摘要响应

    Attributes:
        success: 是否成功
        summary: 摘要信息
        error: 错误信息
    """

    success: bool
    summary: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class SubmitBatchRequestRequest:
    """
    批量提交决策请求

    Attributes:
        requests: 决策请求列表
        quota_period: 使用的配额周期
    """

    requests: list[SubmitDecisionRequestRequest]
    quota_period: QuotaPeriod = QuotaPeriod.WEEKLY


@dataclass
class SubmitBatchRequestResponse:
    """
    批量提交决策请求响应

    Attributes:
        success: 是否成功
        responses: 决策响应列表
        summary: 摘要统计
        error: 错误信息
    """

    success: bool
    responses: list[DecisionResponse] = field(default_factory=list)
    decision_requests: list[DecisionRequest] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ResetQuotaRequest:
    """
    重置配额请求

    Attributes:
        period: 配额周期（可选，None 表示重置所有）
    """

    period: QuotaPeriod | None = None


@dataclass
class ResetQuotaResponse:
    """
    重置配额响应

    Attributes:
        success: 是否成功
        message: 消息
        error: 错误信息
    """

    success: bool
    message: str = ""
    error: str | None = None


# ========== Use Cases ==========


class SubmitDecisionRequestUseCase:
    """
    提交决策请求用例

    提交决策请求，检查配额和冷却期，返回批准/拒绝。

    Attributes:
        rhythm_manager: 节奏管理器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = SubmitDecisionRequestUseCase(manager, event_bus)
        >>> response = use_case.execute(SubmitDecisionRequestRequest(
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     direction="BUY",
        ...     priority=DecisionPriority.HIGH,
        ...     reason="强 Alpha 信号"
        ... ))
    """

    def __init__(self, rhythm_manager, event_bus=None):
        """
        初始化用例

        Args:
            rhythm_manager: 节奏管理器
            event_bus: 事件总线（可选）
        """
        self.rhythm_manager = rhythm_manager
        self.event_bus = event_bus

    def execute(self, request: SubmitDecisionRequestRequest) -> SubmitDecisionRequestResponse:
        """
        提交决策请求

        流程：
        1. 创建决策请求
        2. 检查配额
        3. 检查冷却期
        4. 批准/拒绝
        5. 消耗配额
        6. 发布事件

        Args:
            request: 提交请求

        Returns:
            提交响应
        """
        try:
            # 创建决策请求
            from ..domain.entities import create_request

            decision_request = create_request(
                asset_code=request.asset_code,
                asset_class=request.asset_class,
                direction=request.direction,
                priority=request.priority,
                reason=request.reason,
                trigger_id=request.trigger_id,
                candidate_id=request.candidate_id,
                expected_confidence=request.expected_confidence,
                quantity=request.quantity,
                notional=request.notional,
            )

            # 提交到节奏管理器
            response = self.rhythm_manager.submit_request(decision_request, request.quota_period)

            # 发布事件
            self._publish_event(decision_request, response)

            # 记录日志
            self._log_decision(decision_request, response)

            return SubmitDecisionRequestResponse(
                success=True,
                response=response,
                decision_request=decision_request,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to submit decision request: {e}", exc_info=True)
            return SubmitDecisionRequestResponse(
                success=False,
                error=str(e),
            )

    def _publish_event(self, decision_request: DecisionRequest, response: DecisionResponse):
        """发布事件"""
        if self.event_bus is None:
            return

        event_type = (
            EventType.DECISION_APPROVED if response.approved else EventType.DECISION_REJECTED
        )

        event = create_event(
            event_type=event_type,
            payload={
                "request_id": decision_request.request_id,
                "asset_code": decision_request.asset_code,
                "asset_class": decision_request.asset_class,
                "direction": decision_request.direction,
                "priority": decision_request.priority.value,
                "approved": response.approved,
                "reason": response.approval_reason,
                "rejection_reason": response.rejection_reason,
            },
        )

        self.event_bus.publish(event)

    def _log_decision(self, decision_request: DecisionRequest, response: DecisionResponse):
        """记录决策"""
        if response.approved:
            logger.info(
                f"Decision APPROVED: {decision_request.asset_code} {decision_request.direction} "
                f"({decision_request.priority.value})"
            )
        else:
            logger.warning(
                f"Decision REJECTED: {decision_request.asset_code} - {response.rejection_reason}"
            )


class SubmitBatchRequestUseCase:
    """
    批量提交决策请求用例

    批量提交多个决策请求，按优先级排序处理。

    Attributes:
        rhythm_manager: 节奏管理器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = SubmitBatchRequestUseCase(manager, event_bus)
        >>> response = use_case.execute(SubmitBatchRequestRequest(
        ...     requests=[...]
        ... ))
    """

    def __init__(self, rhythm_manager, event_bus=None):
        """
        初始化用例

        Args:
            rhythm_manager: 节奏管理器
            event_bus: 事件总线（可选）
        """
        self.rhythm_manager = rhythm_manager
        self.event_bus = event_bus

    def execute(self, request: SubmitBatchRequestRequest) -> SubmitBatchRequestResponse:
        """
        批量提交决策请求

        Args:
            request: 批量提交请求

        Returns:
            批量提交响应
        """
        try:
            # 转换为 DecisionRequest 列表
            from ..domain.entities import create_request

            decision_requests = []
            for req in request.requests:
                decision_requests.append(
                    create_request(
                        asset_code=req.asset_code,
                        asset_class=req.asset_class,
                        direction=req.direction,
                        priority=req.priority,
                        reason=req.reason,
                        trigger_id=req.trigger_id,
                        expected_confidence=req.expected_confidence,
                        quantity=req.quantity,
                        notional=req.notional,
                    )
                )

            # 批量提交
            responses = self.rhythm_manager.submit_batch(decision_requests, request.quota_period)

            # 统计摘要
            summary = self._calculate_summary(responses)

            # 发布汇总事件
            self._publish_summary_event(responses, summary)

            return SubmitBatchRequestResponse(
                success=True,
                responses=responses,
                decision_requests=decision_requests,
                summary=summary,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to submit batch decision requests: {e}", exc_info=True)
            return SubmitBatchRequestResponse(
                success=False,
                error=str(e),
            )

    def _calculate_summary(self, responses: list[DecisionResponse]) -> dict[str, Any]:
        """计算摘要统计"""
        total = len(responses)
        approved = sum(1 for r in responses if r.approved)
        rejected = total - approved

        # 按优先级统计
        by_priority = {}
        for response in responses:
            # 从 request_id 获取优先级（简化处理）
            pass

        return {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": approved / total if total > 0 else 0,
        }

    def _publish_summary_event(self, responses: list[DecisionResponse], summary: dict[str, Any]):
        """发布汇总事件"""
        if self.event_bus is None:
            return

        event = create_event(
            event_type=EventType.DECISION_REQUESTED,
            payload={
                **summary,
            },
        )

        self.event_bus.publish(event)


class GetQuotaStatusUseCase:
    """
    获取配额状态用例

    获取指定周期的配额使用状态。

    Attributes:
        quota_manager: 配额管理器

    Example:
        >>> use_case = GetQuotaStatusUseCase(manager)
        >>> response = use_case.execute(GetQuotaStatusRequest(QuotaPeriod.WEEKLY))
    """

    def __init__(self, quota_manager):
        """
        初始化用例

        Args:
            quota_manager: 配额管理器
        """
        self.quota_manager = quota_manager

    def execute(self, request: GetQuotaStatusRequest) -> GetQuotaStatusResponse:
        """
        获取配额状态

        Args:
            request: 获取状态请求

        Returns:
            状态响应
        """
        try:
            status = self.quota_manager.get_quota_status(request.period)

            return GetQuotaStatusResponse(
                success=True,
                status=status,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get quota status: {e}", exc_info=True)
            return GetQuotaStatusResponse(
                success=False,
                error=str(e),
            )


class GetRhythmSummaryUseCase:
    """
    获取节奏摘要用例

    获取决策节奏的整体摘要信息。

    Attributes:
        rhythm_manager: 节奏管理器

    Example:
        >>> use_case = GetRhythmSummaryUseCase(manager)
        >>> response = use_case.execute(GetRhythmSummaryRequest())
    """

    def __init__(self, rhythm_manager):
        """
        初始化用例

        Args:
            rhythm_manager: 节奏管理器
        """
        self.rhythm_manager = rhythm_manager

    def execute(self, request: GetRhythmSummaryRequest) -> GetRhythmSummaryResponse:
        """
        获取节奏摘要

        Args:
            request: 摘要请求

        Returns:
            摘要响应
        """
        try:
            summary = self.rhythm_manager.get_summary()

            return GetRhythmSummaryResponse(
                success=True,
                summary=summary,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get rhythm summary: {e}", exc_info=True)
            return GetRhythmSummaryResponse(
                success=False,
                error=str(e),
            )


class ResetQuotaUseCase:
    """
    重置配额用例

    重置指定周期的配额。

    Attributes:
        quota_manager: 配额管理器
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = ResetQuotaUseCase(manager, event_bus)
        >>> response = use_case.execute(ResetQuotaRequest(QuotaPeriod.WEEKLY))
    """

    def __init__(self, quota_manager, event_bus=None):
        """
        初始化用例

        Args:
            quota_manager: 配额管理器
            event_bus: 事件总线（可选）
        """
        self.quota_manager = quota_manager
        self.event_bus = event_bus

    def execute(self, request: ResetQuotaRequest) -> ResetQuotaResponse:
        """
        重置配额

        Args:
            request: 重置请求

        Returns:
            重置响应
        """
        try:
            if request.period is None:
                # 重置所有配额
                self.quota_manager.reset_all_quotas()
                message = "All quotas reset"
            else:
                # 重置指定配额
                self.quota_manager._reset_quota(request.period)
                message = f"{request.period.value} quota reset"

            # 发布事件
            if self.event_bus:
                event = create_event(
                    event_type=EventType.QUOTA_RESET,
                    payload={
                        "period": request.period.value if request.period else "all",
                    },
                )
                self.event_bus.publish(event)

            logger.info(f"Quota reset: {message}")

            return ResetQuotaResponse(
                success=True,
                message=message,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to reset quota: {e}", exc_info=True)
            return ResetQuotaResponse(
                success=False,
                error=str(e),
            )


class GetDecisionQueueUseCase:
    """
    获取决策队列用例

    获取待处理的决策队列状态。

    Attributes:
        scheduler: 决策调度器

    Example:
        >>> use_case = GetDecisionQueueUseCase(scheduler)
        >>> queue_summary = use_case.execute()
    """

    def __init__(self, scheduler):
        """
        初始化用例

        Args:
            scheduler: 决策调度器
        """
        self.scheduler = scheduler

    def execute(self) -> dict[str, Any]:
        """
        获取队列摘要

        Returns:
            队列摘要
        """
        return self.scheduler.get_queue_summary()


# ========== WP-2: 决策编排与新 API ==========


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
        candidate_repo,
        quota_repo,
        cooldown_repo,
        regime_provider=None,
        policy_provider=None,
        beta_gate_config_selector=None,
    ):
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
                    beta_gate_passed = decision.is_passed
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
        request_repo,
        candidate_repo,
        simulated_account_repo=None,
        position_repo=None,
        trade_repo=None,
        signal_repo=None,
        event_bus=None,
    ):
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
            candidate = None
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
            execution_ref = None
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

        from apps.simulated_trading.application.use_cases import (
            ExecuteBuyOrderUseCase,
            ExecuteSellOrderUseCase,
        )

        if request.action == "buy":
            signal_id = self._resolve_simulated_buy_signal_id(request, decision_request)
            use_case = ExecuteBuyOrderUseCase(
                account_repo=self.simulated_account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
                signal_repo=self.signal_repo,
            )
            trade = use_case.execute(
                account_id=request.sim_account_id,
                asset_code=request.asset_code,
                asset_name=request.asset_code,  # 简化处理
                asset_type="equity",
                quantity=request.quantity,
                price=request.price,
                reason=request.reason,
                signal_id=signal_id,
            )
        else:
            use_case = ExecuteSellOrderUseCase(
                account_repo=self.simulated_account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
            )
            trade = use_case.execute(
                account_id=request.sim_account_id,
                asset_code=request.asset_code,
                quantity=request.quantity,
                price=request.price,
                reason=request.reason,
            )

        return {
            "trade_id": trade.trade_id,
            "account_id": request.sim_account_id,
            "action": request.action,
            "quantity": request.quantity,
            "price": request.price,
        }

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
            value = getattr(candidate, field_name, None)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
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

        signal_id = summaries[0].get("id")
        try:
            return int(signal_id) if signal_id is not None else None
        except (TypeError, ValueError):
            logger.warning("Unsupported signal summary id: %s", signal_id)
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
        # P2-11: 使用仓储而非直接操作 ORM
        from decimal import Decimal

        position = update_or_create_account_position(
            portfolio_id=request.portfolio_id,
            asset_code=request.asset_code,
            shares=request.shares,
            avg_cost=Decimal(str(request.avg_cost)),
            current_price=Decimal(str(request.current_price)),
            source="decision",
        )

        return {
            "position_id": position.id,
            "portfolio_id": request.portfolio_id,
            "asset_code": request.asset_code,
            "shares": request.shares,
            "avg_cost": request.avg_cost,
        }

    def _publish_event(
        self,
        decision_request: DecisionRequest,
        candidate,
        execution_ref: dict[str, Any],
    ):
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

    def __init__(self, request_repo, candidate_repo):
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

    def __init__(self, quota_repo):
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


# ========== 估值定价引擎用例 ==========


@dataclass
class CreateValuationSnapshotRequest:
    """
    创建估值快照请求

    Attributes:
        security_code: 证券代码
        valuation_method: 估值方法
        fair_value: 公允价值
        current_price: 当前价格
        input_parameters: 输入参数
        stop_loss_pct: 止损比例（可选）
        target_upside_pct: 目标收益比例（可选）
    """

    security_code: str
    valuation_method: str
    fair_value: float
    current_price: float
    input_parameters: dict[str, Any]
    stop_loss_pct: float | None = None
    target_upside_pct: float | None = None


@dataclass
class CreateValuationSnapshotResponse:
    """
    创建估值快照响应

    Attributes:
        success: 是否成功
        snapshot: 估值快照实体
        error: 错误信息
    """

    success: bool
    snapshot: Any | None = None  # ValuationSnapshot
    error: str | None = None


@dataclass
class GetAggregatedWorkspaceRequest:
    """
    获取聚合工作台请求

    Attributes:
        account_id: 账户 ID（可选，不传则获取全部）
        include_executed: 是否包含已执行的建议
    """

    account_id: str | None = None
    include_executed: bool = False


@dataclass
class GetAggregatedWorkspaceResponse:
    """
    获取聚合工作台响应

    Attributes:
        success: 是否成功
        aggregated_recommendations: 聚合后的建议列表
        regime_context: Regime 上下文
        error: 错误信息
    """

    success: bool
    aggregated_recommendations: list[dict[str, Any]] = field(default_factory=list)
    regime_context: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class PreviewExecutionRequest:
    """
    预览执行请求

    Attributes:
        recommendation_id: 投资建议 ID
        account_id: 账户 ID
        market_price: 当前市场价格
    """

    recommendation_id: str
    account_id: str
    market_price: float


@dataclass
class PreviewExecutionResponse:
    """
    预览执行响应

    Attributes:
        success: 是否成功
        preview: 执行预览详情
        risk_checks: 风控检查结果
        error: 错误信息
    """

    success: bool
    preview: dict[str, Any] | None = None
    risk_checks: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ApproveExecutionRequest:
    """
    批准执行请求

    Attributes:
        approval_request_id: 执行审批请求 ID
        reviewer_comments: 审批评论
        market_price: 当前市场价格
    """

    approval_request_id: str
    reviewer_comments: str
    market_price: float | None = None


@dataclass
class ApproveExecutionResponse:
    """
    批准执行响应

    Attributes:
        success: 是否成功
        approval_request: 更新后的执行审批请求
        error: 错误信息
    """

    success: bool
    approval_request: Any | None = None  # ExecutionApprovalRequest
    error: str | None = None


@dataclass
class RejectExecutionRequest:
    """
    拒绝执行请求

    Attributes:
        approval_request_id: 执行审批请求 ID
        reviewer_comments: 拒绝原因
    """

    approval_request_id: str
    reviewer_comments: str


@dataclass
class RejectExecutionResponse:
    """
    拒绝执行响应

    Attributes:
        success: 是否成功
        approval_request: 更新后的执行审批请求
        error: 错误信息
    """

    success: bool
    approval_request: Any | None = None  # ExecutionApprovalRequest
    error: str | None = None


class CreateValuationSnapshotUseCase:
    """
    创建估值快照用例

    为指定证券创建估值快照。

    Attributes:
        valuation_snapshot_repo: 估值快照仓储
        valuation_service: 估值快照服务

    Example:
        >>> use_case = CreateValuationSnapshotUseCase(repo, service)
        >>> response = use_case.execute(CreateValuationSnapshotRequest(
        ...     security_code="000001.SH",
        ...     valuation_method="COMPOSITE",
        ...     fair_value=12.50,
        ...     current_price=10.80,
        ...     input_parameters={"pe_percentile": 0.15},
        ... ))
    """

    def __init__(self, valuation_snapshot_repo, valuation_service=None):
        """
        初始化用例

        Args:
            valuation_snapshot_repo: 估值快照仓储
            valuation_service: 估值快照服务（可选）
        """
        self.valuation_snapshot_repo = valuation_snapshot_repo
        self.valuation_service = valuation_service

    def execute(self, request: CreateValuationSnapshotRequest) -> CreateValuationSnapshotResponse:
        """
        执行创建估值快照

        Args:
            request: 创建请求

        Returns:
            创建响应
        """
        try:
            from decimal import Decimal

            from ..domain.entities import create_valuation_snapshot

            # 创建估值快照
            snapshot = create_valuation_snapshot(
                security_code=request.security_code,
                valuation_method=request.valuation_method,
                fair_value=Decimal(str(request.fair_value)),
                entry_price_low=Decimal(str(request.fair_value * 0.95)),
                entry_price_high=Decimal(str(request.fair_value * 1.05)),
                target_price_low=Decimal(str(request.fair_value * 1.15)),
                target_price_high=Decimal(str(request.fair_value * 1.25)),
                stop_loss_price=Decimal(str(request.current_price * 0.90)),
                input_parameters=request.input_parameters,
            )

            # 保存到仓储
            self.valuation_snapshot_repo.save(snapshot)

            logger.info(
                f"Valuation snapshot created: {snapshot.snapshot_id} for {request.security_code}"
            )

            return CreateValuationSnapshotResponse(
                success=True,
                snapshot=snapshot,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to create valuation snapshot: {e}", exc_info=True)
            return CreateValuationSnapshotResponse(
                success=False,
                error=str(e),
            )


class GetAggregatedWorkspaceUseCase:
    """
    获取聚合工作台用例

    获取按账户+证券+方向聚合后的投资建议列表。

    Attributes:
        recommendation_repo: 投资建议仓储
        consolidation_service: 建议聚合服务
        regime_provider: Regime 提供器

    Example:
        >>> use_case = GetAggregatedWorkspaceUseCase(repo, service, regime_provider)
        >>> response = use_case.execute(GetAggregatedWorkspaceRequest(account_id="account_1"))
    """

    def __init__(
        self,
        recommendation_repo,
        consolidation_service=None,
        regime_provider=None,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 投资建议仓储
            consolidation_service: 建议聚合服务（可选）
            regime_provider: Regime 提供器（可选）
        """
        self.recommendation_repo = recommendation_repo
        self.consolidation_service = consolidation_service
        self.regime_provider = regime_provider

    def execute(self, request: GetAggregatedWorkspaceRequest) -> GetAggregatedWorkspaceResponse:
        """
        执行获取聚合工作台

        Args:
            request: 获取请求

        Returns:
            聚合工作台响应
        """
        try:
            from ..domain.services import RecommendationConsolidationService

            # 获取活跃建议
            if request.account_id:
                recommendations = self.recommendation_repo.get_active_by_account(
                    account_id=request.account_id,
                    include_executed=request.include_executed,
                )
            else:
                recommendations = self.recommendation_repo.get_all_active(
                    include_executed=request.include_executed,
                )

            # 聚合建议
            if self.consolidation_service:
                consolidation_service = self.consolidation_service
            else:
                consolidation_service = RecommendationConsolidationService()

            # 按账户分组聚合
            account_groups: dict[str, list[Any]] = {}
            for rec in recommendations:
                # 从 recommendation 中提取账户信息
                # 这里简化处理，实际应该从关联关系获取
                account_id = getattr(rec, "account_id", "default")
                if account_id not in account_groups:
                    account_groups[account_id] = []
                account_groups[account_id].append(rec)

            aggregated = []
            for account_id, recs in account_groups.items():
                consolidated_recs = consolidation_service.consolidate(recs, account_id)
                for rec in consolidated_recs:
                    aggregated.append(self._format_recommendation(rec, account_id))

            # 获取 Regime 上下文
            regime_context = None
            if self.regime_provider:
                try:
                    regime_context = {
                        "current_regime": self.regime_provider.get_current_regime(),
                        "confidence": self.regime_provider.get_regime_confidence(),
                        "source": getattr(self.regime_provider, "source", "UNKNOWN"),
                    }
                except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                    logger.warning(f"Failed to get regime context: {e}")

            return GetAggregatedWorkspaceResponse(
                success=True,
                aggregated_recommendations=aggregated,
                regime_context=regime_context,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get aggregated workspace: {e}", exc_info=True)
            return GetAggregatedWorkspaceResponse(
                success=False,
                error=str(e),
            )

    def _format_recommendation(self, rec, account_id: str) -> dict[str, Any]:
        """格式化建议为 API 响应格式"""
        return {
            "aggregation_key": f"{account_id}:{rec.security_code}:{rec.side}",
            "security_code": rec.security_code,
            "security_name": getattr(rec, "security_name", rec.security_code),
            "side": rec.side,
            "confidence": rec.confidence,
            "valuation_snapshot_id": rec.valuation_snapshot_id,
            "price_range": {
                "entry_low": float(rec.entry_price_low),
                "entry_high": float(rec.entry_price_high),
                "target_low": float(rec.target_price_low),
                "target_high": float(rec.target_price_high),
                "stop_loss": float(rec.stop_loss_price),
            },
            "position_suggestion": {
                "suggested_pct": rec.position_size_pct,
                "suggested_quantity": rec.suggested_quantity,
                "max_capital": float(rec.max_capital),
            },
            "risk_checks": {},  # 将在 PreviewExecution 中填充
            "source_recommendation_ids": rec.source_recommendation_ids,
            "reason_codes": rec.reason_codes,
            "human_readable_rationale": rec.human_readable_rationale,
            "regime_source": getattr(rec, "regime_source", "UNKNOWN"),
        }


class PreviewExecutionUseCase:
    """
    预览执行用例

    在审批前预览执行详情，包括风控检查。

    Attributes:
        recommendation_repo: 投资建议仓储
        approval_repo: 执行审批仓储
        quota_repo: 配额仓储
        cooldown_repo: 冷却期仓储
        regime_provider: Regime 提供器

    Example:
        >>> use_case = PreviewExecutionUseCase(...)
        >>> response = use_case.execute(PreviewExecutionRequest(
        ...     recommendation_id="rec_001",
        ...     account_id="account_1",
        ...     market_price=10.80,
        ... ))
    """

    def __init__(
        self,
        recommendation_repo,
        approval_repo,
        quota_repo=None,
        cooldown_repo=None,
        regime_provider=None,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 投资建议仓储
            approval_repo: 执行审批仓储
            quota_repo: 配额仓储（可选）
            cooldown_repo: 冷却期仓储（可选）
            regime_provider: Regime 提供器（可选）
        """
        self.recommendation_repo = recommendation_repo
        self.approval_repo = approval_repo
        self.quota_repo = quota_repo
        self.cooldown_repo = cooldown_repo
        self.regime_provider = regime_provider

    def execute(self, request: PreviewExecutionRequest) -> PreviewExecutionResponse:
        """
        执行预览

        Args:
            request: 预览请求

        Returns:
            预览响应
        """
        try:
            from decimal import Decimal

            from ..domain.entities import ApprovalStatus, create_execution_approval_request

            # 获取投资建议
            recommendation = self.recommendation_repo.get_by_id(request.recommendation_id)
            if recommendation is None:
                return PreviewExecutionResponse(
                    success=False,
                    error=f"投资建议不存在: {request.recommendation_id}",
                )

            # 执行风控检查
            risk_checks = self._run_risk_checks(
                recommendation=recommendation,
                market_price=Decimal(str(request.market_price)),
            )

            # 获取 Regime 来源
            regime_source = "UNKNOWN"
            if self.regime_provider:
                try:
                    regime_source = getattr(self.regime_provider, "source", "V2_CALCULATION")
                except (AttributeError, RuntimeError, TypeError):
                    regime_source = "UNKNOWN"

            # 创建预览审批请求（DRAFT 状态）
            approval_request = create_execution_approval_request(
                recommendation=recommendation,
                account_id=request.account_id,
                risk_check_results=risk_checks,
                regime_source=regime_source,
                market_price_at_review=Decimal(str(request.market_price)),
            )

            # 构建预览详情
            preview = {
                "recommendation_id": recommendation.recommendation_id,
                "security_code": recommendation.security_code,
                "side": recommendation.side,
                "confidence": recommendation.confidence,
                "suggested_quantity": approval_request.suggested_quantity,
                "market_price": request.market_price,
                "price_range": {
                    "entry_low": float(recommendation.entry_price_low),
                    "entry_high": float(recommendation.entry_price_high),
                    "target_low": float(recommendation.target_price_low),
                    "target_high": float(recommendation.target_price_high),
                    "stop_loss": float(recommendation.stop_loss_price),
                },
                "position_suggestion": {
                    "suggested_pct": recommendation.position_size_pct,
                    "suggested_quantity": recommendation.suggested_quantity,
                    "max_capital": float(recommendation.max_capital),
                },
                "regime_source": regime_source,
            }

            return PreviewExecutionResponse(
                success=True,
                preview=preview,
                risk_checks=risk_checks,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to preview execution: {e}", exc_info=True)
            return PreviewExecutionResponse(
                success=False,
                error=str(e),
            )

    def _run_risk_checks(
        self,
        recommendation,
        market_price,
    ) -> dict[str, Any]:
        """执行风控检查"""
        risk_checks = {}

        # 1. 价格验证
        if recommendation.is_buy:
            price_valid = market_price <= recommendation.entry_price_high
            risk_checks["price_validation"] = {
                "passed": price_valid,
                "reason": (
                    ""
                    if price_valid
                    else f"市场价格 {market_price} 高于入场上限 {recommendation.entry_price_high}"
                ),
            }
        else:
            price_valid = True  # SELL 不限制价格
            risk_checks["price_validation"] = {
                "passed": True,
                "reason": "",
            }

        # 2. 配额检查
        if self.quota_repo:
            try:
                from ..domain.entities import QuotaPeriod

                quota = self.quota_repo.get_quota(QuotaPeriod.WEEKLY)
                quota_ok = quota and not quota.is_quota_exceeded
                risk_checks["quota"] = {
                    "passed": quota_ok,
                    "remaining": quota.remaining_decisions if quota else 0,
                    "reason": "" if quota_ok else "配额已耗尽",
                }
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                risk_checks["quota"] = {"passed": True, "reason": f"检查失败（跳过）: {e}"}
        else:
            risk_checks["quota"] = {"passed": True, "reason": "未配置"}

        # 3. 冷却期检查
        if self.cooldown_repo:
            try:
                cooldown = self.cooldown_repo.get_active_cooldown(recommendation.security_code)
                cooldown_ok = not cooldown or cooldown.is_decision_ready
                risk_checks["cooldown"] = {
                    "passed": cooldown_ok,
                    "hours_remaining": cooldown.decision_ready_in_hours if cooldown else 0,
                    "reason": (
                        ""
                        if cooldown_ok
                        else f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时"
                    ),
                }
            except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
                risk_checks["cooldown"] = {"passed": True, "reason": f"检查失败（跳过）: {e}"}
        else:
            risk_checks["cooldown"] = {"passed": True, "reason": "未配置"}

        return risk_checks


class ApproveExecutionUseCase:
    """
    批准执行用例

    批准执行审批请求。

    Attributes:
        approval_repo: 执行审批仓储
        approval_service: 执行审批服务
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = ApproveExecutionUseCase(repo, service)
        >>> response = use_case.execute(ApproveExecutionRequest(
        ...     approval_request_id="apr_001",
        ...     reviewer_comments="审批通过",
        ...     market_price=10.80,
        ... ))
    """

    def __init__(self, approval_repo, approval_service=None, event_bus=None):
        """
        初始化用例

        Args:
            approval_repo: 执行审批仓储
            approval_service: 执行审批服务（可选）
            event_bus: 事件总线（可选）
        """
        self.approval_repo = approval_repo
        self.approval_service = approval_service
        self.event_bus = event_bus

    def execute(self, request: ApproveExecutionRequest) -> ApproveExecutionResponse:
        """
        执行批准

        Args:
            request: 批准请求

        Returns:
            批准响应
        """
        try:
            from decimal import Decimal

            from ..domain.services import ExecutionApprovalService

            # 获取审批请求
            approval_request = self.approval_repo.get_by_id(request.approval_request_id)
            if approval_request is None:
                return ApproveExecutionResponse(
                    success=False,
                    error=f"审批请求不存在: {request.approval_request_id}",
                )

            # 获取或创建审批服务
            if self.approval_service:
                approval_service = self.approval_service
            else:
                approval_service = ExecutionApprovalService()

            # 市场价格
            market_price = Decimal(str(request.market_price)) if request.market_price else None

            # 检查是否可以批准
            if market_price:
                can_approve, reason = approval_service.can_approve(approval_request, market_price)
                if not can_approve:
                    return ApproveExecutionResponse(
                        success=False,
                        error=f"无法批准: {reason}",
                    )

            # 执行批准
            updated_request = approval_service.approve(
                approval_request=approval_request,
                reviewer_comments=request.reviewer_comments,
                market_price=market_price,
            )

            # 保存更新
            self.approval_repo.save(updated_request)

            # 发布事件
            if self.event_bus:
                event = create_event(
                    event_type=EventType.DECISION_APPROVED,
                    payload={
                        "approval_request_id": updated_request.request_id,
                        "recommendation_id": updated_request.recommendation_id,
                        "security_code": updated_request.security_code,
                        "side": updated_request.side,
                        "reviewer_comments": request.reviewer_comments,
                    },
                )
                self.event_bus.publish(event)

            logger.info(f"Execution approved: {updated_request.request_id}")

            return ApproveExecutionResponse(
                success=True,
                approval_request=updated_request,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to approve execution: {e}", exc_info=True)
            return ApproveExecutionResponse(
                success=False,
                error=str(e),
            )


class RejectExecutionUseCase:
    """
    拒绝执行用例

    拒绝执行审批请求。

    Attributes:
        approval_repo: 执行审批仓储
        approval_service: 执行审批服务
        event_bus: 事件总线（可选）

    Example:
        >>> use_case = RejectExecutionUseCase(repo, service)
        >>> response = use_case.execute(RejectExecutionRequest(
        ...     approval_request_id="apr_001",
        ...     reviewer_comments="风险过高",
        ... ))
    """

    def __init__(self, approval_repo, approval_service=None, event_bus=None):
        """
        初始化用例

        Args:
            approval_repo: 执行审批仓储
            approval_service: 执行审批服务（可选）
            event_bus: 事件总线（可选）
        """
        self.approval_repo = approval_repo
        self.approval_service = approval_service
        self.event_bus = event_bus

    def execute(self, request: RejectExecutionRequest) -> RejectExecutionResponse:
        """
        执行拒绝

        Args:
            request: 拒绝请求

        Returns:
            拒绝响应
        """
        try:
            from ..domain.services import ExecutionApprovalService

            # 获取审批请求
            approval_request = self.approval_repo.get_by_id(request.approval_request_id)
            if approval_request is None:
                return RejectExecutionResponse(
                    success=False,
                    error=f"审批请求不存在: {request.approval_request_id}",
                )

            # 获取或创建审批服务
            if self.approval_service:
                approval_service = self.approval_service
            else:
                approval_service = ExecutionApprovalService()

            # 执行拒绝
            updated_request = approval_service.reject(
                approval_request=approval_request,
                reviewer_comments=request.reviewer_comments,
            )

            # 保存更新
            self.approval_repo.save(updated_request)

            # 发布事件
            if self.event_bus:
                event = create_event(
                    event_type=EventType.DECISION_REJECTED,
                    payload={
                        "approval_request_id": updated_request.request_id,
                        "recommendation_id": updated_request.recommendation_id,
                        "security_code": updated_request.security_code,
                        "side": updated_request.side,
                        "rejection_reason": request.reviewer_comments,
                    },
                )
                self.event_bus.publish(event)

            logger.info(f"Execution rejected: {updated_request.request_id}")

            return RejectExecutionResponse(
                success=True,
                approval_request=updated_request,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to reject execution: {e}", exc_info=True)
            return RejectExecutionResponse(
                success=False,
                error=str(e),
            )


# ============================================================================
# 统一推荐参数管理用例（Top-down + Bottom-up 融合）
# ============================================================================


class ModelParamConfigRepositoryProtocol(Protocol):
    """模型参数配置仓储协议"""

    def get_param(
        self,
        param_key: str,
        env: str,
    ) -> Optional["ModelParamConfig"]:
        """获取参数配置"""
        ...

    def get_all_params(self, env: str) -> list["ModelParamConfig"]:
        """获取所有参数配置"""
        ...

    def save_param(
        self,
        config: "ModelParamConfig",
    ) -> "ModelParamConfig":
        """保存参数配置"""
        ...

    def create_audit_log(
        self,
        log: "ModelParamAuditLog",
    ) -> "ModelParamAuditLog":
        """创建审计日志"""
        ...


class GetModelParamsUseCase:
    """
    获取模型参数用例

    实现参数读取的完整回退链：
    1. 数据库配置表
    2. 内置默认值（兜底）
    """

    def __init__(
        self,
        param_repo: ModelParamConfigRepositoryProtocol,
        default_env: str = "dev",
    ):
        """
        初始化用例

        Args:
            param_repo: 参数配置仓储
            default_env: 默认环境
        """
        self.param_repo = param_repo
        self.default_env = default_env

    def execute(
        self,
        env: str | None = None,
    ) -> dict[str, Any]:
        """
        获取所有模型参数

        Args:
            env: 环境（可选，默认使用 default_env）

        Returns:
            参数字典
        """
        from ..domain.services import DEFAULT_MODEL_PARAMS

        target_env = env or self.default_env

        # 从数据库获取参数
        db_params = self.param_repo.get_all_params(target_env)

        # 构建参数字典
        params = dict(DEFAULT_MODEL_PARAMS)  # 从默认值开始

        # 用数据库配置覆盖
        for config in db_params:
            if config.is_active:
                typed_value = config.get_typed_value()
                params[config.param_key] = typed_value

        return params

    def get_param(
        self,
        param_key: str,
        env: str | None = None,
    ) -> Any:
        """
        获取单个参数

        Args:
            param_key: 参数键
            env: 环境（可选）

        Returns:
            参数值
        """
        from ..domain.services import DEFAULT_MODEL_PARAMS

        target_env = env or self.default_env

        # 尝试从数据库获取
        config = self.param_repo.get_param(param_key, target_env)

        if config and config.is_active:
            return config.get_typed_value()

        # 回退到默认值
        if param_key in DEFAULT_MODEL_PARAMS:
            return DEFAULT_MODEL_PARAMS[param_key]

        raise ValueError(f"Unknown parameter: {param_key}")

    def get_model_weights(
        self,
        env: str | None = None,
    ) -> "ModelWeights":
        """
        获取模型权重配置

        Args:
            env: 环境（可选）

        Returns:
            ModelWeights 实例
        """
        from ..domain.services import ModelWeights

        params = self.execute(env)

        return ModelWeights(
            alpha_model_weight=params.get("alpha_model_weight", 0.40),
            sentiment_weight=params.get("sentiment_weight", 0.15),
            flow_weight=params.get("flow_weight", 0.15),
            technical_weight=params.get("technical_weight", 0.15),
            fundamental_weight=params.get("fundamental_weight", 0.15),
        )

    def get_gate_penalties(
        self,
        env: str | None = None,
    ) -> "GatePenalties":
        """
        获取 Gate 惩罚参数

        Args:
            env: 环境（可选）

        Returns:
            GatePenalties 实例
        """
        from ..domain.services import GatePenalties

        params = self.execute(env)

        return GatePenalties(
            cooldown_penalty=params.get("gate_penalty_cooldown", 0.10),
            quota_penalty=params.get("gate_penalty_quota", 0.10),
            volatility_penalty=params.get("gate_penalty_volatility", 0.10),
        )


@dataclass
class UpdateModelParamRequest:
    """更新模型参数请求"""

    param_key: str
    param_value: str
    param_type: str = "float"
    env: str = "dev"
    updated_by: str = ""
    updated_reason: str = ""


@dataclass
class UpdateModelParamResponse:
    """更新模型参数响应"""

    success: bool
    config: Optional["ModelParamConfig"] = None
    error: str = ""


class UpdateModelParamUseCase:
    """
    更新模型参数用例

    实现参数更新并记录审计日志。
    """

    def __init__(
        self,
        param_repo: ModelParamConfigRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            param_repo: 参数配置仓储
        """
        self.param_repo = param_repo

    def execute(
        self,
        request: UpdateModelParamRequest,
    ) -> UpdateModelParamResponse:
        """
        执行参数更新

        Args:
            request: 更新请求

        Returns:
            更新响应
        """
        from uuid import uuid4

        from ..domain.entities import ModelParamAuditLog, ModelParamConfig

        try:
            # 获取旧值
            old_config = self.param_repo.get_param(request.param_key, request.env)
            old_value = old_config.param_value if old_config else ""

            # 创建或更新配置
            if old_config:
                config = ModelParamConfig(
                    config_id=f"mpc_{uuid4().hex[:12]}",
                    param_key=request.param_key,
                    param_value=request.param_value,
                    param_type=request.param_type,
                    env=request.env,
                    version=old_config.version + 1,
                    is_active=True,
                    description=old_config.description,
                    updated_by=request.updated_by,
                    updated_reason=request.updated_reason,
                    created_at=old_config.created_at,
                    updated_at=timezone.now(),
                )
            else:
                config = ModelParamConfig(
                    config_id=f"mpc_{uuid4().hex[:12]}",
                    param_key=request.param_key,
                    param_value=request.param_value,
                    param_type=request.param_type,
                    env=request.env,
                    version=1,
                    is_active=True,
                    description="",
                    updated_by=request.updated_by,
                    updated_reason=request.updated_reason,
                )

            # 保存配置
            saved_config = self.param_repo.save_param(config)

            # 创建审计日志
            audit_log = ModelParamAuditLog(
                log_id=f"mpal_{uuid4().hex[:12]}",
                param_key=request.param_key,
                old_value=old_value,
                new_value=request.param_value,
                env=request.env,
                changed_by=request.updated_by,
                change_reason=request.updated_reason,
            )
            self.param_repo.create_audit_log(audit_log)

            logger.info(
                f"Model param updated: {request.param_key} = {request.param_value} "
                f"(env={request.env}, by={request.updated_by})"
            )

            return UpdateModelParamResponse(
                success=True,
                config=saved_config,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to update model param: {e}", exc_info=True)
            return UpdateModelParamResponse(
                success=False,
                error=str(e),
            )


# ============================================================================
# 统一推荐聚合服务用例（Top-down + Bottom-up 融合）
# ============================================================================


class FeatureDataProviderProtocol(Protocol):
    """特征数据提供者协议"""

    def get_regime(self) -> dict[str, Any] | None:
        """获取当前 Regime 状态"""
        ...

    def get_policy_level(self) -> str | None:
        """获取当前政策档位"""
        ...

    def check_beta_gate(self, security_code: str) -> bool:
        """检查 Beta Gate 是否通过"""
        ...

    def get_sentiment_score(self, security_code: str) -> float:
        """获取舆情分数"""
        ...

    def get_flow_score(self, security_code: str) -> float:
        """获取资金流向分数"""
        ...

    def get_technical_score(self, security_code: str) -> float:
        """获取技术面分数"""
        ...

    def get_fundamental_score(self, security_code: str) -> float:
        """获取基本面分数"""
        ...

    def get_alpha_model_score(self, security_code: str) -> float:
        """获取 Alpha 模型分数"""
        ...


class ValuationProviderProtocol(Protocol):
    """估值数据提供者协议"""

    def get_valuation(
        self,
        security_code: str,
    ) -> dict[str, Any] | None:
        """获取估值数据"""
        ...


class SignalProviderProtocol(Protocol):
    """信号数据提供者协议"""

    def get_active_signals(
        self,
        security_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取活跃信号"""
        ...


class CandidateProviderProtocol(Protocol):
    """候选数据提供者协议"""

    def get_active_candidates(
        self,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取活跃候选"""
        ...


class PositionSnapshotProviderProtocol(Protocol):
    """持仓快照提供者协议。"""

    def get_position_snapshots(self, account_id: str) -> list[dict[str, Any]]:
        """获取账户当前持仓快照。"""
        ...


class UnifiedRecommendationRepositoryProtocol(Protocol):
    """统一推荐仓储协议"""

    def save(self, recommendation: "UnifiedRecommendation") -> "UnifiedRecommendation":
        """保存推荐"""
        ...

    def save_feature_snapshot(
        self, snapshot: "DecisionFeatureSnapshot"
    ) -> "DecisionFeatureSnapshot":
        """保存特征快照"""
        ...

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list["UnifiedRecommendation"]:
        """按账户获取推荐"""
        ...

    def get_conflicts(self, account_id: str) -> list["UnifiedRecommendation"]:
        """获取冲突推荐"""
        ...

    def mark_as_conflict(self, recommendation_id: str) -> None:
        """标记为冲突"""
        ...


@dataclass
class GenerateRecommendationsRequest:
    """生成推荐请求"""

    account_id: str
    security_codes: list[str] | None = None
    force_refresh: bool = False


@dataclass
class GenerateRecommendationsResponse:
    """生成推荐响应"""

    success: bool
    recommendations: list["UnifiedRecommendation"] = field(default_factory=list)
    conflicts: list["UnifiedRecommendation"] = field(default_factory=list)
    error: str = ""


class GenerateUnifiedRecommendationsUseCase:
    """
    生成统一推荐用例

    协调 Top-down 和 Bottom-up 数据汇聚，生成统一推荐。

    流程:
        1. 数据汇聚: 拉取 Regime、Policy、Beta Gate、舆情、价格交易、财务、Alpha 分数
        2. 推荐生成: 生成统一推荐对象 UnifiedRecommendation
        3. 后端聚合: 按 account_id + security_code + side 去重
        4. 冲突处理: 同账户同证券同时 BUY/SELL 进入冲突队列
    """

    def __init__(
        self,
        feature_provider: FeatureDataProviderProtocol,
        valuation_provider: ValuationProviderProtocol,
        signal_provider: SignalProviderProtocol,
        candidate_provider: CandidateProviderProtocol,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
        param_use_case: GetModelParamsUseCase,
        position_snapshot_provider: PositionSnapshotProviderProtocol | None = None,
    ):
        """
        初始化用例

        Args:
            feature_provider: 特征数据提供者
            valuation_provider: 估值数据提供者
            signal_provider: 信号数据提供者
            candidate_provider: 候选数据提供者
            recommendation_repo: 推荐仓储
            param_use_case: 参数获取用例
            position_snapshot_provider: 持仓快照提供者（可选）
        """
        self.feature_provider = feature_provider
        self.valuation_provider = valuation_provider
        self.signal_provider = signal_provider
        self.candidate_provider = candidate_provider
        self.recommendation_repo = recommendation_repo
        self.param_use_case = param_use_case
        self.position_snapshot_provider = position_snapshot_provider

    def execute(
        self,
        request: GenerateRecommendationsRequest,
    ) -> GenerateRecommendationsResponse:
        """
        执行推荐生成

        Args:
            request: 生成请求

        Returns:
            生成响应
        """
        from uuid import uuid4

        from ..domain.entities import (
            DecisionFeatureSnapshot,
            RecommendationStatus,
            UnifiedRecommendation,
        )
        from ..domain.services import (
            CompositeScoreCalculator,
            RecommendationAggregator,
        )

        def _to_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        try:
            # 获取模型参数
            params: dict[str, Any] = {}
            if hasattr(self.param_use_case, "execute"):
                raw_params = self.param_use_case.execute()
                if isinstance(raw_params, dict):
                    params = raw_params
            weights = self.param_use_case.get_model_weights()
            penalties = self.param_use_case.get_gate_penalties()
            calculator = CompositeScoreCalculator(weights, penalties)
            aggregator = RecommendationAggregator()
            buy_score_threshold = _to_float(params.get("buy_score_threshold", 0.65), 0.65)
            buy_alpha_threshold = _to_float(params.get("buy_alpha_threshold", 0.60), 0.60)
            sell_score_threshold = _to_float(params.get("sell_score_threshold", 0.35), 0.35)
            sell_alpha_threshold = _to_float(params.get("sell_alpha_threshold", 0.30), 0.30)
            default_position_pct = _to_float(params.get("default_position_pct", 5.0), 5.0)
            max_capital_per_trade_raw = _to_float(
                params.get("max_capital_per_trade", 50000.0), 50000.0
            )
            max_capital_per_trade = Decimal(str(max_capital_per_trade_raw))

            # 1. 数据汇聚
            regime_data = self.feature_provider.get_regime()
            policy_level = self.feature_provider.get_policy_level()

            # 获取证券列表
            security_codes = request.security_codes
            if not security_codes:
                candidates = self.candidate_provider.get_active_candidates(request.account_id)
                candidate_codes = {
                    str(code).strip()
                    for code in (c.get("security_code") for c in candidates)
                    if str(code or "").strip()
                }
                held_codes: set[str] = set()
                if self.position_snapshot_provider is not None:
                    position_snapshots = self.position_snapshot_provider.get_position_snapshots(
                        request.account_id
                    )
                    held_codes = {
                        str(code).strip()
                        for code in (p.get("asset_code") for p in position_snapshots)
                        if str(code or "").strip()
                    }
                security_codes = list(candidate_codes | held_codes)

            # 2. 生成推荐
            raw_recommendations: list[UnifiedRecommendation] = []

            for security_code in security_codes:
                # 检查 Beta Gate
                beta_gate_passed = self.feature_provider.check_beta_gate(security_code)

                # 收集特征
                snapshot = DecisionFeatureSnapshot(
                    snapshot_id=f"fsn_{uuid4().hex[:12]}",
                    security_code=security_code,
                    snapshot_time=timezone.now(),
                    regime=regime_data.get("regime", "") if regime_data else "",
                    regime_confidence=regime_data.get("confidence", 0.0) if regime_data else 0.0,
                    policy_level=policy_level or "",
                    beta_gate_passed=beta_gate_passed,
                    sentiment_score=self.feature_provider.get_sentiment_score(security_code),
                    flow_score=self.feature_provider.get_flow_score(security_code),
                    technical_score=self.feature_provider.get_technical_score(security_code),
                    fundamental_score=self.feature_provider.get_fundamental_score(security_code),
                    alpha_model_score=self.feature_provider.get_alpha_model_score(security_code),
                )

                # 保存特征快照
                self.recommendation_repo.save_feature_snapshot(snapshot)

                # 计算综合分
                composite_score, penalty_reasons = calculator.calculate_from_snapshot(snapshot)

                # 获取估值数据
                valuation = self.valuation_provider.get_valuation(security_code)
                valuation_reason_codes = []
                if valuation and valuation.get("valuation_source") == "current_price_fallback":
                    valuation_reason_codes.append("valuation_current_price_fallback")

                # 确定方向（基于综合分）
                side = self._determine_side(
                    composite_score,
                    snapshot.alpha_model_score,
                    buy_score_threshold=buy_score_threshold,
                    buy_alpha_threshold=buy_alpha_threshold,
                    sell_score_threshold=sell_score_threshold,
                    sell_alpha_threshold=sell_alpha_threshold,
                )
                if not beta_gate_passed:
                    side = "HOLD"

                # 获取来源信号
                signals = self.signal_provider.get_active_signals(security_code)
                signal_ids = [s.get("signal_id") for s in signals if s.get("signal_id")]

                # 获取来源候选
                candidates = self.candidate_provider.get_active_candidates(request.account_id)
                candidate_ids = [
                    c.get("candidate_id")
                    for c in candidates
                    if c.get("security_code") == security_code and c.get("candidate_id")
                ]

                # 生成推荐
                recommendation = UnifiedRecommendation(
                    recommendation_id=f"urec_{uuid4().hex[:12]}",
                    account_id=request.account_id,
                    security_code=security_code,
                    side=side,
                    regime=snapshot.regime,
                    regime_confidence=snapshot.regime_confidence,
                    policy_level=snapshot.policy_level,
                    beta_gate_passed=snapshot.beta_gate_passed,
                    sentiment_score=snapshot.sentiment_score,
                    flow_score=snapshot.flow_score,
                    technical_score=snapshot.technical_score,
                    fundamental_score=snapshot.fundamental_score,
                    alpha_model_score=snapshot.alpha_model_score,
                    composite_score=composite_score,
                    confidence=min(snapshot.regime_confidence + snapshot.alpha_model_score, 1.0)
                    / 2,
                    reason_codes=penalty_reasons
                    + valuation_reason_codes
                    + self._generate_reason_codes(snapshot, composite_score),
                    human_rationale=self._generate_rationale(snapshot, composite_score, side),
                    fair_value=(
                        Decimal(str(valuation.get("fair_value", 0))) if valuation else Decimal("0")
                    ),
                    entry_price_low=(
                        Decimal(str(valuation.get("entry_price_low", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    entry_price_high=(
                        Decimal(str(valuation.get("entry_price_high", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    target_price_low=(
                        Decimal(str(valuation.get("target_price_low", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    target_price_high=(
                        Decimal(str(valuation.get("target_price_high", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    stop_loss_price=(
                        Decimal(str(valuation.get("stop_loss_price", 0)))
                        if valuation
                        else Decimal("0")
                    ),
                    position_pct=default_position_pct,
                    suggested_quantity=0,  # 需要根据账户资金计算
                    max_capital=max_capital_per_trade,
                    source_signal_ids=signal_ids,
                    source_candidate_ids=candidate_ids,
                    feature_snapshot_id=snapshot.snapshot_id,
                    status=RecommendationStatus.NEW,
                )

                raw_recommendations.append(recommendation)

            # 3. 后端聚合（去重）
            # 4. 冲突处理
            deduplicated, conflicts, conflict_pairs = aggregator.aggregate(raw_recommendations)

            # 保存推荐和冲突
            saved_recommendations: list[UnifiedRecommendation] = []
            for rec in deduplicated:
                saved = self.recommendation_repo.save(rec)
                saved_recommendations.append(saved)

            saved_conflicts: list[UnifiedRecommendation] = []
            for conflict in conflicts:
                self.recommendation_repo.mark_as_conflict(conflict.recommendation_id)
                saved_conflicts.append(conflict)

            logger.info(
                f"Generated {len(saved_recommendations)} recommendations, "
                f"{len(saved_conflicts)} conflicts for account {request.account_id}"
            )

            return GenerateRecommendationsResponse(
                success=True,
                recommendations=saved_recommendations,
                conflicts=saved_conflicts,
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to generate recommendations: {e}", exc_info=True)
            return GenerateRecommendationsResponse(
                success=False,
                error=str(e),
            )

    def _determine_side(
        self,
        composite_score: float,
        alpha_score: float,
        buy_score_threshold: float,
        buy_alpha_threshold: float,
        sell_score_threshold: float,
        sell_alpha_threshold: float,
    ) -> str:
        """
        确定推荐方向

        Args:
            composite_score: 综合分
            alpha_score: Alpha 分数

        Returns:
            方向 (BUY/SELL/HOLD)
        """
        if composite_score >= buy_score_threshold and alpha_score >= buy_alpha_threshold:
            return "BUY"
        elif composite_score <= sell_score_threshold or alpha_score <= sell_alpha_threshold:
            return "SELL"
        else:
            return "HOLD"

    def _generate_reason_codes(
        self,
        snapshot: "DecisionFeatureSnapshot",
        composite_score: float,
    ) -> list[str]:
        """
        生成原因代码

        Args:
            snapshot: 特征快照
            composite_score: 综合分

        Returns:
            原因代码列表
        """
        codes = []

        if snapshot.alpha_model_score >= 0.7:
            codes.append("ALPHA_HIGH")
        elif snapshot.alpha_model_score <= 0.3:
            codes.append("ALPHA_LOW")

        if snapshot.regime_confidence >= 0.8:
            codes.append("REGIME_CONFIDENT")

        if snapshot.beta_gate_passed:
            codes.append("BETA_GATE_PASS")
        else:
            codes.append("BETA_GATE_BLOCKED")

        if composite_score >= 0.7:
            codes.append("COMPOSITE_HIGH")

        return codes

    def _generate_rationale(
        self,
        snapshot: "DecisionFeatureSnapshot",
        composite_score: float,
        side: str,
    ) -> str:
        """
        生成人类可读理由

        Args:
            snapshot: 特征快照
            composite_score: 综合分
            side: 方向

        Returns:
            人类可读理由
        """
        parts = []

        if side == "BUY":
            parts.append("推荐买入")
        elif side == "SELL":
            parts.append("推荐卖出")
        else:
            parts.append("建议持有")

        parts.append(f"综合分 {composite_score:.2f}")

        if snapshot.alpha_model_score >= 0.7:
            parts.append(f"Alpha 分数较高({snapshot.alpha_model_score:.2f})")

        if snapshot.regime:
            parts.append(f"当前 Regime: {snapshot.regime}")

        if snapshot.policy_level:
            parts.append(f"政策档位: {snapshot.policy_level}")

        if not snapshot.beta_gate_passed:
            parts.append("Beta Gate 未通过，当前仅展示观察，不进入执行")

        return "。".join(parts) + "。"


@dataclass
class GetRecommendationsRequest:
    """获取推荐请求"""

    account_id: str
    status: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass
class GetRecommendationsResponse:
    """获取推荐响应"""

    success: bool
    recommendations: list["UnifiedRecommendation"] = field(default_factory=list)
    total_count: int = 0
    error: str = ""


class GetUnifiedRecommendationsUseCase:
    """
    获取统一推荐用例

    从仓储获取已生成的推荐列表。
    """

    def __init__(
        self,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 推荐仓储
        """
        self.recommendation_repo = recommendation_repo

    def execute(
        self,
        request: GetRecommendationsRequest,
    ) -> GetRecommendationsResponse:
        """
        执行获取推荐

        Args:
            request: 获取请求

        Returns:
            获取响应
        """
        try:
            recommendations = self.recommendation_repo.get_by_account(
                account_id=request.account_id,
                status=request.status,
            )

            return GetRecommendationsResponse(
                success=True,
                recommendations=recommendations,
                total_count=len(recommendations),
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get recommendations: {e}", exc_info=True)
            return GetRecommendationsResponse(
                success=False,
                error=str(e),
            )


@dataclass
class GetConflictsRequest:
    """获取冲突请求"""

    account_id: str


@dataclass
class GetConflictsResponse:
    """获取冲突响应"""

    success: bool
    conflicts: list["UnifiedRecommendation"] = field(default_factory=list)
    total_count: int = 0
    error: str = ""


class GetConflictsUseCase:
    """
    获取冲突用例

    从仓储获取冲突推荐列表。
    """

    def __init__(
        self,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol,
    ):
        """
        初始化用例

        Args:
            recommendation_repo: 推荐仓储
        """
        self.recommendation_repo = recommendation_repo

    def execute(
        self,
        request: GetConflictsRequest,
    ) -> GetConflictsResponse:
        """
        执行获取冲突

        Args:
            request: 获取请求

        Returns:
            获取响应
        """
        try:
            conflicts = self.recommendation_repo.get_conflicts(request.account_id)

            return GetConflictsResponse(
                success=True,
                conflicts=conflicts,
                total_count=len(conflicts),
            )

        except RECOVERABLE_DECISION_RHYTHM_EXCEPTIONS as e:
            logger.error(f"Failed to get conflicts: {e}", exc_info=True)
            return GetConflictsResponse(
                success=False,
                error=str(e),
            )
