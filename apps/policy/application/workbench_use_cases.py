"""Workbench use cases for Policy.

Owner module for the policy workbench: summary snapshot, item listing,
approve/reject/rollback/override event actions, and the sentiment gate state
query.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..domain.entities import SentimentGateThresholds, WorkbenchSummary
from ..domain.rules import calculate_gate_level, get_max_position_cap
from .event_use_cases import RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS
from .repository_provider import DjangoPolicyRepository, WorkbenchRepository

logger = logging.getLogger(__name__)

__all__ = [
    "ApproveEventInput",
    "ApproveEventOutput",
    "ApproveEventUseCase",
    "GetSentimentGateStateUseCase",
    "GetWorkbenchItemsUseCase",
    "GetWorkbenchSummaryUseCase",
    "OverrideEventInput",
    "OverrideEventOutput",
    "OverrideEventUseCase",
    "RejectEventInput",
    "RejectEventOutput",
    "RejectEventUseCase",
    "RollbackEventInput",
    "RollbackEventOutput",
    "RollbackEventUseCase",
    "SentimentGateStateInput",
    "SentimentGateStateOutput",
    "WorkbenchItemsInput",
    "WorkbenchItemsOutput",
    "WorkbenchSummaryInput",
    "WorkbenchSummaryOutput",
]


# 工作台 Use Cases


@dataclass
class WorkbenchSummaryInput:
    """工作台概览输入 DTO"""

    pass


@dataclass
class WorkbenchSummaryOutput:
    """工作台概览输出 DTO"""

    success: bool
    summary: WorkbenchSummary | None = None
    error: str | None = None


class GetWorkbenchSummaryUseCase:
    """获取工作台概览用例"""

    def __init__(
        self,
        workbench_repo: WorkbenchRepository | None = None,
        policy_repo: DjangoPolicyRepository | None = None,
    ):
        self.workbench_repo = workbench_repo or WorkbenchRepository()
        self.policy_repo = policy_repo or DjangoPolicyRepository()

    def execute(self, input_dto: WorkbenchSummaryInput = None) -> WorkbenchSummaryOutput:
        """
        获取工作台概览数据

        Returns:
            WorkbenchSummaryOutput: 包含双闸状态、待审核数、SLA超时数等
        """
        try:
            # 获取政策档位（仅已生效的政策事件）
            policy_level = self.policy_repo.get_current_policy_level()

            # 获取触发政策档位的事件
            latest_policy_event = self.workbench_repo.get_latest_effective_policy_title()

            # 获取全局热度与情绪
            global_heat, global_sentiment = self.workbench_repo.get_global_heat_sentiment()

            # 计算闸门等级
            gate_config = self.workbench_repo.get_gate_config("all")
            global_gate_level = None
            if gate_config and global_heat is not None:
                thresholds = SentimentGateThresholds(
                    heat_l1_threshold=gate_config.heat_l1_threshold,
                    heat_l2_threshold=gate_config.heat_l2_threshold,
                    heat_l3_threshold=gate_config.heat_l3_threshold,
                    sentiment_l1_threshold=gate_config.sentiment_l1_threshold,
                    sentiment_l2_threshold=gate_config.sentiment_l2_threshold,
                    sentiment_l3_threshold=gate_config.sentiment_l3_threshold,
                )
                global_gate_level = calculate_gate_level(global_heat, global_sentiment, thresholds)

            # 获取配置用于 SLA 计算
            ingestion_config = self.workbench_repo.get_ingestion_config()

            # 获取统计数
            pending_review_count = self.workbench_repo.get_pending_review_count()
            sla_exceeded_count = self.workbench_repo.get_sla_exceeded_count(
                p23_sla_hours=ingestion_config.p23_sla_hours,
                normal_sla_hours=ingestion_config.normal_sla_hours,
            )
            effective_today_count = self.workbench_repo.get_effective_today_count()

            # 获取最后抓取时间
            last_fetch_at = self.workbench_repo.get_last_fetch_at()

            summary = WorkbenchSummary(
                policy_level=policy_level,
                policy_level_event=latest_policy_event,
                global_heat_score=global_heat,
                global_sentiment_score=global_sentiment,
                global_gate_level=global_gate_level,
                pending_review_count=pending_review_count,
                sla_exceeded_count=sla_exceeded_count,
                effective_today_count=effective_today_count,
                last_fetch_at=last_fetch_at,
            )

            return WorkbenchSummaryOutput(success=True, summary=summary)

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to get workbench summary: {e}")
            return WorkbenchSummaryOutput(success=False, error=str(e))


@dataclass
class WorkbenchItemsInput:
    """工作台事件列表输入 DTO"""

    tab: str = "pending"  # pending, effective, all
    event_type: str | None = None
    level: str | None = None
    gate_level: str | None = None
    asset_class: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    search: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class WorkbenchItemsOutput:
    """工作台事件列表输出 DTO"""

    success: bool
    items: list[dict[str, Any]] = None
    total: int = 0
    error: str | None = None


class GetWorkbenchItemsUseCase:
    """获取工作台事件列表用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: WorkbenchItemsInput) -> WorkbenchItemsOutput:
        """
        获取工作台事件列表

        Args:
            input_dto: 筛选参数

        Returns:
            WorkbenchItemsOutput: 事件列表
        """
        try:
            result = self.workbench_repo.list_workbench_items(
                tab=input_dto.tab,
                event_type=input_dto.event_type,
                level=input_dto.level,
                gate_level=input_dto.gate_level,
                asset_class=input_dto.asset_class,
                start_date=input_dto.start_date,
                end_date=input_dto.end_date,
                search=input_dto.search,
                limit=input_dto.limit,
                offset=input_dto.offset,
            )
            return WorkbenchItemsOutput(
                success=True,
                items=result["items"],
                total=result["total"],
            )

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to get workbench items: {e}")
            return WorkbenchItemsOutput(success=False, error=str(e))


@dataclass
class ApproveEventInput:
    """审核通过输入 DTO"""

    event_id: int
    user_id: int
    reason: str = ""


@dataclass
class ApproveEventOutput:
    """审核通过输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class ApproveEventUseCase:
    """审核通过用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: ApproveEventInput) -> ApproveEventOutput:
        """
        审核通过事件

        Args:
            input_dto: 包含 event_id, user_id, reason

        Returns:
            ApproveEventOutput: 操作结果
        """
        try:
            event = self.workbench_repo.approve_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} approved by user {input_dto.user_id}")
                return ApproveEventOutput(success=True, event_id=event.id)
            else:
                return ApproveEventOutput(success=False, error="Event not found")

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to approve event: {e}")
            return ApproveEventOutput(success=False, error=str(e))


@dataclass
class RejectEventInput:
    """审核拒绝输入 DTO"""

    event_id: int
    user_id: int
    reason: str


@dataclass
class RejectEventOutput:
    """审核拒绝输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class RejectEventUseCase:
    """审核拒绝用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: RejectEventInput) -> RejectEventOutput:
        """
        审核拒绝事件

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）

        Returns:
            RejectEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return RejectEventOutput(success=False, error="拒绝原因不能为空")

        try:
            event = self.workbench_repo.reject_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} rejected by user {input_dto.user_id}")
                return RejectEventOutput(success=True, event_id=event.id)
            else:
                return RejectEventOutput(success=False, error="Event not found")

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to reject event: {e}")
            return RejectEventOutput(success=False, error=str(e))


@dataclass
class RollbackEventInput:
    """回滚生效输入 DTO"""

    event_id: int
    user_id: int
    reason: str


@dataclass
class RollbackEventOutput:
    """回滚生效输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class RollbackEventUseCase:
    """回滚生效用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: RollbackEventInput) -> RollbackEventOutput:
        """
        回滚事件生效状态

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）

        Returns:
            RollbackEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return RollbackEventOutput(success=False, error="回滚原因不能为空")

        try:
            event = self.workbench_repo.rollback_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} rolled back by user {input_dto.user_id}")
                return RollbackEventOutput(success=True, event_id=event.id)
            else:
                return RollbackEventOutput(success=False, error="Event not found")

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to rollback event: {e}")
            return RollbackEventOutput(success=False, error=str(e))


@dataclass
class OverrideEventInput:
    """临时豁免输入 DTO"""

    event_id: int
    user_id: int
    reason: str
    new_level: str | None = None


@dataclass
class OverrideEventOutput:
    """临时豁免输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class OverrideEventUseCase:
    """临时豁免用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: OverrideEventInput) -> OverrideEventOutput:
        """
        临时豁免事件

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）, new_level（可选）

        Returns:
            OverrideEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return OverrideEventOutput(success=False, error="豁免原因不能为空")

        try:
            event = self.workbench_repo.override_event(
                event_id=input_dto.event_id,
                user_id=input_dto.user_id,
                reason=input_dto.reason,
                new_level=input_dto.new_level,
            )

            if event:
                logger.info(f"Event {input_dto.event_id} overridden by user {input_dto.user_id}")
                return OverrideEventOutput(success=True, event_id=event.id)
            else:
                return OverrideEventOutput(success=False, error="Event not found")

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to override event: {e}")
            return OverrideEventOutput(success=False, error=str(e))


@dataclass
class SentimentGateStateInput:
    """热点情绪闸门状态输入 DTO"""

    asset_class: str = "all"


@dataclass
class SentimentGateStateOutput:
    """热点情绪闸门状态输出 DTO"""

    success: bool
    asset_class: str | None = None
    gate_level: str | None = None
    heat_score: float | None = None
    sentiment_score: float | None = None
    max_position_cap: float | None = None
    thresholds: dict[str, float] | None = None
    error: str | None = None


class GetSentimentGateStateUseCase:
    """获取热点情绪闸门状态用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: SentimentGateStateInput) -> SentimentGateStateOutput:
        """
        获取指定资产类的闸门状态

        Args:
            input_dto: 包含 asset_class

        Returns:
            SentimentGateStateOutput: 闸门状态
        """
        try:
            # 获取闸门配置
            gate_config = self.workbench_repo.get_gate_config(input_dto.asset_class)
            if not gate_config:
                return SentimentGateStateOutput(
                    success=False,
                    error=f"No gate config found for asset class: {input_dto.asset_class}",
                )

            # 获取该资产类的热度与情绪（简化：使用全局数据）
            global_heat, global_sentiment = self.workbench_repo.get_global_heat_sentiment()

            # 计算闸门等级
            thresholds = SentimentGateThresholds(
                heat_l1_threshold=gate_config.heat_l1_threshold,
                heat_l2_threshold=gate_config.heat_l2_threshold,
                heat_l3_threshold=gate_config.heat_l3_threshold,
                sentiment_l1_threshold=gate_config.sentiment_l1_threshold,
                sentiment_l2_threshold=gate_config.sentiment_l2_threshold,
                sentiment_l3_threshold=gate_config.sentiment_l3_threshold,
            )
            gate_level = calculate_gate_level(global_heat, global_sentiment, thresholds)

            # 获取仓位上限
            cap_config = {
                "max_position_cap_l2": gate_config.max_position_cap_l2,
                "max_position_cap_l3": gate_config.max_position_cap_l3,
            }
            max_cap = get_max_position_cap(gate_level, cap_config)

            return SentimentGateStateOutput(
                success=True,
                asset_class=input_dto.asset_class,
                gate_level=gate_level.value if gate_level else None,
                heat_score=global_heat,
                sentiment_score=global_sentiment,
                max_position_cap=max_cap,
                thresholds={
                    "heat_l1": gate_config.heat_l1_threshold,
                    "heat_l2": gate_config.heat_l2_threshold,
                    "heat_l3": gate_config.heat_l3_threshold,
                    "sentiment_l1": gate_config.sentiment_l1_threshold,
                    "sentiment_l2": gate_config.sentiment_l2_threshold,
                    "sentiment_l3": gate_config.sentiment_l3_threshold,
                },
            )

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.exception(f"Failed to get sentiment gate state: {e}")
            return SentimentGateStateOutput(success=False, error=str(e))
