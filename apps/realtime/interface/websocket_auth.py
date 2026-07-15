"""Authorization-header authentication for realtime WebSockets."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from channels.auth import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

from core.integration.account_access_registry import (
    get_active_access_token,
    touch_access_token,
)


def extract_formal_token(
    headers: list[tuple[bytes, bytes]],
    query_string: bytes,
) -> tuple[str | None, bool]:
    """Extract a formal ``Token`` credential and reject query credentials."""

    query = parse_qs(query_string.decode("ascii", errors="ignore"), keep_blank_values=True)
    if {"token", "access_token", "api_key"}.intersection(query):
        return None, True
    for name, value in headers:
        if name.lower() != b"authorization":
            continue
        try:
            scheme, key = value.decode("ascii").strip().split(None, 1)
        except (UnicodeDecodeError, ValueError):
            return None, False
        if scheme != "Token" or not key.strip():
            return None, False
        return key.strip(), False
    return None, False


def _authenticate_token(key: str) -> tuple[Any, bool] | None:
    """Resolve a formal Account token without exposing it beyond this boundary."""

    token = get_active_access_token(key)
    if token is None or not token.user.is_active:
        return None
    profile = getattr(token.user, "account_profile", None)
    if profile is not None and not profile.mcp_enabled:
        return None
    touch_access_token(token)
    return token.user, bool(getattr(token, "allows_write", True))


class AuthorizationHeaderAuthMiddleware(BaseMiddleware):
    """Authenticate WebSockets from a formal Account Authorization header."""

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> Any:
        token, query_rejected = extract_formal_token(
            list(scope.get("headers", [])),
            scope.get("query_string", b""),
        )
        scope["realtime_query_token_rejected"] = query_rejected
        scope["realtime_token_allows_write"] = True
        if query_rejected:
            scope["user"] = AnonymousUser()
        elif token is not None:
            result = await database_sync_to_async(_authenticate_token)(token)
            if result is None:
                scope["user"] = AnonymousUser()
            else:
                scope["user"], scope["realtime_token_allows_write"] = result
        return await super().__call__(scope, receive, send)
