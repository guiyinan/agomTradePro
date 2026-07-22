"""Read-only operational-readiness facade for live broker execution."""

from __future__ import annotations

from typing import Any

from .repository_provider import get_broker_execution_repository


def get_broker_execution_readiness_evidence(
    *, user_id: int, account_id: int
) -> dict[str, Any]:
    """Return account-scoped broker readiness without exposing ORM models."""

    return get_broker_execution_repository().get_account_readiness_evidence(
        user_id=user_id,
        account_id=account_id,
    )
