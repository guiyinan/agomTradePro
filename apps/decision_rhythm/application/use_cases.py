"""
Decision Rhythm Application Use Cases

决策频率约束和配额管理的用例编排层。
负责协调配额管理、冷却控制和决策调度。

仅依赖 Domain 层和事件总线，不直接依赖 ORM 或外部 API。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..domain.entities import (
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    RhythmConfig,
    DecisionPriority,
    QuotaPeriod,
    ExecutionTarget,
    ExecutionStatus,
)
from ..domain.services import (
    QuotaManager,
    CooldownManager,
    RhythmManager,
    DecisionScheduler,
    QuotaCheckResult,
    CooldownCheckResult,
    PrecheckResult,
    ExecutionResult,
    ExecutionStatusStateMachine,
    CandidateStatusStateMachine,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event
from apps.alpha_trigger.domain.entities import CandidateStatus


logger = logging.getLogger(__name__)


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
    trigger_id: Optional[str] = None
    candidate_id: Optional[str] = None
    reason: str = ""
    expected_confidence: float = 0.0
    quantity: Optional[int] = None
    notional: Optional[float] = None
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
    response: Optional[DecisionResponse] = None
    decision_request: Optional[DecisionRequest] = None
    error: Optional[str] = None


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
    status: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


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
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class SubmitBatchRequestRequest:
    """
    批量提交决策请求

    Attributes:
        requests: 决策请求列表
        quota_period: 使用的配额周期
    """

    requests: List[SubmitDecisionRequestRequest]
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
    responses: List[DecisionResponse] = field(default_factory=list)
    decision_requests: List[DecisionRequest] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ResetQuotaRequest:
    """
    重置配额请求

    Attributes:
        period: 配额周期（可选，None 表示重置所有）
    """

    period: Optional[QuotaPeriod] = None


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
    error: Optional[str] = None


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

        except Exception as e:
            logger.error(f"Failed to submit decision request: {e}", exc_info=True)
            return SubmitDecisionRequestResponse(
                success=False,
                error=str(e),
            )

    def _publish_event(self, decision_request: DecisionRequest, response: DecisionResponse):
        """发布事件"""
        if self.event_bus is None:
            return

        event_type = EventType.DECISION_APPROVED if response.approved else EventType.DECISION_REJECTED

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

        except Exception as e:
            logger.error(f"Failed to submit batch decision requests: {e}", exc_info=True)
            return SubmitBatchRequestResponse(
                success=False,
                error=str(e),
            )

    def _calculate_summary(self, responses: List[DecisionResponse]) -> Dict[str, Any]:
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

    def _publish_summary_event(self, responses: List[DecisionResponse], summary: Dict[str, Any]):
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

        except Exception as e:
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

        except Exception as e:
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

        except Exception as e:
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

    def execute(self) -> Dict[str, Any]:
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
    result: Optional[PrecheckResult] = None
    error: Optional[str] = None


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
    sim_account_id: Optional[int] = None
    asset_code: Optional[str] = None
    action: Optional[str] = None  # "buy" or "sell"
    quantity: Optional[int] = None
    price: Optional[float] = None
    reason: str = ""
    # 实盘账户参数
    portfolio_id: Optional[int] = None
    shares: Optional[int] = None
    avg_cost: Optional[float] = None
    current_price: Optional[float] = None


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
    result: Optional[ExecutionResult] = None
    error: Optional[str] = None


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
        warnings: List[str] = []
        errors: List[str] = []
        details: Dict[str, Any] = {}

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
                    details["beta_gate_decision"] = decision.to_dict() if hasattr(decision, 'to_dict') else {}
                    if not beta_gate_passed:
                        errors.append(f"Beta Gate 未通过: {decision.blocking_reason}")
                except Exception as e:
                    warnings.append(f"Beta Gate 检查失败（跳过）: {e}")

            # 4. 检查配额
            quota_ok = True
            try:
                quota = self.quota_repo.get_quota(QuotaPeriod.WEEKLY)
                if quota and quota.is_quota_exceeded:
                    quota_ok = False
                    errors.append("配额已耗尽")
                details["quota_status"] = quota.to_dict() if quota else {}
            except Exception as e:
                warnings.append(f"配额检查失败（跳过）: {e}")

            # 5. 检查冷却期
            cooldown_ok = True
            try:
                cooldown = self.cooldown_repo.get_active_cooldown(candidate.asset_code)
                if cooldown and not cooldown.is_decision_ready:
                    cooldown_ok = False
                    errors.append(f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时")
                details["cooldown_status"] = cooldown.to_dict() if cooldown else None
            except Exception as e:
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

        except Exception as e:
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
            event_bus: 事件总线（可选）
        """
        self.request_repo = request_repo
        self.candidate_repo = candidate_repo
        self.simulated_account_repo = simulated_account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
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
                executed_at=datetime.now(),
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
                executed_at=datetime.now(),
                execution_ref=execution_ref,
                candidate_status=candidate_status,
            )

            logger.info(
                f"Decision executed: {request.request_id} "
                f"-> {request.target.value}, ref={execution_ref}"
            )

            return ExecuteDecisionResponse(success=True, result=result)

        except Exception as e:
            logger.error(f"Execute decision failed: {e}", exc_info=True)
            # 更新决策请求为失败状态
            try:
                self.request_repo.update_execution_status(
                    request_id=request.request_id,
                    execution_status=ExecutionStatus.FAILED,
                )
            except Exception:
                pass
            return ExecuteDecisionResponse(success=False, error=str(e))

    def _execute_simulated(
        self,
        request: ExecuteDecisionRequest,
        decision_request: DecisionRequest,
    ) -> Dict[str, Any]:
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
            use_case = ExecuteBuyOrderUseCase(
                account_repo=self.simulated_account_repo,
                position_repo=self.position_repo,
                trade_repo=self.trade_repo,
            )
            trade = use_case.execute(
                account_id=request.sim_account_id,
                asset_code=request.asset_code,
                asset_name=request.asset_code,  # 简化处理
                asset_type="equity",
                quantity=request.quantity,
                price=request.price,
                reason=request.reason,
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

    def _execute_account(
        self,
        request: ExecuteDecisionRequest,
        decision_request: DecisionRequest,
    ) -> Dict[str, Any]:
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
        from apps.account.infrastructure.repositories import PositionRepository
        from decimal import Decimal

        position_repo = PositionRepository()

        position = position_repo.update_or_create_position(
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
        execution_ref: Dict[str, Any],
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
