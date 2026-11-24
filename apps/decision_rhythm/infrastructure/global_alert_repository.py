"""Django read model for decision-rhythm global alerts."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.decision_rhythm.application.global_alert_service import QuotaUsage
from apps.decision_rhythm.domain.entities import QuotaPeriod

from .models import CooldownPeriodModel, DecisionQuotaModel, DecisionRequestModel


class DjangoDecisionRhythmGlobalAlertRepository:
    """ORM-backed decision-rhythm global-alert repository."""

    def get_weekly_quota_usage(self, *, account_ids: list[str]) -> QuotaUsage | None:
        """Read current weekly limits for a complete authorized set of accounts."""

        accounts = set(account_ids)
        if not accounts:
            return None
        now = timezone.now()
        rows = list(
            DecisionQuotaModel._default_manager.filter(
                account_id__in=accounts,
                period=QuotaPeriod.WEEKLY.value,
                period_start__lte=now,
                period_end__gte=now,
            ).values_list("max_decisions", "used_decisions")
        )
        if len(rows) != len(accounts):
            return None
        if any(total < 0 or used < 0 or used > total for total, used in rows):
            return None
        quota_total = sum(total for total, _ in rows)
        quota_used = sum(used for _, used in rows)
        quota_remaining = quota_total - quota_used
        usage_percent = round(quota_used / quota_total * 100, 1) if quota_total else 0.0
        return {
            "quota_total": quota_total,
            "quota_used": quota_used,
            "quota_remaining": quota_remaining,
            "usage_percent": usage_percent,
        }

    def count_active_cooldowns(self, window_hours: int) -> int:
        """Return approximate active cooldown count."""

        threshold = timezone.now() - timedelta(hours=window_hours)
        return CooldownPeriodModel._default_manager.filter(last_decision_at__gte=threshold).count()

    def count_high_priority_pending_requests(self, *, account_ids: list[str]) -> int:
        """Return pending high-priority request count."""

        return DecisionRequestModel._default_manager.filter(
            execution_status="PENDING",
            priority="high",
            unified_recommendation__account_id__in=account_ids,
        ).count()

    def list_pending_execution_requests(
        self,
        limit: int,
        account_ids: list[str] | None = None,
    ) -> list[DecisionRequestModel]:
        """Return approved pending/failed requests, optionally scoped to accounts."""

        queryset = DecisionRequestModel._default_manager.filter(
            response__approved=True,
            execution_status__in=["PENDING", "FAILED"],
        ).select_related("unified_recommendation")
        if account_ids is not None:
            if not account_ids:
                return []
            queryset = queryset.filter(unified_recommendation__account_id__in=account_ids)
        return list(queryset.order_by("-requested_at")[:limit])
