"""Shared API response helpers for decision rhythm interface views."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger(__name__)

DecoratedCallable = TypeVar("DecoratedCallable", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed drf-spectacular decorator boundary."""

    def __call__(
        self,
        **kwargs: Any,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


def bad_request_response(error: Any) -> Response:
    """Build a standardized 400 response payload."""
    return Response(
        {"success": False, "error": str(error)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def internal_error_response(message: str, error: Exception) -> Response:
    """Log an internal exception and return a non-sensitive 500 response."""

    logger.error(f"{message}: {error}", exc_info=True)
    return Response(
        {"success": False, "error": message},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
