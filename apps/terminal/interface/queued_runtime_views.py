"""Dormant HTTP boundary for the reserved queued Terminal Agent routes."""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agent_runtime.application.terminal_agent_run_route_guard import (
    TerminalQueuedRuntimeUnavailable,
    reject_terminal_queued_route,
)


class TerminalQueuedRunUnavailableView(APIView):
    """Return a stable 503 without composing a queued or inline Agent run."""

    permission_classes = [IsAuthenticated]

    def _unavailable_response(self) -> Response:
        """Build the redacted response for the dormant route boundary."""

        try:
            reject_terminal_queued_route()
        except TerminalQueuedRuntimeUnavailable as exc:
            return Response(
                {
                    "error": "Queued terminal runtime is not available.",
                    "code": exc.code,
                    "reason_code": exc.reason_code,
                    "retryable": True,
                },
                status=exc.status_code,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fail closed for reserved read/status/event routes."""

        return self._unavailable_response()

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Fail closed for reserved create/cancel routes."""

        return self._unavailable_response()
