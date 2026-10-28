"""Application-level query helpers for cross-app alpha-trigger access."""

from __future__ import annotations

from typing import Any

from apps.alpha_trigger.application.repository_provider import (
    get_alpha_candidate_repository,
    get_alpha_trigger_repository,
)
from apps.alpha_trigger.domain.entities import AlphaCandidate, CandidateStatus


def get_open_candidates_by_asset(asset_code: str) -> list[AlphaCandidate]:
    """Return unexpired, non-terminal candidates in repository priority order.

    This lifecycle filter does not verify market-source freshness or execution readiness.
    """

    candidates = get_alpha_candidate_repository().get_by_asset(asset_code)
    return [
        candidate
        for candidate in candidates
        if not candidate.is_expired
        and not candidate.is_executed
        and candidate.status_value != CandidateStatus.CANCELLED.value
    ]


def get_candidate_generation_context(*, limit: int = 50) -> dict[str, Any]:
    """Return trigger/candidate context for downstream candidate generation flows."""

    trigger_repo = get_alpha_trigger_repository()
    candidate_repo = get_alpha_candidate_repository()
    active_triggers = trigger_repo.list_models_by_statuses(["ACTIVE", "TRIGGERED"], limit=limit)
    trigger_ids = [trigger.trigger_id for trigger in active_triggers]

    existing_candidates = candidate_repo.list_models_by_statuses(
        ["WATCH", "CANDIDATE", "ACTIONABLE"],
        limit=None,
    )

    existing_trigger_ids = {
        str(candidate.trigger_id)
        for candidate in existing_candidates
        if str(getattr(candidate, "trigger_id", "") or "") in trigger_ids
    }
    actionable_count = candidate_repo.count_by_status("ACTIONABLE")
    return {
        "active_triggers": active_triggers,
        "existing_trigger_ids": existing_trigger_ids,
        "actionable_count": actionable_count,
    }


def has_alpha_triggers() -> bool:
    """Return whether the default trigger lists can surface selectable rows."""

    trigger_repo = get_alpha_trigger_repository()
    return bool(trigger_repo.get_active())


def has_alpha_candidates() -> bool:
    """Return whether same-screen candidate selectors can surface rows."""

    candidate_repo = get_alpha_candidate_repository()
    return bool(
        candidate_repo.list_models_by_statuses(
            ["ACTIONABLE", "WATCH"],
            limit=1,
        )
    )
