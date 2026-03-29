"""Application-level query helpers for cross-app simulated trading access."""

from __future__ import annotations

from apps.simulated_trading.infrastructure.repositories import DjangoPositionRepository


def get_position_snapshots(account_id: int | str) -> list[dict]:
    """Return lightweight position snapshots for account-level planning."""
    return DjangoPositionRepository().get_position_snapshots(account_id=account_id)
