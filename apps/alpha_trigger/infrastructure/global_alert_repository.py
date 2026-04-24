"""Django read model for alpha-trigger global alerts."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import AlphaCandidateModel, AlphaTriggerModel


class DjangoAlphaTriggerGlobalAlertRepository:
    """ORM-backed alpha-trigger global-alert repository."""

    def count_expiring_candidates(self, days: int) -> int:
        """Return candidate count expiring within the given number of days."""

        expiring_candidates = 0
        now = timezone.now()
        threshold = now + timedelta(days=days)
        candidates = AlphaCandidateModel._default_manager.filter(
            status__in=["WATCH", "CANDIDATE", "ACTIONABLE"]
        ).only("created_at", "time_horizon")
        for candidate in candidates:
            if not candidate.created_at or not candidate.time_horizon:
                continue
            expires_at = candidate.created_at + timedelta(days=int(candidate.time_horizon))
            if now < expires_at <= threshold:
                expiring_candidates += 1
        return expiring_candidates

    def count_expiring_triggers(self, days: int) -> int:
        """Return active trigger count expiring within the given number of days."""

        now = timezone.now()
        trigger_threshold = now + timedelta(days=days)
        return AlphaTriggerModel._default_manager.filter(
            status="ACTIVE",
            expires_at__lte=trigger_threshold,
            expires_at__gt=now,
        ).count()

    def count_actionable_candidates(self) -> int:
        """Return actionable candidate count."""

        return AlphaCandidateModel._default_manager.filter(status="ACTIONABLE").count()

    def get_workspace_summary(self) -> dict[str, object]:
        """Return decision workspace alpha-trigger summary."""

        actionable_candidates = list(
            AlphaCandidateModel._default_manager.filter(status="ACTIONABLE").order_by(
                "-confidence", "-created_at"
            )[:50]
        )
        return {
            "alpha_trigger_count": AlphaTriggerModel._default_manager.filter(
                status="ACTIVE"
            ).count(),
            "alpha_watch_count": AlphaCandidateModel._default_manager.filter(
                status="WATCH"
            ).count(),
            "alpha_candidate_count": AlphaCandidateModel._default_manager.filter(
                status="CANDIDATE"
            ).count(),
            "alpha_actionable_count": AlphaCandidateModel._default_manager.filter(
                status="ACTIONABLE"
            ).count(),
            "actionable_candidates": actionable_candidates,
        }
