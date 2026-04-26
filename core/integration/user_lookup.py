"""Bridge helpers for cross-app user lookup."""

from __future__ import annotations

from django.contrib.auth import get_user_model


def find_user_by_id(user_id: int):
    """Return one user by id when it exists."""

    user_model = get_user_model()
    return user_model._default_manager.filter(id=user_id).first()
