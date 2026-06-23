"""Application query service for the daily decision queue."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.decision_rhythm.domain.entities import (
    TodayDecisionQueueItem,
    sort_today_decision_queue_items,
)

from .repository_provider import (
    check_alpha_workspace_consistency_health,
    get_execution_approval_request_repository,
    get_portfolio_transition_plan_repository,
    get_unified_recommendation_repository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TodayDecisionQueueResult:
    """Read model returned by the daily decision queue query."""

    account_id: str
    items: list[TodayDecisionQueueItem]

    def to_dict(self) -> dict[str, Any]:
        """Return an API-safe queue payload."""

        return {
            "account_id": self.account_id,
            "items": [item.to_dict() for item in self.items],
            "total": len(self.items),
        }


class TodayDecisionQueueQueryService:
    """Build the daily decision queue from existing decision workflow records."""

    target_screen = "command-center.decision-flow"

    def execute(self, *, account_id: str = "default") -> TodayDecisionQueueResult:
        """Return actionable queue items for one account."""

        normalized_account_id = str(account_id or "default").strip() or "default"
        items: list[TodayDecisionQueueItem] = []

        recommendation_repo = get_unified_recommendation_repository()
        plan_repo = get_portfolio_transition_plan_repository()
        approval_repo = get_execution_approval_request_repository()

        conflicts = recommendation_repo.get_conflicts(normalized_account_id)
        items.extend(self._conflict_items(conflicts, normalized_account_id))

        pending_approvals = approval_repo.get_pending_requests(normalized_account_id)
        items.extend(self._approval_items(pending_approvals, normalized_account_id))

        latest_plan = plan_repo.get_latest_for_account(normalized_account_id)
        if latest_plan is not None:
            plan_item = self._plan_item(latest_plan, normalized_account_id)
            if plan_item is not None:
                items.append(plan_item)

        adopted_recommendations = recommendation_repo.get_plan_candidates(normalized_account_id)
        items.extend(self._adopted_recommendation_items(adopted_recommendations))
        items.extend(self._system_health_items(normalized_account_id))

        sorted_items = sort_today_decision_queue_items(items)
        return TodayDecisionQueueResult(
            account_id=normalized_account_id,
            items=sorted_items,
        )

    def _conflict_items(
        self,
        recommendations: list[Any],
        account_id: str,
    ) -> list[TodayDecisionQueueItem]:
        items: list[TodayDecisionQueueItem] = []
        for recommendation in recommendations:
            recommendation_id = str(getattr(recommendation, "recommendation_id", "") or "")
            security_code = str(getattr(recommendation, "security_code", "") or "")
            items.append(
                TodayDecisionQueueItem(
                    item_id=f"conflict:{recommendation_id}",
                    type="recommendation_conflict",
                    title=f"处理冲突推荐：{security_code}",
                    status="CONFLICT",
                    priority=10,
                    account_id=account_id,
                    security_code=security_code,
                    source_id=recommendation_id,
                    next_action="处理冲突",
                    target_screen=self.target_screen,
                    created_at=self._created_at(recommendation),
                )
            )
        return items

    def _approval_items(
        self,
        approvals: list[Any],
        account_id: str,
    ) -> list[TodayDecisionQueueItem]:
        items: list[TodayDecisionQueueItem] = []
        for approval in approvals:
            request_id = str(getattr(approval, "request_id", "") or "")
            plan_id = str(getattr(approval, "plan_id", "") or "")
            security_code = str(getattr(approval, "security_code", "") or "")
            source_id = plan_id or str(getattr(approval, "recommendation_id", "") or "")
            items.append(
                TodayDecisionQueueItem(
                    item_id=f"approval:{request_id}",
                    type="execution_approval_pending",
                    title=f"审批执行：{security_code or source_id}",
                    status=self._enum_value(getattr(approval, "approval_status", "")),
                    priority=15,
                    account_id=account_id,
                    security_code=security_code,
                    source_id=request_id,
                    next_action="审批执行",
                    target_screen=self.target_screen,
                    created_at=self._created_at(approval),
                )
            )
        return items

    def _plan_item(
        self,
        plan: Any,
        account_id: str,
    ) -> TodayDecisionQueueItem | None:
        plan_id = str(getattr(plan, "plan_id", "") or "")
        blocking_issues = list(getattr(plan, "blocking_issues", []) or [])
        if blocking_issues:
            return TodayDecisionQueueItem(
                item_id=f"plan_blocking:{plan_id}",
                type="transition_plan_blocking",
                title=f"补齐风控/证伪：{len(blocking_issues)} 项缺口",
                status=self._enum_value(getattr(plan, "status", "")),
                priority=20,
                account_id=account_id,
                security_code=self._plan_security_codes(plan),
                source_id=plan_id,
                next_action="补齐风控/证伪",
                target_screen=self.target_screen,
                created_at=self._created_at(plan, fallback_attr="as_of"),
            )
        if not getattr(plan, "approval_request_id", None) and getattr(
            plan,
            "can_enter_approval",
            False,
        ):
            return TodayDecisionQueueItem(
                item_id=f"plan_ready:{plan_id}",
                type="transition_plan_ready",
                title="创建执行审批：调仓计划已具备风控字段",
                status=self._enum_value(getattr(plan, "status", "")),
                priority=30,
                account_id=account_id,
                security_code=self._plan_security_codes(plan),
                source_id=plan_id,
                next_action="创建审批",
                target_screen=self.target_screen,
                created_at=self._created_at(plan, fallback_attr="as_of"),
            )
        return None

    def _adopted_recommendation_items(
        self,
        recommendations: list[Any],
    ) -> list[TodayDecisionQueueItem]:
        items: list[TodayDecisionQueueItem] = []
        for recommendation in recommendations:
            recommendation_id = str(getattr(recommendation, "recommendation_id", "") or "")
            security_code = str(getattr(recommendation, "security_code", "") or "")
            side = str(getattr(recommendation, "side", "") or "")
            items.append(
                TodayDecisionQueueItem(
                    item_id=f"adopted:{recommendation_id}",
                    type="recommendation_adopted",
                    title=f"生成计划：{security_code} {side}",
                    status=self._enum_value(getattr(recommendation, "user_action", "")),
                    priority=40,
                    account_id=str(getattr(recommendation, "account_id", "") or "default"),
                    security_code=security_code,
                    source_id=recommendation_id,
                    next_action="生成计划",
                    target_screen=self.target_screen,
                    created_at=self._created_at(recommendation, fallback_attr="updated_at"),
                )
            )
        return items

    def _created_at(self, entity: Any, *, fallback_attr: str = "created_at") -> datetime:
        value = getattr(entity, "created_at", None) or getattr(entity, fallback_attr, None)
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                return timezone.make_aware(value, timezone.get_current_timezone())
            return value
        return timezone.now()

    def _enum_value(self, value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value or "")

    def _plan_security_codes(self, plan: Any) -> str:
        codes = [
            str(getattr(order, "security_code", "") or "")
            for order in list(getattr(plan, "orders", []) or [])
            if str(getattr(order, "security_code", "") or "").strip()
        ]
        return ",".join(dict.fromkeys(codes))

    def _system_health_items(self, account_id: str) -> list[TodayDecisionQueueItem]:
        items: list[TodayDecisionQueueItem] = []
        task_health_item = self._task_health_item(account_id)
        if task_health_item is not None:
            items.append(task_health_item)
        alpha_item = self._alpha_consistency_item(account_id)
        if alpha_item is not None:
            items.append(alpha_item)
        return items

    def _task_health_item(self, account_id: str) -> TodayDecisionQueueItem | None:
        try:
            from apps.task_monitor.application.repository_provider import (
                get_celery_health_checker,
            )

            health = get_celery_health_checker().check_health()
        except Exception as exc:
            return TodayDecisionQueueItem(
                item_id="health:task_monitor",
                type="task_health",
                title="任务健康检查异常",
                status="ERROR",
                priority=50,
                account_id=account_id,
                security_code="",
                source_id="task_monitor",
                next_action=f"检查任务监控：{exc}",
                target_screen="execution.tasks",
                created_at=timezone.now(),
            )
        if bool(getattr(health, "is_healthy", False)):
            return None
        return TodayDecisionQueueItem(
            item_id="health:task_monitor",
            type="task_health",
            title="任务监控或 Celery 处于降级状态",
            status="DEGRADED",
            priority=50,
            account_id=account_id,
            security_code="",
            source_id="task_monitor",
            next_action="检查任务监控",
            target_screen="execution.tasks",
            created_at=timezone.now(),
        )

    def _alpha_consistency_item(self, account_id: str) -> TodayDecisionQueueItem | None:
        try:
            payload = check_alpha_workspace_consistency_health()
        except Exception as exc:
            payload = {"status": "error", "error": str(exc)}
        status = str(payload.get("status") or "").lower()
        if status in {"", "ok", "healthy"}:
            return None
        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        first_issue = issues[0] if issues and isinstance(issues[0], dict) else {}
        issue_message = str(first_issue.get("message") or payload.get("error") or "Alpha 一致性异常")
        return TodayDecisionQueueItem(
            item_id="health:alpha_consistency",
            type="alpha_consistency",
            title="Alpha 与工作台推荐一致性待检查",
            status=status.upper(),
            priority=55,
            account_id=account_id,
            security_code="",
            source_id="alpha_workspace_consistency",
            next_action=f"检查 Alpha 一致性：{issue_message}",
            target_screen="research.alpha",
            created_at=timezone.now(),
        )
