"""
Decision Execution Event Handlers

处理决策执行相关的事件，确保跨模块状态一致性。

事件处理器负责：
1. DECISION_APPROVED: 回写 AlphaCandidate.last_decision_request_id
2. DECISION_EXECUTED: 回写 DecisionRequest 和 AlphaCandidate 的执行状态
3. DECISION_EXECUTION_FAILED: 回写失败状态

架构约束：
- 处理器位于 Application 层
- 通过依赖注入使用 Infrastructure 层
- 主事务成功优先，事件发布失败不回滚主事务
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from ..domain.entities import DomainEvent, EventHandler, EventType


logger = logging.getLogger(__name__)


class DecisionApprovedHandler(EventHandler):
    """
    决策批准事件处理器

    处理 DECISION_APPROVED 事件，回写 AlphaCandidate.last_decision_request_id。

    Attributes:
        event_bus: 事件总线（可选，用于发布后续事件）

    Example:
        >>> handler = DecisionApprovedHandler()
        >>> handler.can_handle(EventType.DECISION_APPROVED)  # True
    """

    def __init__(self, event_bus=None):
        """
        初始化处理器

        Args:
            event_bus: 事件总线（可选）
        """
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type == EventType.DECISION_APPROVED

    def handle(self, event: DomainEvent) -> None:
        """
        处理决策批准事件

        回写 AlphaCandidate.last_decision_request_id

        Args:
            event: 领域事件
        """
        try:
            # 从事件负载中提取数据
            candidate_id = event.get_payload_value("candidate_id")
            request_id = event.get_payload_value("request_id")

            if not candidate_id or not request_id:
                logger.debug(
                    f"Event {event.event_id} missing candidate_id or request_id, skipping"
                )
                return

            # 回写 AlphaCandidate
            self._update_alpha_candidate(candidate_id, request_id)

            logger.info(
                f"Updated AlphaCandidate.last_decision_request_id: "
                f"candidate={candidate_id}, request={request_id}"
            )

        except Exception as e:
            logger.error(
                f"Error handling DECISION_APPROVED event {event.event_id}: {e}",
                exc_info=True,
            )
            # 主事务成功优先，事件处理失败只记录日志
            # 不抛出异常，避免影响主流程

    def _update_alpha_candidate(self, candidate_id: str, request_id: str) -> None:
        """
        更新 AlphaCandidate 的 last_decision_request_id

        Args:
            candidate_id: 候选 ID
            request_id: 决策请求 ID
        """
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

        try:
            candidate = AlphaCandidateModel.objects.get(candidate_id=candidate_id)
            candidate.last_decision_request_id = request_id
            candidate.save(update_fields=["last_decision_request_id", "updated_at"])

        except ObjectDoesNotExist:
            logger.warning(f"AlphaCandidate not found: {candidate_id}")

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "events.DecisionApprovedHandler"


class DecisionExecutedHandler(EventHandler):
    """
    决策执行成功事件处理器

    处理 DECISION_EXECUTED 事件，回写执行状态。

    回写内容：
    - DecisionRequest.execution_status = EXECUTED
    - AlphaCandidate.status = EXECUTED
    - AlphaCandidate.last_execution_status = EXECUTED

    Attributes:
        event_bus: 事件总线（可选）

    Example:
        >>> handler = DecisionExecutedHandler()
        >>> handler.can_handle(EventType.DECISION_EXECUTED)  # True
    """

    def __init__(self, event_bus=None):
        """
        初始化处理器

        Args:
            event_bus: 事件总线（可选）
        """
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type == EventType.DECISION_EXECUTED

    def handle(self, event: DomainEvent) -> None:
        """
        处理决策执行成功事件

        回写 DecisionRequest 和 AlphaCandidate 的执行状态

        Args:
            event: 领域事件
        """
        try:
            # 从事件负载中提取数据
            request_id = event.get_payload_value("request_id")
            candidate_id = event.get_payload_value("candidate_id")
            execution_ref = event.get_payload_value("execution_ref")

            if not request_id:
                logger.warning(f"Event {event.event_id} missing request_id, skipping")
                return

            # 使用事务确保一致性
            with transaction.atomic():
                # 更新 DecisionRequest
                self._update_decision_request(request_id, execution_ref)

                # 更新 AlphaCandidate（如果存在）
                if candidate_id:
                    self._update_alpha_candidate_executed(candidate_id)

            logger.info(
                f"Updated execution status to EXECUTED: "
                f"request={request_id}, candidate={candidate_id}"
            )

        except Exception as e:
            logger.error(
                f"Error handling DECISION_EXECUTED event {event.event_id}: {e}",
                exc_info=True,
            )
            # 主事务成功优先，事件处理失败只记录日志

    def _update_decision_request(
        self, request_id: str, execution_ref: Optional[Dict[str, Any]]
    ) -> None:
        """
        更新 DecisionRequest 的执行状态

        Args:
            request_id: 决策请求 ID
            execution_ref: 执行引用（如 trade_id, position_id 等）
        """
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
        from apps.decision_rhythm.domain.entities import ExecutionStatus

        try:
            request = DecisionRequestModel.objects.get(request_id=request_id)
            request.execution_status = ExecutionStatus.EXECUTED.value
            request.executed_at = datetime.now(timezone.utc)
            if execution_ref:
                request.execution_ref = execution_ref
            request.save(
                update_fields=["execution_status", "executed_at", "execution_ref"]
            )

        except ObjectDoesNotExist:
            logger.warning(f"DecisionRequest not found: {request_id}")

    def _update_alpha_candidate_executed(self, candidate_id: str) -> None:
        """
        更新 AlphaCandidate 为已执行状态

        Args:
            candidate_id: 候选 ID
        """
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

        try:
            candidate = AlphaCandidateModel.objects.get(candidate_id=candidate_id)
            candidate.status = AlphaCandidateModel.EXECUTED
            candidate.last_execution_status = AlphaCandidateModel.EXECUTION_EXECUTED
            candidate.status_changed_at = datetime.now(timezone.utc)
            candidate.save(
                update_fields=[
                    "status",
                    "last_execution_status",
                    "status_changed_at",
                    "updated_at",
                ]
            )

        except ObjectDoesNotExist:
            logger.warning(f"AlphaCandidate not found: {candidate_id}")

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "events.DecisionExecutedHandler"


class DecisionExecutionFailedHandler(EventHandler):
    """
    决策执行失败事件处理器

    处理 DECISION_EXECUTION_FAILED 事件，回写失败状态。

    回写内容：
    - DecisionRequest.execution_status = FAILED
    - AlphaCandidate.status = ACTIONABLE（保留可操作状态，允许重试）
    - AlphaCandidate.last_execution_status = FAILED

    Attributes:
        event_bus: 事件总线（可选）

    Example:
        >>> handler = DecisionExecutionFailedHandler()
        >>> handler.can_handle(EventType.DECISION_EXECUTION_FAILED)  # True
    """

    def __init__(self, event_bus=None):
        """
        初始化处理器

        Args:
            event_bus: 事件总线（可选）
        """
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type == EventType.DECISION_EXECUTION_FAILED

    def handle(self, event: DomainEvent) -> None:
        """
        处理决策执行失败事件

        回写 DecisionRequest 和 AlphaCandidate 的失败状态

        Args:
            event: 领域事件
        """
        try:
            # 从事件负载中提取数据
            request_id = event.get_payload_value("request_id")
            candidate_id = event.get_payload_value("candidate_id")
            error_message = event.get_payload_value("error_message")

            if not request_id:
                logger.warning(
                    f"Event {event.event_id} missing request_id, skipping"
                )
                return

            # 使用事务确保一致性
            with transaction.atomic():
                # 更新 DecisionRequest
                self._update_decision_request_failed(request_id, error_message)

                # 更新 AlphaCandidate（如果存在）
                if candidate_id:
                    self._update_alpha_candidate_failed(candidate_id)

            logger.info(
                f"Updated execution status to FAILED: "
                f"request={request_id}, candidate={candidate_id}"
            )

        except Exception as e:
            logger.error(
                f"Error handling DECISION_EXECUTION_FAILED event {event.event_id}: {e}",
                exc_info=True,
            )
            # 主事务成功优先，事件处理失败只记录日志

    def _update_decision_request_failed(
        self, request_id: str, error_message: Optional[str]
    ) -> None:
        """
        更新 DecisionRequest 的执行失败状态

        Args:
            request_id: 决策请求 ID
            error_message: 错误信息
        """
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
        from apps.decision_rhythm.domain.entities import ExecutionStatus

        try:
            request = DecisionRequestModel.objects.get(request_id=request_id)
            request.execution_status = ExecutionStatus.FAILED.value
            request.save(update_fields=["execution_status"])

            # 错误信息记录到日志
            if error_message:
                logger.warning(
                    f"DecisionRequest {request_id} execution failed: {error_message}"
                )

        except ObjectDoesNotExist:
            logger.warning(f"DecisionRequest not found: {request_id}")

    def _update_alpha_candidate_failed(self, candidate_id: str) -> None:
        """
        更新 AlphaCandidate 为执行失败状态

        注意：保留 ACTIONABLE 状态，允许用户重试

        Args:
            candidate_id: 候选 ID
        """
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

        try:
            candidate = AlphaCandidateModel.objects.get(candidate_id=candidate_id)
            # 保留 ACTIONABLE 状态，允许重试
            candidate.last_execution_status = AlphaCandidateModel.EXECUTION_FAILED
            candidate.status_changed_at = datetime.now(timezone.utc)
            candidate.save(
                update_fields=[
                    "last_execution_status",
                    "status_changed_at",
                    "updated_at",
                ]
            )

        except ObjectDoesNotExist:
            logger.warning(f"AlphaCandidate not found: {candidate_id}")

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "events.DecisionExecutionFailedHandler"
