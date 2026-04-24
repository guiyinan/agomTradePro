"""Alpha Trigger repository provider for application consumers."""

from __future__ import annotations

from apps.alpha_trigger.infrastructure.repositories import (
    AlphaCandidateRepository,
    AlphaTriggerRepository,
)


def get_alpha_trigger_repository() -> AlphaTriggerRepository:
    """Return the Alpha Trigger repository."""

    return AlphaTriggerRepository()


def get_alpha_candidate_repository() -> AlphaCandidateRepository:
    """Return the Alpha Candidate repository."""

    return AlphaCandidateRepository()
