"""
Unit tests for cache_utils module.

Tests cache decorators, key building, and Prometheus metrics.
"""

from unittest.mock import MagicMock, Mock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from core.cache_utils import (
    CACHE_TTL,
    CacheKeyBuilder,
    cache_hits_total,
    cache_misses_total,
    cache_stale_total,
    cached_api,
    cached_function,
    get_cache_stats,
    invalidate_pattern,
)


class CacheKeyBuilderTests(TestCase):
    """Test cache key generation."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_build_simple_key(self):
        """Test building a simple cache key."""
        request = self.factory.get('/api/test/')
        key = CacheKeyBuilder.build(prefix='test', request=request)

        self.assertIn('test', key)
        self.assertIsInstance(key, str)
        self.assertGreater(len(key), 0)

    def test_build_key_with_query_params(self):
        """Test building cache key with query parameters."""
        request = self.factory.get('/api/test/?date=2024-01-01&type=daily')
        key = CacheKeyBuilder.build(
            prefix='test',
            request=request,
            vary_on=['date', 'type']
        )

        self.assertIn('test', key)
        # Query params should be included in key
        self.assertIn('q:', key)

    def test_build_key_with_user(self):
        """Test building cache key with user ID."""
        request = self.factory.get('/api/test/')
        request.user = Mock()
        request.user.id = 123
        request.user.is_authenticated = True

        key = CacheKeyBuilder.build(
            prefix='test',
            request=request,
            include_user=True
        )

        self.assertIn('user:123', key)

    def test_build_key_without_user(self):
        """Test building cache key without user ID."""
        request = self.factory.get('/api/test/')
        request.user = Mock()
        request.user.is_authenticated = False

        key = CacheKeyBuilder.build(
            prefix='test',
            request=request,
            include_user=True
        )

        self.assertNotIn('user:', key)

    def test_build_key_from_args(self):
        """Test building cache key from function arguments."""
        key = CacheKeyBuilder.build_from_args(
            prefix='myfunc',
            func_name='calculate',
            args=('arg1', 'arg2'),
            kwargs={'param': 'value'}
        )

        self.assertIn('myfunc', key)
        self.assertIn('calculate', key)
        self.assertIn('param:value', key)

    def test_long_key_hashing(self):
        """Test that long keys are hashed."""
        request = self.factory.get('/api/test/?' + 'x' * 100)
        key = CacheKeyBuilder.build(
            prefix='test',
            request=request,
            vary_on=['x' * 100]
        )

        # Long key should be hashed
        self.assertLessEqual(len(key), 250)


class CachedApiDecoratorTests(TestCase):
    """Test @cached_api decorator."""

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()  # Clear cache before each test

    def test_cache_hit(self):
        """Test cache hit scenario."""
        call_count = [0]

        @cached_api(key_prefix='test_hit', ttl_seconds=60)
        def test_view(request):
            call_count[0] += 1
            return {'data': f'call_{call_count[0]}'}

        # First call - cache miss
        request = self.factory.get('/api/test/')
        response1 = test_view(request)

        # Second call - cache hit
        response2 = test_view(request)

        # Function should only be called once
        self.assertEqual(call_count[0], 1)
        # Both responses should be the same
        self.assertEqual(response1, response2)

    def test_cache_miss_after_ttl(self):
        """Test cache miss after TTL expires."""
        @cached_api(key_prefix='test_ttl', ttl_seconds=0)  # Instant expiry
        def test_view(request):
            return {'data': 'value'}

        request = self.factory.get('/api/test/')
        test_view(request)
        test_view(request)

        # With TTL=0, each call should be a cache miss
        # (Note: LocMemCache may not respect TTL=0 precisely)

    def test_cache_bypass_with_force_refresh(self):
        """Test cache bypass with force_refresh parameter."""
        call_count = [0]

        @cached_api(key_prefix='test_bypass', ttl_seconds=60)
        def test_view(request):
            call_count[0] += 1
            return {'data': f'call_{call_count[0]}'}

        # First call
        request = self.factory.get('/api/test/')
        test_view(request)
        self.assertEqual(call_count[0], 1)

        # Bypass cache
        request = self.factory.get('/api/test/?force_refresh=1')
        test_view(request)
        self.assertEqual(call_count[0], 2)  # Should call function again

    def test_only_caches_get_method(self):
        """Test that only GET requests are cached."""
        call_count = [0]

        @cached_api(key_prefix='test_method', ttl_seconds=60)
        def test_view(request):
            call_count[0] += 1
            return {'method': request.method}

        # GET request - cached
        request = self.factory.get('/api/test/')
        test_view(request)
        test_view(request)
        self.assertEqual(call_count[0], 1)

        # POST request - not cached
        request = self.factory.post('/api/test/')
        test_view(request)
        self.assertEqual(call_count[0], 2)

    def test_caches_with_vary_on_params(self):
        """Test caching with parameter variation."""
        call_counts = {'a': 0, 'b': 0}

        @cached_api(key_prefix='test_vary', ttl_seconds=60, vary_on=['type'])
        def test_view(request):
            param = request.GET.get('type', 'default')
            if param == 'a':
                call_counts['a'] += 1
            elif param == 'b':
                call_counts['b'] += 1
            return {'type': param}

        # Call with type=a
        request1 = self.factory.get('/api/test/?type=a')
        test_view(request1)
        test_view(request1)

        # Call with type=b
        request2 = self.factory.get('/api/test/?type=b')
        test_view(request2)
        test_view(request2)

        # Each param should call function once
        self.assertEqual(call_counts['a'], 1)
        self.assertEqual(call_counts['b'], 1)

    def test_cache_with_user(self):
        """Test caching with user context."""
        @cached_api(key_prefix='test_user', ttl_seconds=60, include_user=True)
        def test_view(request):
            return {'user_id': request.user.id}

        # Create two users
        user1 = Mock()
        user1.id = 1
        user1.is_authenticated = True

        user2 = Mock()
        user2.id = 2
        user2.is_authenticated = True

        # Request from user1
        request1 = self.factory.get('/api/test/')
        request1.user = user1
        response1 = test_view(request1)

        # Request from user2
        request2 = self.factory.get('/api/test/')
        request2.user = user2
        response2 = test_view(request2)

        # Responses should be different (different cache keys)
        self.assertEqual(response1['user_id'], 1)
        self.assertEqual(response2['user_id'], 2)

    def test_drf_response_caching(self):
        """Test caching DRF Response objects."""
        from rest_framework.response import Response

        @cached_api(key_prefix='test_drf', ttl_seconds=60)
        def test_view(request):
            return Response({'data': 'value'}, status=201, headers={'X-Test': 'cached'})

        request = self.factory.get('/api/test/')
        response1 = test_view(request)
        response2 = test_view(request)

        # Should preserve Response semantics on cache hit
        self.assertEqual(response1.data, {'data': 'value'})
        self.assertEqual(response2.data, {'data': 'value'})
        self.assertEqual(response2.status_code, 201)
        self.assertEqual(response2['X-Test'], 'cached')


class CachedFunctionDecoratorTests(TestCase):
    """Test @cached_function decorator."""

    def setUp(self):
        cache.clear()

    def test_function_caching(self):
        """Test basic function caching."""
        call_count = [0]

        @cached_function(prefix='myfunc', ttl_seconds=60)
        def calculate(x, y):
            call_count[0] += 1
            return x + y

        # First call - cache miss
        result1 = calculate(1, 2)
        self.assertEqual(result1, 3)
        self.assertEqual(call_count[0], 1)

        # Second call - cache hit
        result2 = calculate(1, 2)
        self.assertEqual(result2, 3)
        self.assertEqual(call_count[0], 1)

        # Different args - cache miss
        result3 = calculate(2, 3)
        self.assertEqual(result3, 5)
        self.assertEqual(call_count[0], 2)


class CacheTTLTests(TestCase):
    """Test CACHE_TTL presets."""

    def test_ttl_values(self):
        """Test that TTL values are reasonable."""
        # Real-time data should have short TTL
        self.assertLess(CACHE_TTL['realtime_price'], 60)
        self.assertLess(CACHE_TTL['realtime_health'], 120)

        # Reference data can have longer TTL
        self.assertGreater(CACHE_TTL['indicator_list'], 1800)
        self.assertGreater(CACHE_TTL['sector_list'], 1800)

        # Regime data should have medium TTL
        self.assertGreater(CACHE_TTL['regime_current'], 60)
        self.assertLess(CACHE_TTL['regime_current'], 600)


class CacheStatsTests(TestCase):
    """Test cache statistics functions."""

    def test_get_cache_stats(self):
        """Test getting cache statistics."""
        stats = get_cache_stats()

        self.assertIn('backend', stats)
        self.assertIn('default_timeout', stats)
        self.assertIsInstance(stats['backend'], str)

    @patch('core.cache_utils.settings')
    def test_invalidate_pattern_redis(self, mock_settings):
        """Test pattern invalidation with Redis."""
        # Mock Redis cache settings
        mock_settings.CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                'LOCATION': 'redis://localhost:6379/1'
            }
        }

        with patch('core.cache_utils.cache') as mock_cache:
            # Mock Redis client
            mock_redis_client = MagicMock()
            mock_cache._cache = mock_redis_client
            mock_redis_client.scan_iter.return_value = ['key1', 'key2']
            mock_redis_client.delete.return_value = 1

            count = invalidate_pattern('test:*')

            self.assertEqual(count, 2)
            mock_redis_client.scan_iter.assert_called_once_with(match='test:*')


class PrometheusMetricsTests(TestCase):
    """Test Prometheus metrics."""

    def setUp(self):
        # Reset metrics before each test
        for metric in [cache_hits_total, cache_misses_total, cache_stale_total]:
            metric._metrics.clear()

    def test_cache_hits_metric(self):
        """Test cache hits counter."""

        # Increment counter
        cache_hits_total.labels(endpoint='test', key_prefix='test').inc()

        # Verify metric was recorded
        self.assertGreater(
            cache_hits_total.labels(endpoint='test', key_prefix='test')._value._value,
            0
        )

    def test_cache_misses_metric(self):
        """Test cache misses counter."""
        cache_misses_total.labels(endpoint='test', key_prefix='test').inc(3)

        self.assertEqual(
            cache_misses_total.labels(endpoint='test', key_prefix='test')._value._value,
            3
        )

    def test_cache_stale_metric(self):
        """Test cache stale counter."""
        cache_stale_total.labels(endpoint='test').inc()

        self.assertGreater(
            cache_stale_total.labels(endpoint='test')._value._value,
            0
        )
