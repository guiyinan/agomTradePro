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

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from ..domain.entities import (
    ApprovalStatus,
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    ExecutionStatus,
    ExecutionTarget,
    QuotaPeriod,
    RecommendationSide,
)
from .models import (
    CooldownPeriodModel,
    DecisionQuotaModel,
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

    def get_quota(
        self, period: QuotaPeriod, account_id: str = "default"
    ) -> DecisionQuota | None:
        """
        获取配额

        Args:
            period: 配额周期
            account_id: 账户 ID

        Returns:
            DecisionQuota 实体或 None
        """
        try:
            model = self.model.objects.filter(
                account_id=account_id, period=period.value
            ).first()

            if model:
                return model.to_domain()
            return None

        except ObjectDoesNotExist:
            return None

    def get_all_quotas(
        self,
        period: QuotaPeriod | None = None,
        account_id: str | None = None,
    ) -> list[DecisionQuota]:
        """
        获取所有配额

        Args:
            period: 配额周期过滤（可选）
            account_id: 账户 ID 过滤（可选）

        Returns:
            DecisionQuota 实体列表
        """
        queryset = self.model.objects.all()

        if account_id:
            queryset = queryset.filter(account_id=account_id)

        if period:
            queryset = queryset.filter(period=period.value)

        models = queryset.order_by("account_id", "period")

        return [m.to_domain() for m in models]

    def save(self, quota: DecisionQuota) -> DecisionQuota:
        """
        保存配额

        Args:
            quota: DecisionQuota 实体

        Returns:
            保存后的 DecisionQuota 实体
        """
        account_id = quota.account_id or "default"
        # 按 (account_id, period) 唯一查找
        existing = self.model.objects.filter(
            account_id=account_id, period=quota.period.value
        ).first()

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

    def reset_quota(
        self, period: QuotaPeriod, account_id: str = "default"
    ) -> bool:
        """
        重置配额

        Args:
            period: 配额周期
            account_id: 账户 ID

        Returns:
            是否重置成功
        """
        try:
            updated = (
                self.model.objects
                .filter(account_id=account_id, period=period.value)
                .update(
                    used_decisions=0,
                    used_executions=0,
                )
            )

            logger.info(
                f"Reset {updated} quotas for account={account_id}, period={period.value}"
            )

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
        direction: str | None = None,
    ) -> CooldownPeriod | None:
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
        direction: str | None = None,
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

    def get_all_active(self) -> list[CooldownPeriod]:
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

    def get_by_id(self, request_id: str) -> DecisionRequest | None:
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
        asset_code: str | None = None,
    ) -> list[DecisionRequest]:
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
                existing_response.approval_reason = response.approval_reason or ""
                existing_response.scheduled_at = response.scheduled_at
                existing_response.estimated_execution_at = response.estimated_execution_at
                existing_response.rejection_reason = response.rejection_reason or ""
                existing_response.wait_until = response.wait_until
                existing_response.quota_status = response.quota_status
                existing_response.cooldown_status = response.cooldown_status or ""
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
                    approval_reason=response.approval_reason or "",
                    scheduled_at=response.scheduled_at,
                    estimated_execution_at=response.estimated_execution_at,
                    rejection_reason=response.rejection_reason or "",
                    wait_until=response.wait_until,
                    quota_status=response.quota_status,
                    cooldown_status=response.cooldown_status or "",
                    alternative_suggestions=response.alternative_suggestions,
                )

                model.full_clean()
                model.save()

                logger.info(f"Decision response created: {model.response_id}")

                return model.to_domain(request_model.to_domain())

        except ObjectDoesNotExist:
            raise ValueError(f"Request not found: {request_id}")

    def update_execution_status_to_executed(
        self,
        request_id: str,
        execution_ref: dict[str, Any] | None,
    ) -> bool:
        """更新请求执行状态为已执行。"""
        update_fields: dict[str, Any] = {
            "execution_status": ExecutionStatus.EXECUTED.value,
            "executed_at": timezone.now(),
        }
        if execution_ref is not None:
            update_fields["execution_ref"] = execution_ref

        updated = self.model.objects.filter(request_id=request_id).update(**update_fields)
        if updated:
            logger.info(
                "DecisionRequest.execution_status updated to EXECUTED: %s",
                request_id,
            )
            return True

        logger.warning(f"DecisionRequest not found: {request_id}")
        return False

    def update_execution_status_to_failed(self, request_id: str) -> bool:
        """更新请求执行状态为失败。"""
        updated = self.model.objects.filter(request_id=request_id).update(
            execution_status=ExecutionStatus.FAILED.value,
        )
        if updated:
            logger.info(
                "DecisionRequest.execution_status updated to FAILED: %s",
                request_id,
            )
            return True

        logger.warning(f"DecisionRequest not found: {request_id}")
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

    def update_execution_status(
        self,
        request_id: str,
        execution_status,
        executed_at=None,
        execution_ref=None,
    ) -> bool:
        """
        更新决策请求的执行状态

        Args:
            request_id: 请求 ID
            execution_status: 执行状态（ExecutionStatus 枚举或字符串）
            executed_at: 执行时间（可选）
            execution_ref: 执行引用（可选）

        Returns:
            是否更新成功
        """
        try:
            model = self.model.objects.get(request_id=request_id)

            # 处理执行状态
            status_value = execution_status.value if hasattr(execution_status, 'value') else str(execution_status)
            model.execution_status = status_value

            if executed_at:
                model.executed_at = executed_at

            if execution_ref:
                model.execution_ref = execution_ref

            model.save(update_fields=["execution_status", "executed_at", "execution_ref"])

            logger.info(
                f"Decision request execution status updated: {request_id} -> {status_value}"
            )

            return True

        except ObjectDoesNotExist:
            logger.warning(f"Request not found for execution update: {request_id}")
            return False

    def get_pending_for_execution(self) -> list[DecisionRequest]:
        """
        获取待执行的决策请求

        Returns:
            待执行的 DecisionRequest 实体列表
        """
        models = self.model.objects.filter(
            execution_status="PENDING"
        ).order_by("-requested_at")

        return [m.to_domain() for m in models]

    def get_by_candidate_id(self, candidate_id: str) -> DecisionRequest | None:
        """
        按候选 ID 获取最近的决策请求

        Args:
            candidate_id: 候选 ID

        Returns:
            DecisionRequest 实体或 None
        """
        try:
            model = self.model.objects.filter(
                candidate_id=candidate_id
            ).order_by("-requested_at").first()

            if model:
                return model.to_domain()
            return None

        except Exception as e:
            logger.error(f"Failed to get request by candidate_id: {e}", exc_info=True)
            return None

    def get_open_by_asset_code(self, asset_code: str) -> DecisionRequest | None:
        """
        按证券代码获取最近的待执行请求（已批准且未完成）。

        用于提交幂等控制，避免同一证券重复堆积待办请求。
        """
        try:
            model = (
                self.model.objects.filter(
                    asset_code=asset_code,
                    response__approved=True,
                    execution_status__in=["PENDING", "FAILED"],
                )
                .order_by("-requested_at")
                .first()
            )
            return model.to_domain() if model else None
        except Exception as e:
            logger.error(f"Failed to get open request by asset_code: {e}", exc_info=True)
            return None

    def get_open_by_candidate_id(self, candidate_id: str) -> DecisionRequest | None:
        """
        按候选 ID 获取最近的待执行请求（已批准且未完成）。
        """
        if not candidate_id:
            return None
        try:
            model = (
                self.model.objects.filter(
                    candidate_id=candidate_id,
                    response__approved=True,
                    execution_status__in=["PENDING", "FAILED"],
                )
                .order_by("-requested_at")
                .first()
            )
            return model.to_domain() if model else None
        except Exception as e:
            logger.error(f"Failed to get open request by candidate_id: {e}", exc_info=True)
            return None


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


# ========== 估值定价引擎仓储 ==========


class ValuationSnapshotRepository:
    """
    估值快照仓储

    提供估值快照的数据持久化操作。

    Example:
        >>> repo = ValuationSnapshotRepository()
        >>> snapshot = repo.get_by_id("vs_001")
        >>> snapshots = repo.get_latest_for_security("000001.SH", limit=5)
    """

    def save(self, snapshot) -> Any:
        """
        保存估值快照

        Args:
            snapshot: 估值快照实体

        Returns:
            保存后的实体
        """
        from .models import ValuationSnapshotModel

        model = ValuationSnapshotModel.from_domain(snapshot)
        model.save()
        return model.to_domain()

    def get_by_id(self, snapshot_id: str) -> Any | None:
        """
        根据 ID 获取估值快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            估值快照实体，不存在则返回 None
        """
        from .models import ValuationSnapshotModel

        try:
            model = ValuationSnapshotModel.objects.get(snapshot_id=snapshot_id)
            return model.to_domain()
        except ValuationSnapshotModel.DoesNotExist:
            return None

    def get_latest_for_security(
        self,
        security_code: str,
        limit: int = 5,
    ) -> list[Any]:
        """
        获取指定证券的最新估值快照

        Args:
            security_code: 证券代码
            limit: 返回数量

        Returns:
            估值快照列表（按计算时间倒序）
        """
        from .models import ValuationSnapshotModel

        models = ValuationSnapshotModel.objects.filter(
            security_code=security_code
        ).order_by("-calculated_at")[:limit]

        return [model.to_domain() for model in models]

    def get_latest_by_method(
        self,
        security_code: str,
        valuation_method: str,
    ) -> Any | None:
        """
        获取指定证券和方法的最新估值快照

        Args:
            security_code: 证券代码
            valuation_method: 估值方法

        Returns:
            估值快照实体，不存在则返回 None
        """
        from .models import ValuationSnapshotModel

        try:
            model = ValuationSnapshotModel.objects.filter(
                security_code=security_code,
                valuation_method=valuation_method,
            ).order_by("-calculated_at").first()
            return model.to_domain() if model else None
        except Exception:
            return None

    def delete_by_id(self, snapshot_id: str) -> bool:
        """
        删除估值快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            是否删除成功
        """
        from .models import ValuationSnapshotModel

        try:
            model = ValuationSnapshotModel.objects.get(snapshot_id=snapshot_id)
            model.delete()
            return True
        except ValuationSnapshotModel.DoesNotExist:
            return False


class InvestmentRecommendationRepository:
    """
    投资建议仓储

    提供投资建议的数据持久化操作。

    Example:
        >>> repo = InvestmentRecommendationRepository()
        >>> rec = repo.get_by_id("rec_001")
        >>> active_recs = repo.get_active_recommendations()
    """

    def save(self, recommendation) -> Any:
        """
        保存投资建议

        Args:
            recommendation: 投资建议实体

        Returns:
            保存后的实体
        """
        from .models import InvestmentRecommendationModel, ValuationSnapshotModel

        model = InvestmentRecommendationModel.from_domain(recommendation)

        # 处理估值快照关联
        if recommendation.valuation_snapshot_id:
            try:
                snapshot_model = ValuationSnapshotModel.objects.get(
                    snapshot_id=recommendation.valuation_snapshot_id
                )
                model.valuation_snapshot = snapshot_model
            except ValuationSnapshotModel.DoesNotExist:
                pass

        model.save()
        return model.to_domain()

    def get_by_id(self, recommendation_id: str) -> Any | None:
        """
        根据 ID 获取投资建议

        Args:
            recommendation_id: 建议 ID

        Returns:
            投资建议实体，不存在则返回 None
        """
        from .models import InvestmentRecommendationModel

        try:
            model = InvestmentRecommendationModel.objects.get(
                recommendation_id=recommendation_id
            )
            return model.to_domain()
        except InvestmentRecommendationModel.DoesNotExist:
            return None

    def get_active_recommendations(
        self,
        include_executed: bool = False,
    ) -> list[Any]:
        """
        获取活跃的投资建议

        Args:
            include_executed: 是否包含已执行的建议

        Returns:
            投资建议列表
        """
        from .models import InvestmentRecommendationModel

        query = InvestmentRecommendationModel.objects.all()

        if not include_executed:
            query = query.filter(status="ACTIVE")

        query = query.order_by("-created_at")
        return [model.to_domain() for model in query]

    def get_active_by_account(
        self,
        account_id: str,
        include_executed: bool = False,
    ) -> list[Any]:
        """
        获取指定账户的活跃建议

        Args:
            account_id: 账户 ID
            include_executed: 是否包含已执行的建议

        Returns:
            投资建议列表
        """
        from .models import InvestmentRecommendationModel

        query = InvestmentRecommendationModel.objects.filter(account_id=account_id)
        if not include_executed:
            query = query.filter(status="ACTIVE")

        query = query.order_by("-created_at")
        return [model.to_domain() for model in query]

    def get_all_active(
        self,
        include_executed: bool = False,
    ) -> list[Any]:
        """
        获取所有活跃建议

        Args:
            include_executed: 是否包含已执行的建议

        Returns:
            投资建议列表
        """
        return self.get_active_recommendations(include_executed)

    def get_by_security(
        self,
        security_code: str,
        status: str | None = None,
    ) -> list[Any]:
        """
        获取指定证券的建议

        Args:
            security_code: 证券代码
            status: 状态过滤（可选）

        Returns:
            投资建议列表
        """
        from .models import InvestmentRecommendationModel

        query = InvestmentRecommendationModel.objects.filter(
            security_code=security_code
        )

        if status:
            query = query.filter(status=status)

        query = query.order_by("-created_at")
        return [model.to_domain() for model in query]

    def update_status(
        self,
        recommendation_id: str,
        status: str,
    ) -> Any | None:
        """
        更新建议状态

        Args:
            recommendation_id: 建议 ID
            status: 新状态

        Returns:
            更新后的实体，不存在则返回 None
        """
        from .models import InvestmentRecommendationModel

        try:
            model = InvestmentRecommendationModel.objects.get(
                recommendation_id=recommendation_id
            )
            model.status = status
            model.save()
            return model.to_domain()
        except InvestmentRecommendationModel.DoesNotExist:
            return None

    def delete_by_id(self, recommendation_id: str) -> bool:
        """
        删除投资建议

        Args:
            recommendation_id: 建议 ID

        Returns:
            是否删除成功
        """
        from .models import InvestmentRecommendationModel

        try:
            model = InvestmentRecommendationModel.objects.get(
                recommendation_id=recommendation_id
            )
            model.delete()
            return True
        except InvestmentRecommendationModel.DoesNotExist:
            return False


class ExecutionApprovalRequestRepository:
    """
    执行审批请求仓储

    提供执行审批请求的数据持久化操作。

    Example:
        >>> repo = ExecutionApprovalRequestRepository()
        >>> request = repo.get_by_id("apr_001")
        >>> pending_requests = repo.get_pending_requests("account_1")
    """

    def save(self, approval_request) -> Any:
        """
        保存执行审批请求

        Args:
            approval_request: 执行审批请求实体

        Returns:
            保存后的实体
        """
        from .models import ExecutionApprovalRequestModel, InvestmentRecommendationModel

        # 获取关联的投资建议模型
        try:
            recommendation_model = InvestmentRecommendationModel.objects.get(
                recommendation_id=approval_request.recommendation_id
            )
        except InvestmentRecommendationModel.DoesNotExist:
            raise ValueError(f"Investment recommendation not found: {approval_request.recommendation_id}")

        model = ExecutionApprovalRequestModel.from_domain(approval_request, recommendation_model)
        model.save()
        return model.to_domain()

    def get_by_id(self, request_id: str) -> Any | None:
        """
        根据 ID 获取执行审批请求

        Args:
            request_id: 请求 ID

        Returns:
            执行审批请求实体，不存在则返回 None
        """
        from .models import ExecutionApprovalRequestModel

        try:
            model = ExecutionApprovalRequestModel.objects.get(request_id=request_id)
            return model.to_domain()
        except ExecutionApprovalRequestModel.DoesNotExist:
            return None

    def get_pending_requests(
        self,
        account_id: str | None = None,
    ) -> list[Any]:
        """
        获取待审批的请求

        Args:
            account_id: 账户 ID（可选，不传则获取全部）

        Returns:
            执行审批请求列表
        """
        from .models import ExecutionApprovalRequestModel

        query = ExecutionApprovalRequestModel.objects.filter(
            approval_status=ApprovalStatus.PENDING.value
        )

        if account_id:
            query = query.filter(account_id=account_id)

        query = query.order_by("-created_at")
        return [model.to_domain() for model in query]

    def get_by_account_and_security(
        self,
        account_id: str,
        security_code: str,
        side: str | None = None,
    ) -> list[Any]:
        """
        获取指定账户和证券的审批请求

        Args:
            account_id: 账户 ID
            security_code: 证券代码
            side: 方向过滤（可选）

        Returns:
            执行审批请求列表
        """
        from .models import ExecutionApprovalRequestModel

        query = ExecutionApprovalRequestModel.objects.filter(
            account_id=account_id,
            security_code=security_code,
        )

        if side:
            query = query.filter(side=side)

        query = query.order_by("-created_at")
        return [model.to_domain() for model in query]

    def get_pending_by_aggregation_key(
        self,
        account_id: str,
        security_code: str,
        side: str,
    ) -> Any | None:
        """
        获取指定聚合键的待审批请求

        用于检查唯一性约束。

        Args:
            account_id: 账户 ID
            security_code: 证券代码
            side: 方向

        Returns:
            执行审批请求实体，不存在则返回 None
        """
        from .models import ExecutionApprovalRequestModel

        try:
            model = ExecutionApprovalRequestModel.objects.filter(
                account_id=account_id,
                security_code=security_code,
                side=side,
                approval_status=ApprovalStatus.PENDING.value,
            ).first()
            return model.to_domain() if model else None
        except Exception:
            return None

    def update_status(
        self,
        request_id: str,
        approval_status: ApprovalStatus,
        reviewer_comments: str | None = None,
    ) -> Any | None:
        """
        更新审批状态并同步到关联的 UnifiedRecommendation

        Args:
            request_id: 请求 ID
            approval_status: 新状态
            reviewer_comments: 审批评论（可选）

        Returns:
            更新后的实体，不存在则返回 None
        """
        from ..domain.entities import RecommendationStatus
        from .models import ExecutionApprovalRequestModel, UnifiedRecommendationModel

        try:
            with transaction.atomic():
                model = ExecutionApprovalRequestModel.objects.select_for_update().get(request_id=request_id)
                old_status = model.approval_status
                model.approval_status = approval_status.value

                if reviewer_comments is not None:
                    model.reviewer_comments = reviewer_comments

                if approval_status in [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]:
                    model.reviewed_at = timezone.now()

                if approval_status == ApprovalStatus.EXECUTED:
                    model.executed_at = timezone.now()

                model.save()

                # 同步状态到 UnifiedRecommendation（规格 10.1.5：状态一致性）
                # ApprovalStatus -> RecommendationStatus 映射
                status_mapping = {
                    ApprovalStatus.PENDING: RecommendationStatus.REVIEWING,
                    ApprovalStatus.APPROVED: RecommendationStatus.APPROVED,
                    ApprovalStatus.REJECTED: RecommendationStatus.REJECTED,
                    ApprovalStatus.EXECUTED: RecommendationStatus.EXECUTED,
                    ApprovalStatus.FAILED: RecommendationStatus.FAILED,
                }

                if approval_status in status_mapping:
                    rec_status = status_mapping[approval_status]

                    # 更新关联的 UnifiedRecommendation 状态
                    if model.unified_recommendation:
                        uni_rec = model.unified_recommendation
                        uni_rec.status = rec_status.value
                        uni_rec.save(update_fields=["status", "updated_at"])
                        logger.info(
                            f"Synced UnifiedRecommendation {uni_rec.recommendation_id} "
                            f"status: {old_status} -> {rec_status.value}"
                        )

                    # 更新旧的 InvestmentRecommendation 状态（兼容）
                    if model.recommendation:
                        old_rec = model.recommendation
                        old_rec.status = rec_status.value
                        old_rec.save(update_fields=["status"])
                        logger.info(
                            f"Synced InvestmentRecommendation {old_rec.recommendation_id} "
                            f"status: {old_status} -> {rec_status.value}"
                        )

                return model.to_domain()
        except ExecutionApprovalRequestModel.DoesNotExist:
            return None

    def has_pending_request(
        self,
        account_id: str,
        security_code: str,
        side: str,
    ) -> bool:
        """
        检查是否存在待审批请求

        用于唯一性约束验证。

        Args:
            account_id: 账户 ID
            security_code: 证券代码
            side: 方向

        Returns:
            是否存在待审批请求
        """
        from .models import ExecutionApprovalRequestModel

        return ExecutionApprovalRequestModel.objects.filter(
            account_id=account_id,
            security_code=security_code,
            side=side,
            approval_status=ApprovalStatus.PENDING.value,
        ).exists()

    def get_by_regime_source(
        self,
        regime_source: str,
    ) -> list[Any]:
        """
        根据 Regime 来源获取审批请求

        用于 Regime 追踪。

        Args:
            regime_source: Regime 来源标识

        Returns:
            执行审批请求列表
        """
        from .models import ExecutionApprovalRequestModel

        models = ExecutionApprovalRequestModel.objects.filter(
            regime_source=regime_source
        ).order_by("-created_at")

        return [model.to_domain() for model in models]

    def get_executed_in_period(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[Any]:
        """
        获取指定时间段内已执行的请求

        用于审计和统计。

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            执行审批请求列表
        """
        from .models import ExecutionApprovalRequestModel

        models = ExecutionApprovalRequestModel.objects.filter(
            approval_status=ApprovalStatus.EXECUTED.value,
            executed_at__gte=start_date,
            executed_at__lte=end_date,
        ).order_by("-executed_at")

        return [model.to_domain() for model in models]


# ============================================================================
# 统一推荐仓储
# ============================================================================


class UnifiedRecommendationRepository:
    """
    统一推荐仓储

    管理统一推荐对象的持久化。
    """

    def save(self, recommendation) -> Any:
        """
        保存推荐

        Args:
            recommendation: UnifiedRecommendation 实体

        Returns:
            保存后的实体
        """
        from ..domain.entities import RecommendationStatus
        from .models import UnifiedRecommendationModel

        # 转换 reason_codes 和其他列表字段
        reason_codes = recommendation.reason_codes if hasattr(recommendation, "reason_codes") else []
        source_signal_ids = recommendation.source_signal_ids if hasattr(recommendation, "source_signal_ids") else []
        source_candidate_ids = recommendation.source_candidate_ids if hasattr(recommendation, "source_candidate_ids") else []

        model, created = UnifiedRecommendationModel.objects.update_or_create(
            recommendation_id=recommendation.recommendation_id,
            defaults={
                "account_id": recommendation.account_id,
                "security_code": recommendation.security_code,
                "side": recommendation.side,
                "regime": recommendation.regime,
                "regime_confidence": recommendation.regime_confidence,
                "policy_level": recommendation.policy_level,
                "beta_gate_passed": recommendation.beta_gate_passed,
                "sentiment_score": recommendation.sentiment_score,
                "flow_score": recommendation.flow_score,
                "technical_score": recommendation.technical_score,
                "fundamental_score": recommendation.fundamental_score,
                "alpha_model_score": recommendation.alpha_model_score,
                "composite_score": recommendation.composite_score,
                "confidence": recommendation.confidence,
                "reason_codes": reason_codes,
                "human_rationale": recommendation.human_rationale,
                "fair_value": recommendation.fair_value,
                "entry_price_low": recommendation.entry_price_low,
                "entry_price_high": recommendation.entry_price_high,
                "target_price_low": recommendation.target_price_low,
                "target_price_high": recommendation.target_price_high,
                "stop_loss_price": recommendation.stop_loss_price,
                "position_pct": recommendation.position_pct,
                "suggested_quantity": recommendation.suggested_quantity,
                "max_capital": recommendation.max_capital,
                "source_signal_ids": source_signal_ids,
                "source_candidate_ids": source_candidate_ids,
                "status": recommendation.status.value if hasattr(recommendation.status, "value") else str(recommendation.status),
            },
        )

        return recommendation

    def save_feature_snapshot(self, snapshot) -> Any:
        """
        保存特征快照

        Args:
            snapshot: DecisionFeatureSnapshot 实体

        Returns:
            保存后的实体
        """
        from .models import DecisionFeatureSnapshotModel

        extra_features = snapshot.extra_features if hasattr(snapshot, "extra_features") else {}

        model, created = DecisionFeatureSnapshotModel.objects.update_or_create(
            snapshot_id=snapshot.snapshot_id,
            defaults={
                "security_code": snapshot.security_code,
                "snapshot_time": snapshot.snapshot_time,
                "regime": snapshot.regime,
                "regime_confidence": snapshot.regime_confidence,
                "policy_level": snapshot.policy_level,
                "beta_gate_passed": snapshot.beta_gate_passed,
                "sentiment_score": snapshot.sentiment_score,
                "flow_score": snapshot.flow_score,
                "technical_score": snapshot.technical_score,
                "fundamental_score": snapshot.fundamental_score,
                "alpha_model_score": snapshot.alpha_model_score,
                "extra_features": extra_features,
            },
        )

        return snapshot

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[Any]:
        """
        按账户获取推荐

        Args:
            account_id: 账户 ID
            status: 状态过滤（可选）

        Returns:
            推荐列表
        """
        from .models import UnifiedRecommendationModel

        query = UnifiedRecommendationModel.objects.filter(account_id=account_id)

        if status:
            query = query.filter(status=status)

        query = query.order_by("-created_at")
        return [self._model_to_entity(model) for model in query]

    def get_conflicts(self, account_id: str) -> list[Any]:
        """
        获取冲突推荐

        Args:
            account_id: 账户 ID

        Returns:
            冲突推荐列表
        """
        from ..domain.entities import RecommendationStatus
        from .models import UnifiedRecommendationModel

        models = UnifiedRecommendationModel.objects.filter(
            account_id=account_id,
            status=RecommendationStatus.CONFLICT.value,
        ).order_by("-created_at")

        return [self._model_to_entity(model) for model in models]

    def mark_as_conflict(self, recommendation_id: str) -> None:
        """
        标记为冲突

        Args:
            recommendation_id: 推荐 ID
        """
        from ..domain.entities import RecommendationStatus
        from .models import UnifiedRecommendationModel

        UnifiedRecommendationModel.objects.filter(
            recommendation_id=recommendation_id
        ).update(status=RecommendationStatus.CONFLICT.value)

    def _model_to_entity(self, model) -> Any:
        """
        将 ORM 模型转换为实体

        Args:
            model: ORM 模型实例

        Returns:
            实体实例
        """
        from decimal import Decimal

        from ..domain.entities import (
            RecommendationStatus,
            UnifiedRecommendation,
        )

        # 解析状态
        try:
            status = RecommendationStatus(model.status)
        except ValueError:
            status = RecommendationStatus.NEW

        return UnifiedRecommendation(
            recommendation_id=model.recommendation_id,
            account_id=model.account_id,
            security_code=model.security_code,
            side=model.side,
            regime=model.regime,
            regime_confidence=model.regime_confidence,
            policy_level=model.policy_level,
            beta_gate_passed=model.beta_gate_passed,
            sentiment_score=model.sentiment_score,
            flow_score=model.flow_score,
            technical_score=model.technical_score,
            fundamental_score=model.fundamental_score,
            alpha_model_score=model.alpha_model_score,
            composite_score=model.composite_score,
            confidence=model.confidence,
            reason_codes=model.reason_codes or [],
            human_rationale=model.human_rationale,
            fair_value=Decimal(str(model.fair_value)),
            entry_price_low=Decimal(str(model.entry_price_low)),
            entry_price_high=Decimal(str(model.entry_price_high)),
            target_price_low=Decimal(str(model.target_price_low)),
            target_price_high=Decimal(str(model.target_price_high)),
            stop_loss_price=Decimal(str(model.stop_loss_price)),
            position_pct=float(model.position_pct),
            suggested_quantity=model.suggested_quantity,
            max_capital=Decimal(str(model.max_capital)),
            source_signal_ids=model.source_signal_ids or [],
            source_candidate_ids=model.source_candidate_ids or [],
            feature_snapshot_id=getattr(model, "feature_snapshot_id", ""),
            status=status,
        )


class DecisionModelParamConfigRepository:
    """
    决策模型参数仓储

    为参数 use case 提供统一的参数读写与审计能力。
    """

    def get_param(self, param_key: str, env: str):
        from .models import DecisionModelParamConfigModel

        model = (
            DecisionModelParamConfigModel.objects
            .filter(param_key=param_key, env=env)
            .order_by("-version", "-updated_at")
            .first()
        )
        return model.to_domain() if model else None

    def get_all_params(self, env: str):
        from .models import DecisionModelParamConfigModel

        models = (
            DecisionModelParamConfigModel.objects
            .filter(env=env, is_active=True)
            .order_by("param_key")
        )
        return [model.to_domain() for model in models]

    def save_param(self, config):
        from .models import DecisionModelParamConfigModel

        with transaction.atomic():
            # 同一参数键在同一环境下只允许一个激活版本
            DecisionModelParamConfigModel.objects.filter(
                param_key=config.param_key,
                env=config.env,
                is_active=True,
            ).exclude(config_id=config.config_id).update(is_active=False)

            model, _ = DecisionModelParamConfigModel.objects.update_or_create(
                config_id=config.config_id,
                defaults={
                    "param_key": config.param_key,
                    "param_value": config.param_value,
                    "param_type": config.param_type,
                    "env": config.env,
                    "version": config.version,
                    "is_active": config.is_active,
                    "description": config.description,
                    "updated_by": config.updated_by,
                    "updated_reason": config.updated_reason,
                },
            )

        return model.to_domain()

    def create_audit_log(self, log):
        from .models import DecisionModelParamAuditLogModel

        model = DecisionModelParamAuditLogModel.from_domain(log)
        model.save()
        return model.to_domain()


# 便捷函数

def get_valuation_snapshot_repository() -> ValuationSnapshotRepository:
    """获取估值快照仓储实例"""
    return ValuationSnapshotRepository()


def get_investment_recommendation_repository() -> InvestmentRecommendationRepository:
    """获取投资建议仓储实例"""
    return InvestmentRecommendationRepository()


def get_execution_approval_request_repository() -> ExecutionApprovalRequestRepository:
    """获取执行审批请求仓储实例"""
    return ExecutionApprovalRequestRepository()
