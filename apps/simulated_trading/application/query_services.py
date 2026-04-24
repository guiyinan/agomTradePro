"""Application-level query helpers for cross-app simulated trading access."""

from __future__ import annotations

from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_position_repository,
)


def get_position_snapshots(account_id: int | str) -> list[dict]:
    """Return lightweight position snapshots for account-level planning."""
    return get_simulated_position_repository().get_position_snapshots(account_id=account_id)


def list_active_account_models_for_user(user_id: int) -> list:
    """Return active account rows for UI contexts that rely on model display helpers."""
    return get_simulated_account_repository().get_active_account_models_for_user(user_id)
