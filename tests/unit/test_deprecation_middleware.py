"""
Unit tests for DeprecationHeaderMiddleware.
"""

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware.deprecation import DeprecationHeaderMiddleware


class TestDeprecationHeaderMiddleware:
    """Test the deprecation header middleware."""

    @pytest.fixture
    def factory(self):
        """Create a request factory."""
        return RequestFactory()

    @pytest.fixture
    def get_response(self):
        """Mock get_response function."""
        def mock_response(request):
            return HttpResponse()
        return mock_response

    @pytest.fixture
    def middleware(self, get_response):
        """Create middleware instance."""
        return DeprecationHeaderMiddleware(get_response)

    def test_old_route_adds_deprecation_headers(
        self, middleware, factory
    ):
        """Test that old route pattern adds deprecation headers."""
        request = factory.get('/account/api/positions/')
        response = middleware(request)

        assert response['X-Deprecated'] == 'true'
        assert 'deprecated' in response['X-Deprecation-Message'].lower()
        assert '/api/account/positions/' in response['X-Deprecation-Message']
        assert response['X-Sunset'] == '2026-06-01'

    def test_new_route_does_not_add_deprecation_headers(
        self, middleware, factory
    ):
        """Test that new route pattern does not add deprecation headers."""
        request = factory.get('/api/account/positions/')
        response = middleware(request)

        assert 'X-Deprecated' not in response
        assert 'X-Deprecation-Message' not in response
        assert 'X-Sunset' not in response

    def test_multiple_old_routes_get_headers(self, middleware, factory):
        """Test that various old route patterns get deprecation headers."""
        old_routes = [
            '/account/api/positions/',
            '/regime/api/states/',
            '/signal/api/signals/',
            '/backtest/api/results/',
            '/audit/api/operations/',
            '/simulated_trading/api/orders/',
        ]

        for route in old_routes:
            request = factory.get(route)
            response = middleware(request)

            assert response['X-Deprecated'] == 'true'
            assert response['X-Sunset'] == '2026-06-01'

    def test_non_api_routes_unchanged(self, middleware, factory):
        """Test that non-API routes are not affected."""
        non_api_routes = [
            '/dashboard/',
            '/admin/',
            '/account/login/',
            '/static/css/main.css',
        ]

        for route in non_api_routes:
            request = factory.get(route)
            response = middleware(request)

            assert 'X-Deprecated' not in response

    def test_deprecation_message_contains_new_path(
        self, middleware, factory
    ):
        """Test that deprecation message includes the correct new path."""
        test_cases = [
            ('/account/api/positions/', '/api/account/positions/'),
            ('/regime/api/states/', '/api/regime/states/'),
            ('/signal/api/signals/', '/api/signal/signals/'),
            ('/beta_gate/api/checks/', '/api/beta_gate/checks/'),
        ]

        for old_path, expected_new_path in test_cases:
            request = factory.get(old_path)
            response = middleware(request)

            assert expected_new_path in response['X-Deprecation-Message']

    def test_get_new_path_conversion(self, middleware):
        """Test the _get_new_path method directly."""
        test_cases = [
            ('/account/api/positions/', '/api/account/positions/'),
            ('/regime/api/states/123/', '/api/regime/states/123/'),
            ('/simulated_trading/api/orders/', '/api/simulated_trading/orders/'),
        ]

        for old_path, expected_new_path in test_cases:
            result = middleware._get_new_path(old_path)
            assert result == expected_new_path

    def test_link_header_added(self, middleware, factory):
        """Test that Link header is added for RFC 8284 compliance."""
        request = factory.get('/account/api/positions/')
        response = middleware(request)

        assert 'Link' in response
        assert '/api/account/positions/' in response['Link']
        assert 'rel="alternate"' in response['Link']

    def test_post_request_also_gets_headers(self, middleware, factory):
        """Test that POST requests to old routes also get headers."""
        request = factory.post('/account/api/positions/')
        response = middleware(request)

        assert response['X-Deprecated'] == 'true'

    def test_query_params_preserved_in_new_path(self, middleware, factory):
        """Test that query parameters are not part of path conversion."""
        # Query params should not be in the path conversion (they stay on request)
        request = factory.get('/account/api/positions/?limit=10')
        response = middleware(request)

        # The message should only reference the path, not query params
        assert '/api/account/positions/' in response['X-Deprecation-Message']
        # Query params should not be in the suggested new path in header
        assert '?limit=10' not in response['X-Deprecation-Message']

    def test_uppercase_module_not_matched(self, middleware, factory):
        """Test that uppercase module names are not matched (pattern is lowercase only)."""
        request = factory.get('/Account/api/positions/')
        response = middleware(request)

        # Should not match since pattern is [a-z_]+ only
        assert 'X-Deprecated' not in response


class TestDeprecationHeaderMiddlewarePatterns:
    """Test the regex patterns used by the middleware."""

    def test_pattern_matches_correct_routes(self):
        """Verify the regex pattern matches expected routes."""
        from core.middleware.deprecation import DeprecationHeaderMiddleware

        pattern = DeprecationHeaderMiddleware.DEPRECATED_PATTERNS[0]

        # Should match
        assert pattern.match('/account/api/positions/')
        assert pattern.match('/regime/api/states/')
        assert pattern.match('/simulated_trading/api/orders/')
        assert pattern.match('/app_name/api/resource/')

        # Should not match
        assert not pattern.match('/api/account/positions/')
        assert not pattern.match('/account/positions/')
        assert not pattern.match('/dashboard/')
        assert not pattern.match('/api/')

    def test_sunset_date_is_set(self):
        """Test that SUNSET_DATE is properly configured."""
        from core.middleware.deprecation import DeprecationHeaderMiddleware

        assert DeprecationHeaderMiddleware.SUNSET_DATE == "2026-06-01"
