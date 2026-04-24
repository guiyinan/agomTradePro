"""Decision Rhythm repository provider for application consumers."""

from __future__ import annotations

from apps.decision_rhythm.infrastructure.repositories import (
    DecisionRequestRepository,
    get_request_repository,
)


def get_decision_request_repository() -> DecisionRequestRepository:
    """Return the Decision Request repository."""

    return get_request_repository()
