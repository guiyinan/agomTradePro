"""Bridge helpers for cross-app user lookup."""

from __future__ import annotations

from apps.account.application.interface_services import find_user_by_id as find_account_user_by_id


def find_user_by_id(user_id: int):
    """Return one user by id when it exists."""

    return find_account_user_by_id(user_id)
