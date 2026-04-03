"""Shared API response helpers for decision rhythm interface views."""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def bad_request_response(error: Any) -> Response:
    """Build a standardized 400 response payload."""
    return Response(
        {"success": False, "error": str(error)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def internal_error_response(message: str, error: Exception) -> Response:
    """Build a standardized 500 response payload and log the exception."""
    logger.error(f"{message}: {error}", exc_info=True)
    return Response(
        {"success": False, "error": str(error)},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
