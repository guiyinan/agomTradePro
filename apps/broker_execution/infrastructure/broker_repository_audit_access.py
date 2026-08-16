"""Read projections for broker audit, reconciliation, and grant views."""

from __future__ import annotations

from typing import Any, TypeVar

from django.db.models import Model, QuerySet

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountAccessModel,
    BrokerExecutionAuditModel,
    ReconciliationRunModel,
)

ModelT = TypeVar("ModelT", bound=Model)


class BrokerExecutionAuditAccessMixin(BrokerExecutionRepositoryMixinSupport):
    """Expose scoped read projections owned by the access repository."""

    def _user_scope(
        self,
        queryset: QuerySet[ModelT],
        *,
        user_id: int,
        is_admin: bool,
    ) -> QuerySet[ModelT]:
        """Return a user-scoped queryset supplied by the composing access mixin."""

        raise NotImplementedError

    def list_account_access_grants(self, *, actor_id: int) -> list[dict[str, Any]]:
        """Return account grants for the already-authorized administrator."""

        del actor_id
        return [
            {
                "id": grant.pk,
                "user_id": grant.user_id,
                "username": grant.user.username,
                "account_id": grant.account_id,
                "can_approve": grant.can_approve,
                "can_trade": grant.can_trade,
                "is_active": grant.is_active,
                "granted_by": (grant.granted_by.username if grant.granted_by is not None else None),
                "updated_at": grant.updated_at.isoformat(),
            }
            for grant in BrokerAccountAccessModel._default_manager.select_related(
                "user", "granted_by"
            ).order_by("account_id", "user__username")
        ]

    def list_reconciliations(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return scoped reconciliation runs and their bounded differences."""

        queryset = self._user_scope(
            ReconciliationRunModel._default_manager.prefetch_related("differences"),
            user_id=user_id,
            is_admin=is_admin,
        )
        return [
            {
                "id": run.id,
                "account_id": run.account_id,
                "status": run.status,
                "order_difference_count": run.order_difference_count,
                "fill_difference_count": run.fill_difference_count,
                "cash_difference_count": run.cash_difference_count,
                "position_difference_count": run.position_difference_count,
                "summary": run.summary or {},
                "differences": [
                    {
                        "dimension": item.dimension,
                        "difference_key": item.difference_key,
                        "severity": item.severity,
                        "expected": item.expected or {},
                        "actual": item.actual or {},
                        "reason": item.reason,
                        "status": item.status,
                    }
                    for item in run.differences.all()
                ],
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run in queryset[: max(1, min(int(limit), 200))]
        ]

    def list_audits(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return scoped execution audit events."""

        queryset = self._user_scope(
            BrokerExecutionAuditModel._default_manager.select_related("actor"),
            user_id=user_id,
            is_admin=is_admin,
        )
        return [
            {
                "id": event.id,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "actor_username": event.actor.username if event.actor else "",
                "action": event.action,
                "account_id": event.account_id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "before": event.before or {},
                "after": event.after or {},
                "reason": event.reason,
                "request_id": event.request_id,
                "created_at": event.created_at.isoformat(),
            }
            for event in queryset[: max(1, min(int(limit), 200))]
        ]
