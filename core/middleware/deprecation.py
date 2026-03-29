"""
Deprecation middleware for legacy route patterns.

This middleware rewrites deprecated module-scoped API paths to the canonical
system API prefix while adding deprecation headers:
- Old pattern: /{module}/api/{resource}/
- New pattern: /api/{module}/{resource}/
"""

import logging
import re
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class DeprecationHeaderMiddleware:
    """
    Rewrite legacy route patterns and add deprecation headers.

    The old route pattern (/{module}/api/{resource}/) is deprecated in favor
    of the new pattern (/api/{module}/{resource}/). This middleware adds
    appropriate headers to inform API consumers about the deprecation.

    Compatibility behavior:
    - Rewrite /{module}/api/... to /api/{module}/... before URL resolution
    - Add deprecation headers to the response

    Headers added:
    - X-Deprecated: true
    - X-Deprecation-Message: Human-readable message with migration path
    - X-Sunset: Date when the deprecated endpoints will be removed

    Example:
        For request to /account/api/positions/:
        X-Deprecated: true
        X-Deprecation-Message: This endpoint is deprecated. Use /api/account/positions/ instead.
        X-Sunset: 2026-06-01
    """

    # Match patterns like /account/api/, /regime/api/, /signal/api/ etc.
    # Pattern explanation:
    # ^/        - Start with /
    # [a-z][a-z_-]* - Lowercase module name, allowing '_' and '-'
    # /api/    - Literal /api/
    DEPRECATED_PATTERNS = [
        re.compile(r'^/[a-z][a-z_-]*/api/'),
    ]

    # Sunset date when deprecated endpoints will be removed
    SUNSET_DATE = "2026-06-01"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: The next middleware or view in the chain.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and add deprecation headers if needed.

        Args:
            request: The incoming HTTP request.

        Returns:
            The HTTP response with deprecation headers if the route matches
            the deprecated pattern.
        """
        original_path = request.path
        original_path_info = request.path_info
        is_deprecated_route = False

        for pattern in self.DEPRECATED_PATTERNS:
            if pattern.match(original_path):
                is_deprecated_route = True
                new_path = self._get_new_path(original_path)
                request.path = new_path
                request.path_info = new_path
                request.META["PATH_INFO"] = new_path
                logger.debug("Rewriting deprecated route %s -> %s", original_path, new_path)
                break

        response = self.get_response(request)

        if is_deprecated_route:
            request.path = original_path
            request.path_info = original_path_info
            request.META["PATH_INFO"] = original_path_info
            self._add_deprecation_headers(original_path, response)
            logger.debug("Added deprecation headers for legacy route: %s", original_path)

        return response

    def _add_deprecation_headers(
        self, original_path: str, response: HttpResponse
    ) -> None:
        """
        Add deprecation headers to the response.

        Args:
            original_path: The incoming deprecated request path.
            response: The HTTP response to modify.
        """
        # Mark the endpoint as deprecated
        response['X-Deprecated'] = 'true'

        # Add human-readable deprecation message with migration path
        new_path = self._get_new_path(original_path)
        response['X-Deprecation-Message'] = (
            f'This endpoint is deprecated. '
            f'Use {new_path} instead.'
        )

        # Add sunset date
        response['X-Sunset'] = self.SUNSET_DATE

        # Add Link header for RFC 8284 deprecation (optional, for compliance)
        response['Link'] = (
            f'<{new_path}>; rel="alternate"; type="application/json"'
        )

    def _get_new_path(self, old_path: str) -> str:
        """
        Convert an old path pattern to the new path pattern.

        Args:
            old_path: The old path like /account/api/positions/

        Returns:
            The new path like /api/account/positions/

        Examples:
            _get_new_path('/account/api/positions/') -> '/api/account/positions/'
            _get_new_path('/regime/api/states/') -> '/api/regime/states/'
        """
        # Find the /api/ in the old path (after module name)
        api_index = old_path.find('/api/')
        if api_index == -1:
            # Fallback: shouldn't happen given the regex pattern
            return old_path

        # Extract the module name (between / and /api/)
        module = old_path[1:api_index]

        # Construct new path: /api/{module}/rest
        new_path = f'/api/{module}{old_path[api_index + 4:]}'

        return new_path
