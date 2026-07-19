"""Audit queue use cases for Policy.

Owner module for the human review pipeline: audit queue listing, single-item
review, bulk review, and automatic auditor assignment.
"""

import logging
from dataclasses import dataclass
from typing import Any

from ..domain.entities import AuditStatus
from .event_use_cases import RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS, AlertServiceProtocol
from .repository_provider import DjangoPolicyRepository, WorkbenchRepository

logger = logging.getLogger(__name__)

__all__ = [
    "AutoAssignAuditsUseCase",
    "BulkReviewUseCase",
    "GetAuditQueueUseCase",
    "ReviewPolicyItemInput",
    "ReviewPolicyItemOutput",
    "ReviewPolicyItemUseCase",
]


@dataclass
class ReviewPolicyItemInput:
    """审核政策条目的输入"""

    policy_log_id: int
    approved: bool
    reviewer: Any  # Django User model
    notes: str = ""
    modifications: dict[str, Any] | None = None  # 允许审核者修改AI提取的数据


@dataclass
class ReviewPolicyItemOutput:
    """审核政策条目的输出"""

    success: bool
    audit_status: AuditStatus
    message: str
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class GetAuditQueueUseCase:
    """获取审核队列用例"""

    def __init__(
        self,
        policy_repository: DjangoPolicyRepository,
        workbench_repo: WorkbenchRepository | None = None,
    ):
        """
        初始化用例

        Args:
            policy_repository: 政策仓储
        """
        self.policy_repository = policy_repository
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(
        self,
        user: Any,
        status: str = "pending_review",
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取待审核的政策列表

        Args:
            user: 当前用户
            status: 审核状态过滤
            priority: 优先级过滤
            limit: 返回数量限制

        Returns:
            List[Dict]: 待审核政策列表
        """
        return self.workbench_repo.list_audit_queue_items(
            assigned_user_id=user.id,
            status=status,
            priority=priority,
            limit=limit,
        )


class ReviewPolicyItemUseCase:
    """审核政策条目用例"""

    def __init__(
        self,
        policy_repository: DjangoPolicyRepository,
        alert_service: AlertServiceProtocol | None = None,
        workbench_repo: WorkbenchRepository | None = None,
    ):
        self.policy_repository = policy_repository
        self.alert_service = alert_service
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input: ReviewPolicyItemInput) -> ReviewPolicyItemOutput:
        """
        审核政策条目

        Args:
            input: 审核输入

        Returns:
            ReviewPolicyItemOutput: 审核结果
        """
        output = ReviewPolicyItemOutput(
            success=False, audit_status=AuditStatus.PENDING_REVIEW, message=""
        )

        try:
            review_result = self.workbench_repo.review_policy_item(
                policy_log_id=input.policy_log_id,
                approved=input.approved,
                reviewer_id=input.reviewer.id,
                notes=input.notes,
                modifications=input.modifications,
            )
            if review_result is None:
                output.errors.append(f"政策日志 {input.policy_log_id} 不存在")
                logger.error(f"Policy log {input.policy_log_id} not found")
                return output

            output.audit_status = AuditStatus(review_result["audit_status"])
            output.message = "政策已审核通过" if input.approved else "政策已拒绝"
            output.success = True

            logger.info(
                f"Policy {input.policy_log_id} "
                f"{'approved' if input.approved else 'rejected'} by {input.reviewer.username}"
            )

        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            output.errors.append(f"审核失败: {str(e)}")
            logger.error(f"Failed to review policy {input.policy_log_id}: {e}", exc_info=True)

        return output


class BulkReviewUseCase:
    """批量审核用例"""

    def __init__(self, review_use_case: ReviewPolicyItemUseCase):
        self.review_use_case = review_use_case

    def execute(
        self, policy_log_ids: list[int], approved: bool, reviewer: Any, notes: str = ""
    ) -> dict[str, Any]:
        """
        批量审核政策条目

        Args:
            policy_log_ids: 政策日志ID列表
            approved: 是否通过
            reviewer: 审核人
            notes: 审核备注

        Returns:
            Dict: 批量审核结果统计
        """
        results = {"total": len(policy_log_ids), "success": 0, "failed": 0, "errors": []}

        for policy_log_id in policy_log_ids:
            input_dto = ReviewPolicyItemInput(
                policy_log_id=policy_log_id, approved=approved, reviewer=reviewer, notes=notes
            )

            output = self.review_use_case.execute(input_dto)

            if output.success:
                results["success"] += 1
            else:
                results["failed"] += 1
                results["errors"].extend(output.errors)

        return results


class AutoAssignAuditsUseCase:
    """自动分配审核任务用例"""

    def __init__(self, workbench_repo: WorkbenchRepository | None = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, max_per_user: int = 10) -> dict[str, Any]:
        """
        自动将待审核的政策分配给审核人员

        Args:
            max_per_user: 每个用户最多分配数量

        Returns:
            Dict: 分配结果统计
        """
        from django.utils import timezone

        unassigned_ids = self.workbench_repo.list_unassigned_audit_queue_ids()
        auditor_ids = self.workbench_repo.list_staff_auditor_ids()

        if not auditor_ids:
            logger.warning("No auditors found with staff privileges")
            return {"assigned": 0, "remaining": len(unassigned_ids)}

        assignment_counts = self.workbench_repo.get_pending_assignment_counts(auditor_ids)
        assigned_count = 0
        auditor_count = len(auditor_ids)
        for idx, queue_id in enumerate(unassigned_ids):
            assigned = False
            for offset in range(auditor_count):
                auditor_id = auditor_ids[(idx + offset) % auditor_count]
                current_assigned = assignment_counts.get(auditor_id, 0)
                if current_assigned >= max_per_user:
                    continue
                if self.workbench_repo.assign_audit_queue_item(
                    queue_id=queue_id,
                    auditor_id=auditor_id,
                    assigned_at=timezone.now(),
                ):
                    assignment_counts[auditor_id] = current_assigned + 1
                    assigned_count += 1
                assigned = True
                break
            if not assigned:
                logger.debug(f"No available auditor slot for queue item {queue_id}")

        logger.info(f"Auto-assigned {assigned_count} policy reviews to {auditor_count} auditors")

        return {
            "assigned": assigned_count,
            "remaining": len(unassigned_ids) - assigned_count,
            "auditors": auditor_count,
        }
