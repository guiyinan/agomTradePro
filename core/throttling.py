"""
AgomSAAF Custom Throttling Classes

Provides specialized rate limiting for expensive operations like backtests
and write operations, separating them from regular read operations.

P0-2 Implementation: Layered rate limiting for expensive operations.

IMPORTANT: These throttles only apply to specific methods, not all requests.
- BacktestRateThrottle: Only POST (create backtest)
- WriteRateThrottle: Only POST, PUT, PATCH, DELETE
- Read operations (GET, HEAD, OPTIONS) use default rate limits only
"""

from rest_framework.throttling import UserRateThrottle
import logging

logger = logging.getLogger(__name__)


class BacktestRateThrottle(UserRateThrottle):
    """
    Throttle class for expensive backtest CREATE operations.

    Default: 10 requests per hour per user.
    This is separate from the general API rate limit.

    IMPORTANT: Only applies to POST requests (backtest creation).
    GET requests (list, retrieve, statistics) are NOT throttled by this class.

    The rate can be configured via:
    - Environment: DRF_THROTTLE_BACKTEST=10/hour
    - Settings: REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['backtest']
    """

    scope = "backtest"

    def allow_request(self, request, view):
        """
        Only apply throttling to POST requests (backtest creation).

        GET, HEAD, OPTIONS requests pass through without backtest throttling.
        """
        # Only throttle POST requests (backtest creation)
        # GET (list/retrieve/statistics) should NOT be throttled by backtest limit
        if request.method != "POST":
            return True

        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"Backtest rate limit exceeded for user {request.user.id}",
                extra={
                    "user_id": request.user.id,
                    "scope": self.scope,
                    "method": request.method,
                    "view": view.__class__.__name__,
                }
            )

        return allowed


class WriteRateThrottle(UserRateThrottle):
    """
    Throttle class for write operations (POST, PUT, PATCH, DELETE).

    Default: 100 requests per hour per user.
    This prevents abuse of data-modifying endpoints.

    IMPORTANT: Only applies to write methods.
    GET, HEAD, OPTIONS requests pass through without write throttling.

    The rate can be configured via:
    - Environment: DRF_THROTTLE_WRITE=100/hour
    - Settings: REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['write']
    """

    scope = "write"

    def allow_request(self, request, view):
        """
        Only apply throttling to write methods.
        """
        # Only throttle write methods
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return True

        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"Write rate limit exceeded for user {request.user.id}",
                extra={
                    "user_id": request.user.id,
                    "scope": self.scope,
                    "method": request.method,
                    "view": view.__class__.__name__,
                }
            )

        return allowed


class BurstRateThrottle(UserRateThrottle):
    """
    Throttle class for burst protection.

    Default: 30 requests per minute per user.
    This prevents rapid-fire API calls that could overwhelm the server.

    Useful for endpoints that trigger heavy computations.

    The rate can be configured via:
    - Settings: REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['burst']
    """

    scope = "burst"

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"Burst rate limit exceeded for user {request.user.id}",
                extra={
                    "user_id": request.user.id,
                    "scope": self.scope,
                    "view": view.__class__.__name__,
                }
            )

        return allowed


# Utility function to get client identifier for anonymous users
def get_client_ip(request):
    """
    Get the client IP address from the request.

    Handles X-Forwarded-For header for reverse proxy setups.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
