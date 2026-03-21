"""
API Cache Decorators and Utilities

Provides high-performance caching decorators for API endpoints.
Supports Redis and in-memory cache with Prometheus metrics tracking.
"""

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable, Optional, List, Dict

from django.core.cache import cache
from django.http import HttpRequest
from django.conf import settings

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Internal marker for serialized DRF responses in cache.
_CACHED_RESPONSE_MARKER = "_agomtradepro_cached_response_v1"

# ============== Prometheus Metrics ==============

cache_hits_total = Counter(
    'api_cache_hits_total',
    'Total number of cache hits',
    ['endpoint', 'key_prefix']
)

cache_misses_total = Counter(
    'api_cache_misses_total',
    'Total number of cache misses',
    ['endpoint', 'key_prefix']
)

cache_errors_total = Counter(
    'api_cache_errors_total',
    'Total number of cache errors',
    ['endpoint', 'key_prefix', 'error_type']
)

cache_latency_seconds = Histogram(
    'api_cache_latency_seconds',
    'Cache operation latency',
    ['endpoint', 'operation'],  # operation: get, set, delete
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

cache_stale_total = Counter(
    'api_cache_stale_total',
    'Number of times cache was bypassed (skip_cache=True)',
    ['endpoint']
)


class CacheKeyBuilder:
    """
    Builds cache keys from request parameters.

    Uses consistent hashing to ensure keys are stable and predictable.
    """

    @staticmethod
    def build(
        prefix: str,
        request: HttpRequest,
        vary_on: Optional[List[str]] = None,
        include_user: bool = False,
    ) -> str:
        """
        Build a cache key from request parameters.

        Args:
            prefix: Cache key prefix (e.g., 'regime', 'signal')
            request: HTTP request object
            vary_on: List of query parameters to include in key
            include_user: Whether to include user ID in key

        Returns:
            Cache key string
        """
        parts = [prefix]

        # Include user if requested
        if include_user and request.user.is_authenticated:
            parts.append(f"user:{request.user.id}")

        # Include path
        path_parts = request.path.strip('/').split('/')
        if len(path_parts) > 1:
            parts.append(path_parts[-1])

        # Include query parameters
        if vary_on:
            query_values = []
            for param in sorted(vary_on):
                value = request.GET.get(param, '')
                if value:
                    query_values.append(f"{param}={value}")

            if query_values:
                query_string = '&'.join(query_values)
                # Hash long query strings to avoid key length issues
                if len(query_string) > 50:
                    query_hash = hashlib.md5(query_string.encode()).hexdigest()[:8]
                    parts.append(f"q:{query_hash}")
                else:
                    parts.append(f"q:{query_string}")

        # Build final key
        key = ':'.join(parts)

        # Ensure key doesn't exceed limits
        # Redis max key length is 512MB, but we keep it reasonable
        if len(key) > 200:
            key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
            key = f"{prefix}:hash:{key_hash}"

        return key

    @staticmethod
    def build_from_args(
        prefix: str,
        func_name: str,
        args: tuple,
        kwargs: dict,
    ) -> str:
        """
        Build a cache key from function arguments.

        Useful for caching non-view functions.
        """
        # Create a deterministic representation of arguments
        key_parts = [prefix, func_name]

        # Add positional args
        for arg in args:
            if hasattr(arg, 'id'):
                key_parts.append(f"id:{arg.id}")
            elif hasattr(arg, '__str__'):
                arg_str = str(arg)[:50]
                key_parts.append(arg_str)
            else:
                key_parts.append(type(arg).__name__)

        # Add keyword args (sorted for consistency)
        for k in sorted(kwargs.keys()):
            v = kwargs[k]
            if hasattr(v, 'id'):
                key_parts.append(f"{k}:id:{v.id}")
            else:
                v_str = str(v)[:50]
                key_parts.append(f"{k}:{v_str}")

        key = ':'.join(key_parts)

        # Hash if too long
        if len(key) > 200:
            key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
            key = f"{prefix}:hash:{key_hash}"

        return key


class cached_api:
    """
    Decorator for caching API responses.

    Usage:
        @cached_api(key_prefix='regime', ttl_seconds=900, vary_on=['as_of_date'])
        def my_view(request):
            ...

    Args:
        key_prefix: Prefix for cache keys
        ttl_seconds: Cache TTL in seconds
        vary_on: List of query parameters to vary cache key
        include_user: Include user ID in cache key
        skip_param: Query parameter name to bypass cache (default: 'force_refresh')
        cache_empty: Whether to cache empty responses
        method: HTTP method to cache (default: 'GET')
    """

    def __init__(
        self,
        key_prefix: str,
        ttl_seconds: int = 900,
        vary_on: Optional[List[str]] = None,
        include_user: bool = False,
        skip_param: str = 'force_refresh',
        cache_empty: bool = True,
        method: str = 'GET',
    ):
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.vary_on = vary_on or []
        self.include_user = include_user
        self.skip_param = skip_param
        self.cache_empty = cache_empty
        self.method = method

    def __call__(self, func: Callable) -> Callable:
        def _serialize_response_for_cache(response: Any) -> Any:
            """
            Serialize response objects for cache storage.

            DRF Response objects are converted to a plain dict envelope so cache
            backends only store serializable data while preserving status/headers.
            """
            if hasattr(response, 'data'):
                headers: Dict[str, str] = {}
                try:
                    headers = dict(response.items())
                except Exception:
                    headers = {}
                return {
                    _CACHED_RESPONSE_MARKER: True,
                    'kind': 'drf_response',
                    'data': response.data,
                    'status_code': getattr(response, 'status_code', 200),
                    'headers': headers,
                }
            return response

        def _restore_cached_response(cached_value: Any) -> Any:
            """Restore cached payload back into a DRF Response when applicable."""
            if isinstance(cached_value, dict) and cached_value.get(_CACHED_RESPONSE_MARKER):
                if cached_value.get('kind') == 'drf_response':
                    from rest_framework.response import Response

                    return Response(
                        data=cached_value.get('data'),
                        status=cached_value.get('status_code', 200),
                        headers=cached_value.get('headers') or None,
                    )
            return cached_value

        @wraps(func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            # Only cache specified method
            if request.method != self.method:
                return func(request, *args, **kwargs)

            # Check for cache bypass
            skip_cache = request.GET.get(self.skip_param) == '1'
            if skip_cache:
                cache_stale_total.labels(endpoint=self.key_prefix).inc()
                return func(request, *args, **kwargs)

            # Build cache key
            key = CacheKeyBuilder.build(
                prefix=self.key_prefix,
                request=request,
                vary_on=self.vary_on,
                include_user=self.include_user,
            )

            endpoint_name = f"{self.key_prefix}:{func.__name__}"

            # Try to get from cache
            try:
                with cache_latency_seconds.labels(endpoint=endpoint_name, operation='get').time():
                    cached_data = cache.get(key)

                if cached_data is not None:
                    cache_hits_total.labels(endpoint=endpoint_name, key_prefix=self.key_prefix).inc()
                    logger.debug(f"Cache hit: {key}")
                    return _restore_cached_response(cached_data)
            except Exception as e:
                cache_errors_total.labels(
                    endpoint=endpoint_name,
                    key_prefix=self.key_prefix,
                    error_type='get'
                ).inc()
                logger.warning(f"Cache get error for {key}: {e}")

            # Cache miss - call the function
            cache_misses_total.labels(endpoint=endpoint_name, key_prefix=self.key_prefix).inc()
            response = func(request, *args, **kwargs)

            # Don't cache if response has errors
            if hasattr(response, 'status_code'):
                if response.status_code >= 400:
                    return response

            # Don't cache empty responses if configured
            if not self.cache_empty:
                if hasattr(response, 'data'):
                    if not response.data:
                        return response
                elif hasattr(response, 'content'):
                    if not response.content:
                        return response

            # Cache the response
            try:
                with cache_latency_seconds.labels(endpoint=endpoint_name, operation='set').time():
                    cache_payload = _serialize_response_for_cache(response)
                    cache.set(key, cache_payload, timeout=self.ttl_seconds)
                logger.debug(f"Cache set: {key} (TTL={self.ttl_seconds}s)")
            except Exception as e:
                cache_errors_total.labels(
                    endpoint=endpoint_name,
                    key_prefix=self.key_prefix,
                    error_type='set'
                ).inc()
                logger.warning(f"Cache set error for {key}: {e}")

            return response

        return wrapper


class cached_function:
    """
    Decorator for caching function results (non-view functions).

    Usage:
        @cached_function(prefix='macro_series', ttl_seconds=900)
        def calculate_regime(date, indicator):
            ...
    """

    def __init__(
        self,
        prefix: str,
        ttl_seconds: int = 900,
        vary_on: Optional[List[str]] = None,
    ):
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds
        self.vary_on = vary_on or []

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from arguments
            key = CacheKeyBuilder.build_from_args(
                prefix=self.prefix,
                func_name=func.__name__,
                args=args,
                kwargs=kwargs,
            )

            # Try to get from cache
            try:
                with cache_latency_seconds.labels(endpoint=self.prefix, operation='get').time():
                    cached_data = cache.get(key)

                if cached_data is not None:
                    cache_hits_total.labels(endpoint=self.prefix, key_prefix=self.prefix).inc()
                    return cached_data
            except Exception as e:
                logger.warning(f"Cache get error for {key}: {e}")

            # Cache miss
            cache_misses_total.labels(endpoint=self.prefix, key_prefix=self.prefix).inc()
            result = func(*args, **kwargs)

            # Cache the result
            try:
                with cache_latency_seconds.labels(endpoint=self.prefix, operation='set').time():
                    cache.set(key, result, timeout=self.ttl_seconds)
            except Exception as e:
                logger.warning(f"Cache set error for {key}: {e}")

            return result

        return wrapper


def invalidate_pattern(pattern: str) -> int:
    """
    Invalidate all cache keys matching a pattern.

    Note: This is only available with Redis backend.
    For LocMemCache, this will clear all cache.

    Args:
        pattern: Redis key pattern (e.g., 'regime:*')

    Returns:
        Number of keys deleted
    """
    try:
        # Check if using Redis
        backend = settings.CACHES.get('default', {}).get('BACKEND', '')
        if 'redis' in backend.lower():
            # Use Redis SCAN to find and delete keys
            from django.core.cache.backends.redis import RedisCache
            cache_client = cache

            # Get Redis client
            if hasattr(cache, '_cache'):
                client = cache._cache
                # Use SCAN for safe iteration
                count = 0
                for key in client.scan_iter(match=pattern):
                    client.delete(key)
                    count += 1
                return count
        else:
            # For LocMemCache, we can't do pattern matching
            # Fall back to clearing all cache
            logger.warning(f"Pattern invalidation not supported for {backend}, clearing all cache")
            cache.clear()
            return -1
    except Exception as e:
        logger.error(f"Cache invalidation error: {e}")
        return 0


def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics for monitoring.

    Returns:
        Dictionary with cache backend info and stats
    """
    stats = {
        'backend': settings.CACHES.get('default', {}).get('BACKEND', 'unknown'),
        'default_timeout': cache.default_timeout,
    }

    # Add Redis-specific stats if available
    try:
        backend = settings.CACHES.get('default', {}).get('BACKEND', '')
        if 'redis' in backend.lower():
            stats['type'] = 'redis'
            stats['location'] = settings.CACHES['default'].get('LOCATION', '')
    except Exception:
        pass

    return stats


# ============== Cache Configuration ==============

# TTL presets for different data types
CACHE_TTL = {
    # Real-time data (short TTL)
    'realtime_price': 30,          # 30 seconds
    'realtime_health': 60,         # 1 minute

    # Near real-time (medium TTL)
    'regime_current': 300,         # 5 minutes
    'regime_history': 900,         # 15 minutes
    'signal_list': 300,            # 5 minutes
    'signal_detail': 600,          # 10 minutes

    # Reference data (long TTL)
    'indicator_list': 3600,        # 1 hour
    'asset_info': 1800,            # 30 minutes
    'sector_list': 3600,           # 1 hour

    # Computed results (medium-long TTL)
    'dashboard_summary': 180,      # 3 minutes
    'allocation_advice': 600,      # 10 minutes
    'backtest_result': 3600,       # 1 hour (results don't change)

    # External data (long TTL to reduce API calls)
    'macro_series': 900,           # 15 minutes
    'economic_calendar': 3600,     # 1 hour
}
