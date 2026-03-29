"""
Alpha Trigger Repositories

Alpha 事件触发的数据仓储实现。
实现 Domain 层定义的 Repository Protocol。

这些仓储桥接 Domain 层实体和 Django ORM 模型。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateStatus,
    InvalidationCondition,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)
from .models import (
    AlphaCandidateModel,
    AlphaTriggerModel,
)

logger = logging.getLogger(__name__)


class AlphaTriggerRepository:
    """
    Alpha 触发器仓储

    管理触发器的持久化。

    Attributes:
        None（使用 Django ORM）

    Example:
        >>> repo = AlphaTriggerRepository()
        >>> trigger = repo.get_by_id("trigger_001")
    """

    def __init__(self):
        """初始化仓储"""
        self.model = AlphaTriggerModel

    def get_by_id(self, trigger_id: str) -> AlphaTrigger | None:
        """
        按 ID 获取触发器

        Args:
            trigger_id: 触发器 ID

        Returns:
            AlphaTrigger 实体或 None
        """
        try:
            model = self.model.objects.get(trigger_id=trigger_id)
            return model.to_domain()
        except ObjectDoesNotExist:
            return None

    def get_by_signal_id(self, signal_id: str) -> AlphaTrigger | None:
        """
        按源信号 ID 获取触发器

        Args:
            signal_id: 源信号 ID

        Returns:
            AlphaTrigger 实体或 None
        """
        try:
            model = self.model.objects.get(source_signal_id=signal_id)
            return model.to_domain()
        except ObjectDoesNotExist:
            return None

    def get_active(
        self,
        asset_code: str | None = None,
        min_strength: SignalStrength | None = None,
    ) -> list[AlphaTrigger]:
        """
        获取活跃触发器

        Args:
            asset_code: 资产代码过滤（可选）
            min_strength: 最小信号强度（可选）

        Returns:
            AlphaTrigger 实体列表
        """
        queryset = self.model.objects.filter(
            status=self.model.ACTIVE,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))

        if asset_code:
            queryset = queryset.filter(asset_code=asset_code)

        if min_strength:
            strength_order = [
                self.model.VERY_WEAK,
                self.model.WEAK,
                self.model.MODERATE,
                self.model.STRONG,
                self.model.VERY_STRONG,
            ]
            min_index = strength_order.index(str(min_strength.value).upper())
            valid_strengths = strength_order[min_index:]
            queryset = queryset.filter(strength__in=valid_strengths)

        models = queryset.order_by("-created_at")

        return [m.to_domain() for m in models]

    def get_by_regime(self, regime: str) -> list[AlphaTrigger]:
        """
        按相关 Regime 获取触发器

        Args:
            regime: Regime 名称

        Returns:
            AlphaTrigger 实体列表
        """
        models = self.model.objects.filter(related_regime=regime).order_by("-created_at")

        return [m.to_domain() for m in models]

    def get_by_type(self, trigger_type: TriggerType) -> list[AlphaTrigger]:
        """
        按类型获取触发器

        Args:
            trigger_type: 触发器类型

        Returns:
            AlphaTrigger 实体列表
        """
        models = self.model.objects.filter(
            trigger_type=str(trigger_type.value).upper()
        ).order_by("-created_at")

        return [m.to_domain() for m in models]

    def save(self, trigger: AlphaTrigger) -> AlphaTrigger:
        """
        保存触发器

        Args:
            trigger: AlphaTrigger 实体

        Returns:
            保存后的 AlphaTrigger 实体
        """
        # 检查是否已存在
        existing = self.model.objects.filter(trigger_id=trigger.trigger_id).first()

        if existing:
            # 更新
            model = existing
            model.status = str(trigger.status.value).upper()
            model.triggered_at = trigger.triggered_at
            model.invalidated_at = trigger.invalidated_at
            model.custom_data = getattr(trigger, "custom_data", {}) or {}

        else:
            # 创建
            model = AlphaTriggerModel.from_domain(trigger)

        model.full_clean()
        model.save()

        logger.info(
            f"Alpha trigger saved: {model.trigger_id} "
            f"({model.asset_code}, {model.status})"
        )

        return model.to_domain()

    def update_status(
        self,
        trigger_id: str,
        status: TriggerStatus,
        triggered_at: datetime | None = None,
        invalidated_at: datetime | None = None,
    ) -> AlphaTrigger:
        """
        更新触发器状态

        Args:
            trigger_id: 触发器 ID
            status: 新状态
            triggered_at: 触发时间（可选）
            invalidated_at: 证伪时间（可选）

        Returns:
            更新后的 AlphaTrigger 实体

        Raises:
            ValueError: 触发器不存在
        """
        try:
            model = self.model.objects.get(trigger_id=trigger_id)
            model.status = str(status.value).upper()

            if triggered_at:
                model.triggered_at = triggered_at

            if invalidated_at:
                model.invalidated_at = invalidated_at

            model.save()

            return model.to_domain()

        except ObjectDoesNotExist:
            raise ValueError(f"Trigger not found: {trigger_id}")

    def get_expired(self) -> list[AlphaTrigger]:
        """
        获取已过期但状态未更新的触发器

        Returns:
            AlphaTrigger 实体列表
        """
        now = timezone.now()
        models = self.model.objects.filter(
            status=str(TriggerStatus.ACTIVE.value).upper(),
            expires_at__lt=now,
        )

        # 更新状态为过期
        for model in models:
            model.status = str(TriggerStatus.EXPIRED.value).upper()
            model.save()

        return [m.to_domain() for m in models]

    def get_statistics(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        获取统计信息

        Args:
            days: 统计天数

        Returns:
            统计信息字典
        """
        since = timezone.now() - timezone.timedelta(days=days)
        queryset = self.model.objects.filter(created_at__gte=since)

        total = queryset.count()
        active = queryset.filter(status=str(TriggerStatus.ACTIVE.value).upper()).count()
        triggered = queryset.filter(status=str(TriggerStatus.TRIGGERED.value).upper()).count()
        invalidated = queryset.filter(status=str(TriggerStatus.INVALIDATED.value).upper()).count()

        # 按类型分组
        by_type = {}
        for trigger_type, _ in self.model.TRIGGER_TYPE_CHOICES:
            count = queryset.filter(trigger_type=trigger_type).count()
            by_type[trigger_type] = count

        # 按状态分组
        by_status = {}
        for status, _ in self.model.STATUS_CHOICES:
            count = queryset.filter(status=status).count()
            by_status[status] = count

        return {
            "total": total,
            "active": active,
            "triggered": triggered,
            "invalidated": invalidated,
            "by_type": by_type,
            "by_status": by_status,
        }

    def delete(self, trigger_id: str) -> bool:
        """
        删除触发器（软删除）

        Args:
            trigger_id: 触发器 ID

        Returns:
            是否删除成功
        """
        try:
            model = self.model.objects.get(trigger_id=trigger_id)
            model.status = str(TriggerStatus.CANCELLED.value).upper()
            model.save()
            logger.info(f"Alpha trigger cancelled: {trigger_id}")
            return True
        except ObjectDoesNotExist:
            return False


class AlphaCandidateRepository:
    """
    Alpha 候选仓储

    管理候选的持久化。

    Attributes:
        None（使用 Django ORM）

    Example:
        >>> repo = AlphaCandidateRepository()
        >>> candidate = repo.get_by_id("candidate_001")
    """

    def __init__(self):
        """初始化仓储"""
        self.model = AlphaCandidateModel

    def get_by_id(self, candidate_id: str) -> AlphaCandidate | None:
        """
        按 ID 获取候选

        Args:
            candidate_id: 候选 ID

        Returns:
            AlphaCandidate 实体或 None
        """
        try:
            model = self.model.objects.get(candidate_id=candidate_id)
            return model.to_domain()
        except ObjectDoesNotExist:
            return None

    def get_by_trigger_id(self, trigger_id: str) -> AlphaCandidate | None:
        """
        按触发器 ID 获取候选

        Args:
            trigger_id: 触发器 ID

        Returns:
            AlphaCandidate 实体或 None
        """
        try:
            model = self.model.objects.filter(trigger_id=trigger_id).first()
            if model:
                return model.to_domain()
            return None
        except ObjectDoesNotExist:
            return None

    def get_by_asset(
        self,
        asset_code: str,
        status: CandidateStatus | None = None,
    ) -> list[AlphaCandidate]:
        """
        按资产获取候选

        Args:
            asset_code: 资产代码
            status: 状态过滤（可选）

        Returns:
            AlphaCandidate 实体列表
        """
        queryset = self.model.objects.filter(asset_code=asset_code)

        if status:
            queryset = queryset.filter(status=status.value)

        models = queryset.order_by("-created_at")

        return [m.to_domain() for m in models]

    def get_actionable(
        self,
        min_strength: SignalStrength | None = None,
    ) -> list[AlphaCandidate]:
        """
        获取可操作的候选

        Args:
            min_strength: 最小信号强度（可选）

        Returns:
            AlphaCandidate 实体列表
        """
        queryset = self.model.objects.filter(status=self.model.ACTIONABLE)

        if min_strength:
            strength_order = [
                self.model.VERY_WEAK,
                self.model.WEAK,
                self.model.MODERATE,
                self.model.STRONG,
                self.model.VERY_STRONG,
            ]
            min_index = strength_order.index(min_strength.value)
            valid_strengths = strength_order[min_index:]
            queryset = queryset.filter(strength__in=valid_strengths)

        models = queryset.order_by("-strength", "-created_at")

        return [m.to_domain() for m in models]

    def get_watch_list(self) -> list[AlphaCandidate]:
        """
        获取观察列表

        Returns:
            AlphaCandidate 实体列表
        """
        models = (
            self.model.objects.filter(status=self.model.WATCH)
            .order_by("-created_at")
        )

        return [m.to_domain() for m in models]

    def save(self, candidate: AlphaCandidate) -> AlphaCandidate:
        """
        保存候选

        Args:
            candidate: AlphaCandidate 实体

        Returns:
            保存后的 AlphaCandidate 实体
        """
        # 检查是否已存在
        existing = self.model.objects.filter(candidate_id=candidate.candidate_id).first()

        if existing:
            # 更新
            model = existing
            model.status = candidate.status.value
            model.entry_zone = candidate.entry_zone
            model.exit_zone = candidate.exit_zone
            model.time_horizon = candidate.time_horizon
            model.expected_return = candidate.expected_return
            model.risk_level = candidate.risk_level
            model.custom_data = getattr(candidate, "metadata", {}) or {}

            # 如果状态变更，更新状态变更时间
            if model.status != candidate.status.value:
                model.status_changed_at = timezone.now()

            # 如果提升为信号，记录时间
            if candidate.status == CandidateStatus.EXECUTED:
                if not model.promoted_to_signal_at:
                    model.promoted_to_signal_at = timezone.now()

        else:
            # 创建
            model = AlphaCandidateModel.from_domain(candidate)

        model.full_clean()
        model.save()

        logger.info(
            f"Alpha candidate saved: {model.candidate_id} "
            f"({model.asset_code}, {model.status})"
        )

        return model.to_domain()

    def update_status(
        self,
        candidate_id: str,
        status: CandidateStatus,
    ) -> AlphaCandidate:
        """
        更新候选状态

        Args:
            candidate_id: 候选 ID
            status: 新状态

        Returns:
            更新后的 AlphaCandidate 实体

        Raises:
            ValueError: 候选不存在
        """
        try:
            model = self.model.objects.get(candidate_id=candidate_id)
            model.status = status.value
            model.status_changed_at = timezone.now()

            if status == CandidateStatus.EXECUTED:
                model.promoted_to_signal_at = timezone.now()

            model.save()

            return model.to_domain()

        except ObjectDoesNotExist:
            raise ValueError(f"Candidate not found: {candidate_id}")

    def update_last_decision_request_id(
        self,
        candidate_id: str,
        request_id: str,
    ) -> bool:
        """更新候选的最后决策请求 ID。"""
        updated = self.model.objects.filter(candidate_id=candidate_id).update(
            last_decision_request_id=request_id,
            updated_at=timezone.now(),
        )
        if updated:
            logger.info(
                "Alpha candidate last_decision_request_id updated: %s -> %s",
                candidate_id,
                request_id,
            )
            return True

        logger.warning(f"AlphaCandidate not found: {candidate_id}")
        return False

    def update_status_to_rejected(self, candidate_id: str) -> bool:
        """更新候选状态为已拒绝。"""
        try:
            self.update_status(candidate_id, CandidateStatus.REJECTED)
            logger.info(f"AlphaCandidate.status updated to REJECTED: {candidate_id}")
            return True
        except ValueError:
            logger.warning(f"AlphaCandidate not found: {candidate_id}")
            return False

    def update_status_to_executed(self, candidate_id: str) -> bool:
        """更新候选状态为已执行，并同步执行状态。"""
        try:
            model = self.model.objects.get(candidate_id=candidate_id)
            model.status = CandidateStatus.EXECUTED.value
            model.last_execution_status = self.model.EXECUTION_EXECUTED
            model.status_changed_at = timezone.now()
            if not model.promoted_to_signal_at:
                model.promoted_to_signal_at = timezone.now()
            model.save(
                update_fields=[
                    "status",
                    "last_execution_status",
                    "status_changed_at",
                    "promoted_to_signal_at",
                    "updated_at",
                ]
            )
            logger.info(f"AlphaCandidate.status updated to EXECUTED: {candidate_id}")
            return True
        except ObjectDoesNotExist:
            logger.warning(f"AlphaCandidate not found: {candidate_id}")
            return False

    def update_execution_status_to_failed(self, candidate_id: str) -> bool:
        """更新候选执行状态为失败，保留当前候选状态。"""
        updated = self.model.objects.filter(candidate_id=candidate_id).update(
            last_execution_status=self.model.EXECUTION_FAILED,
            status_changed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        if updated:
            logger.info(
                "AlphaCandidate.last_execution_status updated to FAILED: %s",
                candidate_id,
            )
            return True

        logger.warning(f"AlphaCandidate not found: {candidate_id}")
        return False

    def get_statistics(
        self,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        获取统计信息

        Args:
            days: 统计天数

        Returns:
            统计信息字典
        """
        since = timezone.now() - timezone.timedelta(days=days)
        queryset = self.model.objects.filter(created_at__gte=since)

        total = queryset.count()
        actionable = queryset.actionable().count()
        watch = queryset.watch().count()
        candidate = queryset.candidate().count()

        # 按状态分组
        by_status = {}
        for status, _ in self.model.CANDIDATE_STATUS_CHOICES:
            count = queryset.filter(status=status).count()
            by_status[status] = count

        # 按方向分组
        by_direction = {}
        for direction, _ in self.model.DIRECTION_CHOICES:
            count = queryset.filter(direction=direction).count()
            by_direction[direction] = count

        return {
            "total": total,
            "actionable": actionable,
            "watch": watch,
            "candidate": candidate,
            "by_status": by_status,
            "by_direction": by_direction,
        }

    def delete(self, candidate_id: str) -> bool:
        """
        删除候选（软删除）

        Args:
            candidate_id: 候选 ID

        Returns:
            是否删除成功
        """
        try:
            model = self.model.objects.get(candidate_id=candidate_id)
            model.status = CandidateStatus.CANCELLED.value
            model.save()
            logger.info(f"Alpha candidate cancelled: {candidate_id}")
            return True
        except ObjectDoesNotExist:
            return False

    def update_execution_tracking(
        self,
        candidate_id: str,
        decision_request_id: str,
        execution_status: str,
    ) -> AlphaCandidate:
        """
        更新候选的执行跟踪信息

        Args:
            candidate_id: 候选 ID
            decision_request_id: 决策请求 ID
            execution_status: 执行状态

        Returns:
            更新后的 AlphaCandidate 实体

        Raises:
            ValueError: 候选不存在
        """
        try:
            model = self.model.objects.get(candidate_id=candidate_id)
            model.last_decision_request_id = decision_request_id
            model.last_execution_status = execution_status
            model.save(update_fields=["last_decision_request_id", "last_execution_status"])

            logger.info(
                f"Alpha candidate execution tracking updated: {candidate_id} "
                f"-> request={decision_request_id}, status={execution_status}"
            )

            return model.to_domain()

        except ObjectDoesNotExist:
            raise ValueError(f"Candidate not found: {candidate_id}")


# 便捷函数

def get_trigger_repository() -> AlphaTriggerRepository:
    """获取触发器仓储实例"""
    return AlphaTriggerRepository()


def get_candidate_repository() -> AlphaCandidateRepository:
    """获取候选仓储实例"""
    return AlphaCandidateRepository()
