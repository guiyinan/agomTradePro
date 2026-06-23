"""Application-level query helpers for TUI/runtime consumers."""

from __future__ import annotations

from apps.decision_rhythm.application.repository_provider import (
    get_quota_repository,
    get_cooldown_repository,
    get_decision_request_repository,
)


def has_decision_quotas() -> bool:
    """Return whether quota rows exist for same-screen drilldown."""

    quota_repo = get_quota_repository()
    return bool(quota_repo.get_all_quotas())


def has_active_cooldowns() -> bool:
    """Return whether any active cooldown rows exist for operator selection."""

    cooldown_repo = get_cooldown_repository()
    return bool(cooldown_repo.get_all_active())


def has_recent_decision_requests(*, days: int = 30) -> bool:
    """Return whether the default request list can surface selectable rows."""

    request_repo = get_decision_request_repository()
    return bool(request_repo.get_recent(days=days))
