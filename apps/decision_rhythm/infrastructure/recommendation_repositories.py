"""
Decision Rhythm Repositories

决策频率约束和配额管理的数据仓储实现。
实现 Domain 层定义的 Repository Protocol。

这些仓储桥接 Domain 层实体和 Django ORM 模型。
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..domain.entities import (
    ApprovalStatus,
)

logger = logging.getLogger(__name__)


def _json_safe_value(value: Any) -> Any:
    """Convert nested plan snapshots into JSON-safe primitives."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return value


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

        models = ValuationSnapshotModel.objects.filter(security_code=security_code).order_by(
            "-calculated_at"
        )[:limit]

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
            model = (
                ValuationSnapshotModel.objects.filter(
                    security_code=security_code,
                    valuation_method=valuation_method,
                )
                .order_by("-calculated_at")
                .first()
            )
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
            model = InvestmentRecommendationModel.objects.get(recommendation_id=recommendation_id)
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

        query = InvestmentRecommendationModel.objects.filter(security_code=security_code)

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
            model = InvestmentRecommendationModel.objects.get(recommendation_id=recommendation_id)
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
            model = InvestmentRecommendationModel.objects.get(recommendation_id=recommendation_id)
            model.delete()
            return True
        except InvestmentRecommendationModel.DoesNotExist:
            return False


class PortfolioTransitionPlanRepository:
    """账户级调仓计划仓储。"""

    def save(self, plan) -> Any:
        from .models import PortfolioTransitionPlanModel

        model, _ = PortfolioTransitionPlanModel.objects.update_or_create(
            plan_id=plan.plan_id,
            defaults={
                "account_id": plan.account_id,
                "source_recommendation_ids": _json_safe_value(plan.source_recommendation_ids),
                "current_positions_snapshot": _json_safe_value(plan.current_positions_snapshot),
                "target_positions_snapshot": _json_safe_value(plan.target_positions_snapshot),
                "orders": _json_safe_value([order.to_dict() for order in plan.orders]),
                "risk_contract": _json_safe_value(plan.risk_contract),
                "summary": _json_safe_value(plan.summary),
                "status": plan.status.value,
                "approval_request_id": plan.approval_request_id or "",
                "as_of": plan.as_of,
            },
        )
        return model.to_domain()

    def get_by_id(self, plan_id: str) -> Any | None:
        from .models import PortfolioTransitionPlanModel

        try:
            return PortfolioTransitionPlanModel.objects.get(plan_id=plan_id).to_domain()
        except PortfolioTransitionPlanModel.DoesNotExist:
            return None

    def get_latest_for_account(self, account_id: str) -> Any | None:
        from .models import PortfolioTransitionPlanModel

        model = (
            PortfolioTransitionPlanModel.objects.filter(account_id=account_id)
            .order_by("-created_at")
            .first()
        )
        return model.to_domain() if model else None

    def update_status(
        self,
        plan_id: str,
        status_value: str,
        approval_request_id: str | None = None,
    ) -> Any | None:
        from .models import PortfolioTransitionPlanModel

        try:
            model = PortfolioTransitionPlanModel.objects.get(plan_id=plan_id)
        except PortfolioTransitionPlanModel.DoesNotExist:
            return None

        model.status = status_value
        if approval_request_id is not None:
            model.approval_request_id = approval_request_id
        model.save(update_fields=["status", "approval_request_id", "updated_at"])
        return model.to_domain()


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
        except InvestmentRecommendationModel.DoesNotExist as exc:
            raise ValueError(
                f"Investment recommendation not found: {approval_request.recommendation_id}"
            ) from exc

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
        from ..domain.entities import RecommendationStatus, TransitionPlanStatus
        from .models import ExecutionApprovalRequestModel, UnifiedRecommendationModel

        try:
            with transaction.atomic():
                model = ExecutionApprovalRequestModel.objects.select_for_update().get(
                    request_id=request_id
                )
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

                    if model.transition_plan:
                        source_ids = model.transition_plan.source_recommendation_ids or []
                        if source_ids:
                            UnifiedRecommendationModel.objects.filter(
                                recommendation_id__in=source_ids
                            ).update(status=rec_status.value)

                        plan_status_mapping = {
                            ApprovalStatus.PENDING: TransitionPlanStatus.APPROVAL_PENDING.value,
                            ApprovalStatus.APPROVED: TransitionPlanStatus.APPROVED.value,
                            ApprovalStatus.REJECTED: TransitionPlanStatus.REJECTED.value,
                            ApprovalStatus.EXECUTED: TransitionPlanStatus.EXECUTED.value,
                            ApprovalStatus.FAILED: TransitionPlanStatus.FAILED.value,
                        }
                        target_plan_status = plan_status_mapping.get(approval_status)
                        if target_plan_status:
                            model.transition_plan.status = target_plan_status
                            model.transition_plan.approval_request_id = model.request_id
                            model.transition_plan.save(
                                update_fields=["status", "approval_request_id", "updated_at"]
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

    def has_pending_request_for_plan(self, plan_id: str) -> bool:
        """检查指定交易计划是否存在待审批请求。"""
        from .models import ExecutionApprovalRequestModel

        return ExecutionApprovalRequestModel.objects.filter(
            transition_plan__plan_id=plan_id,
            approval_status=ApprovalStatus.PENDING.value,
        ).exists()

    def create_for_transition_plan(
        self,
        plan,
        *,
        account_id: str,
        risk_checks: dict[str, Any],
        regime_source: str,
        market_price,
    ) -> Any:
        """为账户级调仓计划创建审批请求。"""
        from uuid import uuid4

        from .models import ExecutionApprovalRequestModel, PortfolioTransitionPlanModel

        if self.has_pending_request_for_plan(plan.plan_id):
            raise ValueError("当前交易计划已存在待审批请求")

        plan_model = PortfolioTransitionPlanModel.objects.get(plan_id=plan.plan_id)
        active_orders = [order for order in plan.orders if order.action != "HOLD"]
        total_quantity = sum(abs(order.delta_qty) for order in active_orders) or 1
        price_lows = [order.price_band_low for order in active_orders] or [0]
        price_highs = [order.price_band_high for order in active_orders] or [0]

        approval_model = ExecutionApprovalRequestModel.objects.create(
            request_id=f"apr_{uuid4().hex[:12]}",
            transition_plan=plan_model,
            account_id=account_id,
            security_code="PLAN",
            side="HOLD",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=total_quantity,
            market_price_at_review=market_price,
            price_range_low=min(price_lows),
            price_range_high=max(price_highs),
            stop_loss_price=0,
            risk_check_results=risk_checks,
            reviewer_comments="",
            regime_source=regime_source,
            execution_params_json={
                "preview_type": "transition_plan",
                "plan_snapshot": plan.to_dict(),
            },
        )

        plan_model.status = "APPROVAL_PENDING"
        plan_model.approval_request_id = approval_model.request_id
        plan_model.save(update_fields=["status", "approval_request_id", "updated_at"])
        return approval_model.to_domain()

    def create_for_unified_recommendation(
        self,
        recommendation,
        *,
        account_id: str,
        risk_checks: dict[str, Any],
        regime_source: str,
        market_price,
    ) -> Any:
        """为统一推荐创建审批请求。"""
        from datetime import datetime
        from uuid import uuid4

        from .models import ExecutionApprovalRequestModel, UnifiedRecommendationModel

        recommendation_model = UnifiedRecommendationModel.objects.filter(
            recommendation_id=recommendation.recommendation_id
        ).first()
        if recommendation_model is None:
            raise ValueError("Unified recommendation not found")

        entry_mid = (recommendation.entry_price_low + recommendation.entry_price_high) / 2
        suggested_qty = int(recommendation.max_capital / entry_mid) if entry_mid > 0 else 0

        approval_model = ExecutionApprovalRequestModel.objects.create(
            request_id=f"apr_{uuid4().hex[:12]}",
            unified_recommendation=recommendation_model,
            transition_plan=None,
            account_id=account_id,
            security_code=recommendation.security_code,
            side=recommendation.side,
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=suggested_qty,
            market_price_at_review=market_price,
            price_range_low=recommendation.entry_price_low,
            price_range_high=recommendation.entry_price_high,
            stop_loss_price=recommendation.stop_loss_price,
            risk_check_results=risk_checks,
            reviewer_comments="",
            regime_source=regime_source,
            created_at=datetime.now(UTC),
        )
        recommendation_model.status = "REVIEWING"
        recommendation_model.save(update_fields=["status", "updated_at"])
        return approval_model.to_domain()

    def get_related_candidate_ids(self, request_id: str) -> list[str]:
        """返回审批请求关联的候选 ID 列表。"""
        from .models import ExecutionApprovalRequestModel, UnifiedRecommendationModel

        model = (
            ExecutionApprovalRequestModel.objects.select_related(
                "unified_recommendation", "transition_plan"
            )
            .filter(request_id=request_id)
            .first()
        )
        if model is None:
            return []

        candidate_ids: list[str] = []
        if model.unified_recommendation:
            candidate_ids = list(model.unified_recommendation.source_candidate_ids or [])
        elif model.transition_plan:
            source_ids = model.transition_plan.source_recommendation_ids or []
            raw_lists = UnifiedRecommendationModel.objects.filter(
                recommendation_id__in=source_ids
            ).values_list("source_candidate_ids", flat=True)
            candidate_ids = [
                str(candidate_id)
                for row in raw_lists
                for candidate_id in (row or [])
                if candidate_id
            ]
        return list(dict.fromkeys(candidate_ids))

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

        models = ExecutionApprovalRequestModel.objects.filter(regime_source=regime_source).order_by(
            "-created_at"
        )

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
