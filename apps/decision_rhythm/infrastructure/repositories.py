"""
Decision Rhythm Repositories

决策频率约束和配额管理的数据仓储实现。
实现 Domain 层定义的 Repository Protocol。

这些仓储桥接 Domain 层实体和 Django ORM 模型。
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from ..domain.entities import (
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    DecisionPriority,
    QuotaPeriod,
)
from .models import (
    DecisionQuotaModel,
    CooldownPeriodModel,
    DecisionRequestModel,
    DecisionResponseModel,
)


logger = logging.getLogger(__name__)


class QuotaRepository:
    """
    配额仓储

    管理决策配额的持久化。

    Attributes:
        None（使用 Django ORM）

    Example:
        >>> repo = QuotaRepository()
        >>> quota = repo.get_quota(QuotaPeriod.WEEKLY)
    """

    def __init__(self):
        """初始化仓储"""
        self.model = DecisionQuotaModel

    def get_quota(self, period: QuotaPeriod) -> Optional[DecisionQuota]:
        """
        获取配额

        Args:
            period: 配额周期

        Returns:
            DecisionQuota 实体或 None
        """
        try:
            model = self.model.objects.filter(period=period.value).first()

            if model:
                return model.to_domain()
            return None

        except ObjectDoesNotExist:
            return None

    def get_all_quotas(self, period: Optional[QuotaPeriod] = None) -> List[DecisionQuota]:
        """
        获取所有配额

        Args:
            period: 配额周期过滤（可选）

        Returns:
            DecisionQuota 实体列表
        """
        queryset = self.model.objects.all()

        if period:
            queryset = queryset.filter(period=period.value)

        models = queryset.order_by("period")

        return [m.to_domain() for m in models]

    def save(self, quota: DecisionQuota) -> DecisionQuota:
        """
        保存配额

        Args:
            quota: DecisionQuota 实体

        Returns:
            保存后的 DecisionQuota 实体
        """
        # 检查是否已存在
        existing = self.model.objects.filter(period=quota.period.value).first()

        if existing:
            # 更新
            existing.max_decisions = quota.max_decisions
            existing.max_execution_count = quota.max_execution_count
            existing.used_decisions = quota.used_decisions
            existing.used_executions = quota.used_executions
            existing.period_start = quota.period_start
            existing.period_end = quota.period_end

            existing.full_clean()
            existing.save()

            logger.info(f"Decision quota updated: {existing.quota_id}")

            return existing.to_domain()
        else:
            # 创建
            model = DecisionQuotaModel.from_domain(quota)
            model.full_clean()
            model.save()

            logger.info(f"Decision quota created: {model.quota_id}")

            return model.to_domain()

    def reset_quota(self, period: QuotaPeriod) -> bool:
        """
        重置配额

        Args:
            period: 配额周期

        Returns:
            是否重置成功
        """
        try:
            updated = (
                self.model.objects
                .filter(period=period.value)
                .update(
                    used_decisions=0,
                    used_executions=0,
                )
            )

            logger.info(f"Reset {updated} quotas for period {period.value}")

            return updated > 0

        except Exception as e:
            logger.error(f"Failed to reset quota: {e}", exc_info=True)
            return False


class CooldownRepository:
    """
    冷却期仓储

    管理冷却期的持久化。

    Attributes:
        None（使用 Django ORM）

    Example:
        >>> repo = CooldownRepository()
        >>> cooldown = repo.get_active_cooldown("000001.SH")
    """

    def __init__(self):
        """初始化仓储"""
        self.model = CooldownPeriodModel

    def get_active_cooldown(
        self,
        asset_code: str,
        direction: Optional[str] = None,
    ) -> Optional[CooldownPeriod]:
        """
        获取活跃冷却期

        Args:
            asset_code: 资产代码
            direction: 方向过滤（可选）

        Returns:
            CooldownPeriod 实体或 None
        """
        model = self.model.objects.filter(
            asset_code=asset_code
        ).order_by("-created_at").first()

        if model:
            return model.to_domain()
        return None

    def get_remaining_hours(
        self,
        asset_code: str,
        direction: Optional[str] = None,
    ) -> float:
        """
        获取剩余冷却小时数

        Args:
            asset_code: 资产代码
            direction: 方向过滤（可选）

        Returns:
            剩余小时数（0 表示无冷却期）
        """
        cooldown = self.get_active_cooldown(asset_code, direction)

        if cooldown is None or cooldown.last_decision_at is None:
            return 0.0

        elapsed = (timezone.now() - cooldown.last_decision_at).total_seconds() / 3600
        remaining = cooldown.min_decision_interval_hours - elapsed

        return max(0.0, remaining)

    def save(self, cooldown: CooldownPeriod) -> CooldownPeriod:
        """
        保存冷却期

        Args:
            cooldown: CooldownPeriod 实体

        Returns:
            保存后的 CooldownPeriod 实体
        """
        # 检查是否已存在
        existing = self.model.objects.filter(
            asset_code=cooldown.asset_code
        ).first()

        if existing:
            # 更新
            existing.last_decision_at = cooldown.last_decision_at
            existing.last_execution_at = cooldown.last_execution_at
            existing.min_decision_interval_hours = cooldown.min_decision_interval_hours
            existing.min_execution_interval_hours = cooldown.min_execution_interval_hours
            existing.same_asset_cooldown_hours = cooldown.same_asset_cooldown_hours

            existing.full_clean()
            existing.save()

            logger.info(f"Cooldown period updated: {existing.cooldown_id}")

            return existing.to_domain()
        else:
            # 创建
            model = CooldownPeriodModel.from_domain(cooldown)
            model.full_clean()
            model.save()

            logger.info(f"Cooldown period created: {model.cooldown_id}")

            return model.to_domain()

    def get_all_active(self) -> List[CooldownPeriod]:
        """
        获取所有活跃冷却期

        Returns:
            CooldownPeriod 实体列表
        """
        models = self.model.objects.all().order_by("-created_at")

        return [m.to_domain() for m in models]


class DecisionRequestRepository:
    """
    决策请求仓储

    管理决策请求的持久化。

    Attributes:
        None（使用 Django ORM）

    Example:
        >>> repo = DecisionRequestRepository()
        >>> request = repo.get_by_id("request_001")
    """

    def __init__(self):
        """初始化仓储"""
        self.model = DecisionRequestModel
        self.response_model = DecisionResponseModel

    def get_by_id(self, request_id: str) -> Optional[DecisionRequest]:
        """
        按 ID 获取请求

        Args:
            request_id: 请求 ID

        Returns:
            DecisionRequest 实体或 None
        """
        try:
            model = self.model.objects.get(request_id=request_id)
            return model.to_domain()
        except ObjectDoesNotExist:
            return None

    def get_recent(
        self,
        days: int = 30,
        asset_code: Optional[str] = None,
    ) -> List[DecisionRequest]:
        """
        获取最近的请求

        Args:
            days: 天数范围
            asset_code: 资产代码过滤（可选）

        Returns:
            DecisionRequest 实体列表
        """
        since = timezone.now() - timedelta(days=days)
        queryset = self.model.objects.filter(requested_at__gte=since)

        if asset_code:
            queryset = queryset.filter(asset_code=asset_code)

        models = queryset.order_by("-requested_at")

        return [m.to_domain() for m in models]

    def save_request(self, request: DecisionRequest) -> DecisionRequest:
        """
        保存请求

        Args:
            request: DecisionRequest 实体

        Returns:
            保存后的 DecisionRequest 实体
        """
        # 检查是否已存在
        existing = self.model.objects.filter(
            request_id=request.request_id
        ).first()

        if existing:
            # 更新
            existing.asset_code = request.asset_code
            existing.asset_class = request.asset_class
            existing.direction = request.direction
            existing.priority = request.priority.value
            existing.trigger_id = request.trigger_id or ""
            existing.reason = request.reason
            existing.expected_confidence = request.expected_confidence
            existing.quantity = request.quantity
            existing.notional = request.notional
            existing.expires_at = request.expires_at

            existing.full_clean()
            existing.save()

            logger.info(f"Decision request updated: {existing.request_id}")

            return existing.to_domain()
        else:
            # 创建
            model = DecisionRequestModel.from_domain(request)
            model.full_clean()
            model.save()

            logger.info(f"Decision request created: {model.request_id}")

            return model.to_domain()

    def save_response(
        self,
        request_id: str,
        response: DecisionResponse,
    ) -> DecisionResponse:
        """
        保存响应

        Args:
            request_id: 请求 ID
            response: DecisionResponse 实体

        Returns:
            保存后的 DecisionResponse 实体

        Raises:
            ValueError: 请求不存在
        """
        try:
            request_model = self.model.objects.get(request_id=request_id)

            # 检查是否已存在响应
            existing_response = self.response_model.objects.filter(
                request=request_model
            ).first()

            if existing_response:
                # 更新
                existing_response.approved = response.approved
                existing_response.approval_reason = response.approval_reason
                existing_response.scheduled_at = response.scheduled_at
                existing_response.estimated_execution_at = response.estimated_execution_at
                existing_response.rejection_reason = response.rejection_reason
                existing_response.wait_until = response.wait_until
                existing_response.quota_status = response.quota_status
                existing_response.cooldown_status = response.cooldown_status
                existing_response.alternative_suggestions = response.alternative_suggestions

                existing_response.save()

                logger.info(f"Decision response updated: {existing_response.response_id}")

                return existing_response.to_domain(request_model.to_domain())
            else:
                # 创建
                response_id = f"response_{uuid.uuid4().hex[:12]}"
                model = self.response_model(
                    response_id=response_id,
                    request=request_model,
                    approved=response.approved,
                    approval_reason=response.approval_reason,
                    scheduled_at=response.scheduled_at,
                    estimated_execution_at=response.estimated_execution_at,
                    rejection_reason=response.rejection_reason,
                    wait_until=response.wait_until,
                    quota_status=response.quota_status,
                    cooldown_status=response.cooldown_status,
                    alternative_suggestions=response.alternative_suggestions,
                )

                model.full_clean()
                model.save()

                logger.info(f"Decision response created: {model.response_id}")

                return model.to_domain(request_model.to_domain())

        except ObjectDoesNotExist:
            raise ValueError(f"Request not found: {request_id}")

    def get_statistics(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取统计信息

        Args:
            days: 统计天数

        Returns:
            统计信息字典
        """
        since = timezone.now() - timedelta(days=days)
        queryset = self.model.objects.filter(requested_at__gte=since)

        total = queryset.count()

        # 按优先级分组
        by_priority = {}
        for priority in [p.value for p in DecisionPriority]:
            count = queryset.filter(priority=priority).count()
            by_priority[priority] = count

        # 按方向分组
        by_direction = {}
        for direction in ["BUY", "SELL"]:
            count = queryset.filter(direction=direction).count()
            by_direction[direction] = count

        return {
            "total": total,
            "by_priority": by_priority,
            "by_direction": by_direction,
        }


# 便捷函数

def get_quota_repository() -> QuotaRepository:
    """获取配额仓储实例"""
    return QuotaRepository()


def get_cooldown_repository() -> CooldownRepository:
    """获取冷却期仓储实例"""
    return CooldownRepository()


def get_request_repository() -> DecisionRequestRepository:
    """获取请求仓储实例"""
    return DecisionRequestRepository()
