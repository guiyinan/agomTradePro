"""Alpha-trigger data used by global alert context."""

from __future__ import annotations

from typing import Any, Protocol


class AlphaTriggerGlobalAlertRepository(Protocol):
    """Read model contract for alpha-trigger global alerts."""

    def count_expiring_candidates(self, days: int) -> int:
        """Return candidate count expiring within the given number of days."""

    def count_expiring_triggers(self, days: int) -> int:
        """Return active trigger count expiring within the given number of days."""

    def count_actionable_candidates(self) -> int:
        """Return actionable candidate count."""

    def get_workspace_summary(self) -> dict[str, Any]:
        """Return decision workspace alpha-trigger summary."""


class AlphaTriggerGlobalAlertService:
    """Application service for alpha-trigger global alerts."""

    def __init__(self, repository: AlphaTriggerGlobalAlertRepository):
        self.repository = repository

    def count_expiring_candidates(self, days: int = 2) -> int:
        """Return candidate count expiring within the given number of days."""

        return self.repository.count_expiring_candidates(days)

    def count_expiring_triggers(self, days: int = 7) -> int:
        """Return active trigger count expiring within the given number of days."""

        return self.repository.count_expiring_triggers(days)

    def count_actionable_candidates(self) -> int:
        """Return actionable candidate count."""

        return self.repository.count_actionable_candidates()

    def get_workspace_summary(self) -> dict[str, Any]:
        """Return decision workspace alpha-trigger summary."""

        return self.repository.get_workspace_summary()


_global_alert_repository: AlphaTriggerGlobalAlertRepository | None = None


def configure_alpha_trigger_global_alert_repository(
    repository: AlphaTriggerGlobalAlertRepository,
) -> None:
    """Register the alpha-trigger global-alert repository."""

    global _global_alert_repository
    _global_alert_repository = repository


def get_alpha_trigger_global_alert_service() -> AlphaTriggerGlobalAlertService:
    """Return the configured alpha-trigger global-alert service."""

    if _global_alert_repository is None:
        raise RuntimeError("Alpha-trigger global alert repository is not configured")
    return AlphaTriggerGlobalAlertService(_global_alert_repository)
