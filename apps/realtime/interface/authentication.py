"""Realtime-local authentication backed by the Account access registry."""

from __future__ import annotations

from typing import Any

from rest_framework import authentication, exceptions
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request

from core.integration.account_access_registry import (
    get_active_access_token,
    touch_access_token,
)


class RealtimeTokenAuthentication(authentication.TokenAuthentication):
    """Authenticate formal tokens without importing the Account app."""

    keyword = "Token"

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        """Authenticate a request and enforce write capability."""

        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result
        if request.method not in SAFE_METHODS and not getattr(token, "allows_write", True):
            raise exceptions.PermissionDenied(
                "This token is read-only and cannot perform write operations."
            )
        return user, token

    def authenticate_credentials(self, key: str) -> tuple[Any, Any]:
        """Resolve and validate an active formal access token."""

        token = get_active_access_token(key)
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid token.")

        user = token.user
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        profile = getattr(user, "account_profile", None)
        if profile is not None and not profile.mcp_enabled:
            raise exceptions.AuthenticationFailed("MCP access disabled.")

        touch_access_token(token)
        return user, token


__all__ = ["RealtimeTokenAuthentication"]
