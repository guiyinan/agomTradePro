"""Django read model for decision-rhythm global alerts."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.decision_rhythm.application.global_alert_service import QuotaUsage
from apps.decision_rhythm.domain.entities import QuotaPeriod

from .models import CooldownPeriodModel, DecisionQuotaModel, DecisionRequestModel


class DjangoDecisionRhythmGlobalAlertRepository:
    """ORM-backed decision-rhythm global-alert repository."""

    def get_weekly_quota_usage(self) -> QuotaUsage | None:
        """Return latest weekly quota usage."""

        current_quota = (
            DecisionQuotaModel._default_manager.filter(period=QuotaPeriod.WEEKLY.value)
            .order_by("-period_start")
            .first()
        )
        if current_quota is None:
            return None

        quota_total = int(getattr(current_quota, "max_decisions", 10))
        quota_used = int(getattr(current_quota, "used_decisions", 0))
        quota_remaining = max(0, quota_total - quota_used)
        usage_percent = round(quota_used / quota_total * 100, 1) if quota_total > 0 else 0
        return {
            "quota_total": quota_total,
            "quota_used": quota_used,
            "quota_remaining": quota_remaining,
            "usage_percent": usage_percent,
        }

    def count_active_cooldowns(self, window_hours: int) -> int:
        """Return approximate active cooldown count."""

        threshold = timezone.now() - timedelta(hours=window_hours)
        return CooldownPeriodModel._default_manager.filter(
            last_decision_at__gte=threshold
        ).count()

    def count_high_priority_pending_requests(self) -> int:
        """Return pending high-priority request count."""

        return DecisionRequestModel._default_manager.filter(
            execution_status="PENDING",
            priority="high",
        ).count()

    def list_pending_execution_requests(self, limit: int) -> list[DecisionRequestModel]:
        """Return approved pending/failed execution requests."""

        return list(
            DecisionRequestModel._default_manager.filter(
                response__approved=True,
                execution_status__in=["PENDING", "FAILED"],
            ).order_by("-requested_at")[:limit]
        )
