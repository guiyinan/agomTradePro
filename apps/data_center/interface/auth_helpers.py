"""Authentication helpers for data-center HTTP endpoints."""

from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request

def _authenticated_user_id(request: Request) -> int:
    """Return a persisted integer user ID or reject the request."""

    user_id = request.user.id
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise NotAuthenticated("Authenticated user identity is unavailable.")
    return user_id
