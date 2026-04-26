"""Bridge helpers for rotation account context."""

from __future__ import annotations


def list_rotation_user_accounts(user_id: int) -> list:
    """Return active simulated accounts for one user."""

    from apps.simulated_trading.application.query_services import (
        list_active_account_models_for_user,
    )

    return list_active_account_models_for_user(user_id)
