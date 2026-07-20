"""Authentication decorators for dashboard API routes."""

from collections.abc import Callable, Sequence
from typing import Any

from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)


def dashboard_api_view(
    methods: Sequence[str],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Require session, internal, or MCP/SDK token auth for a dashboard API view."""

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        protected = permission_classes([IsAuthenticated])(view_func)
        authenticated = authentication_classes(
            [MultiTokenAuthentication, TerminalInternalAuthentication, SessionAuthentication]
        )(protected)
        return api_view(list(methods))(authenticated)

    return decorator
