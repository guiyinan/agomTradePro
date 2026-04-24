"""Decision-rhythm data used by global alert context."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class QuotaUsage(TypedDict):
    """Weekly decision quota usage snapshot."""

    quota_total: int
    quota_used: int
    quota_remaining: int
    usage_percent: float


class DecisionRhythmGlobalAlertRepository(Protocol):
    """Read model contract for decision-rhythm global alerts."""

    def get_weekly_quota_usage(self) -> QuotaUsage | None:
        """Return latest weekly quota usage."""

    def count_active_cooldowns(self, window_hours: int) -> int:
        """Return approximate active cooldown count."""

    def count_high_priority_pending_requests(self) -> int:
        """Return pending high-priority request count."""

    def list_pending_execution_requests(self, limit: int) -> list[Any]:
        """Return approved pending/failed execution requests."""


class DecisionRhythmGlobalAlertService:
    """Application service for decision-rhythm global alerts."""

    def __init__(self, repository: DecisionRhythmGlobalAlertRepository):
        self.repository = repository

    def get_weekly_quota_usage(self) -> QuotaUsage | None:
        """Return latest weekly quota usage."""

        return self.repository.get_weekly_quota_usage()

    def count_active_cooldowns(self, window_hours: int = 72) -> int:
        """Return approximate active cooldown count."""

        return self.repository.count_active_cooldowns(window_hours)

    def count_high_priority_pending_requests(self) -> int:
        """Return pending high-priority request count."""

        return self.repository.count_high_priority_pending_requests()

    def list_pending_execution_requests(self, limit: int = 100) -> list[Any]:
        """Return approved pending/failed execution requests."""

        return self.repository.list_pending_execution_requests(limit)


_global_alert_repository: DecisionRhythmGlobalAlertRepository | None = None


def configure_decision_rhythm_global_alert_repository(
    repository: DecisionRhythmGlobalAlertRepository,
) -> None:
    """Register the decision-rhythm global-alert repository."""

    global _global_alert_repository
    _global_alert_repository = repository


def get_decision_rhythm_global_alert_service() -> DecisionRhythmGlobalAlertService:
    """Return the configured decision-rhythm global-alert service."""

    if _global_alert_repository is None:
        raise RuntimeError("Decision-rhythm global alert repository is not configured")
    return DecisionRhythmGlobalAlertService(_global_alert_repository)
