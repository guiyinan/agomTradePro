"""HTTP deprecation metadata for the Filter API."""

from __future__ import annotations

from typing import Any, Protocol, cast

from rest_framework.request import Request
from rest_framework.response import Response

from apps.filter.application.lifecycle import (
    FILTER_DEPRECATED_SINCE,
    FILTER_REPLACEMENT_HINT,
    FILTER_SUNSET_HTTP_DATE,
)


class _ResponseFinalizer(Protocol):
    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response: ...


class FilterDeprecationHeaderMixin:
    """Attach the Filter lifecycle contract to every API response."""

    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Finalize a DRF response and add standards-oriented lifecycle headers."""

        finalizer = cast(_ResponseFinalizer, super())
        finalized = finalizer.finalize_response(request, response, *args, **kwargs)
        finalized["Deprecation"] = "true"
        finalized["Sunset"] = FILTER_SUNSET_HTTP_DATE
        finalized["X-Agom-Deprecated-Since"] = FILTER_DEPRECATED_SINCE
        finalized["X-Agom-Deprecation-Notice"] = FILTER_REPLACEMENT_HINT
        return finalized


__all__ = ["FilterDeprecationHeaderMixin"]
