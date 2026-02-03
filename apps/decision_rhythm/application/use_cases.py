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
)
from ..domain.services import (
    QuotaManager,
    CooldownManager,
    RhythmManager,
    DecisionScheduler,
    QuotaCheckResult,
    CooldownCheckResult,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event


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
