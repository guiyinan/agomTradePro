"""
Integration tests for DeprecationHeaderMiddleware with real Django views.
"""

import pytest
from django.test import Client
from django.urls import path
from django.http import HttpResponse
from django.urls import clear_url_caches


def dummy_view(request):
    """A simple dummy view for testing."""
    return HttpResponse({'data': 'test'}, content_type='application/json')


# Test URL patterns
urlpatterns = [
    path('account/api/positions/', dummy_view, name='old-account-positions'),
    path('regime/api/states/', dummy_view, name='old-regime-states'),
    path('api/account/positions/', dummy_view, name='new-account-positions'),
    path('api/regime/states/', dummy_view, name='new-regime-states'),
]


@pytest.mark.django_db
class TestDeprecationMiddlewareIntegration:
    """Integration tests for the deprecation middleware."""

    @pytest.fixture(autouse=True)
    def setup_urls(self, settings):
        """
        Configure test URLs and restore resolver state after each test.

        Using pytest-django `settings` fixture ensures ROOT_URLCONF is reverted,
        and clearing URL caches prevents cross-test resolver contamination.
        """
        clear_url_caches()
        settings.ROOT_URLCONF = 'tests.unit.test_deprecation_integration'
        yield
        clear_url_caches()

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return Client()

    def test_old_account_api_route_has_deprecation_headers(self, client):
        """Test that old account API route has deprecation headers."""
        response = client.get('/account/api/positions/')

        assert response.status_code == 200
        assert response['X-Deprecated'] == 'true'
        assert response['X-Sunset'] == '2026-06-01'
        assert '/api/account/positions/' in response['X-Deprecation-Message']

    def test_old_regime_api_route_has_deprecation_headers(self, client):
        """Test that old regime API route has deprecation headers."""
        response = client.get('/regime/api/states/')

        assert response.status_code == 200
        assert response['X-Deprecated'] == 'true'
        assert '/api/regime/states/' in response['X-Deprecation-Message']

    def test_new_account_api_route_no_deprecation_headers(self, client):
        """Test that new account API route does not have deprecation headers."""
        response = client.get('/api/account/positions/')

        assert response.status_code == 200
        assert 'X-Deprecated' not in response

    def test_new_regime_api_route_no_deprecation_headers(self, client):
        """Test that new regime API route does not have deprecation headers."""
        response = client.get('/api/regime/states/')

        assert response.status_code == 200
        assert 'X-Deprecated' not in response
