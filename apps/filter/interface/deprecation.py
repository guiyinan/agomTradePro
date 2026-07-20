"""HTTP deprecation metadata for the Filter API."""

from __future__ import annotations

from typing import Any

from apps.filter.application.lifecycle import (
    FILTER_DEPRECATED_SINCE,
    FILTER_REPLACEMENT_HINT,
    FILTER_SUNSET_HTTP_DATE,
)


class FilterDeprecationHeaderMixin:
    """Attach the Filter lifecycle contract to every API response."""

    def finalize_response(
        self,
        request: Any,
        response: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Finalize a DRF response and add standards-oriented lifecycle headers."""

        finalized = super().finalize_response(request, response, *args, **kwargs)
        finalized["Deprecation"] = "true"
        finalized["Sunset"] = FILTER_SUNSET_HTTP_DATE
        finalized["X-Agom-Deprecated-Since"] = FILTER_DEPRECATED_SINCE
        finalized["X-Agom-Deprecation-Notice"] = FILTER_REPLACEMENT_HINT
        return finalized


__all__ = ["FilterDeprecationHeaderMixin"]
