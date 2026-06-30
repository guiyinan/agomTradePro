"""Application-level query helpers for cross-app policy access."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.policy.application.repository_provider import (
    get_current_policy_repository,
    get_policy_diagnostic_repository,
)
from apps.policy.application.use_cases import GetPolicyStatusUseCase


def get_policy_event_count() -> int:
    """Return policy event count for operational diagnostics."""

    return get_policy_diagnostic_repository().get_policy_event_count()


def get_policy_status_payload(*, as_of_date: date | None = None) -> dict[str, Any]:
    """Return current policy status in command-friendly shape."""

    status = GetPolicyStatusUseCase(
        event_store=get_current_policy_repository()
    ).execute(as_of_date)
    return {
        "current_level": status.current_level.value,
        "level_name": status.level_name,
        "is_intervention_active": status.is_intervention_active,
        "as_of_date": status.as_of_date.isoformat(),
    }


def get_recent_policy_event_summary(limit: int = 10) -> dict[str, Any]:
    """Return recent policy event summary for operational diagnostics."""

    return get_policy_diagnostic_repository().get_recent_event_summary(limit=limit)


def get_policy_rss_source_summary() -> dict[str, int]:
    """Return RSS source counts for operational diagnostics."""

    return get_policy_diagnostic_repository().get_rss_source_summary()
