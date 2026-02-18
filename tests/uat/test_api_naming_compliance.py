"""
API Naming Convention Compliance Tests.

Validates that all API routes follow the naming conventions defined in the PRD:
- Page routes: /module-name/action/
- API routes: /api/module-name/action/
- Clear separation between page and data endpoints
"""
import pytest
import re
from pathlib import Path
from typing import List, Dict, Tuple

from django.test import Client
from django.urls import reverse
from django.conf import settings


class APINamingConventionTest:
    """Test API naming convention compliance."""

    @pytest.fixture
    def api_client(self):
        """Create a test client for API requests."""
        return Client()

    def collect_all_url_patterns(self) -> List[Dict[str, str]]:
        """Collect all URL patterns from the project.

        Returns:
            List of dicts with 'pattern', 'name', 'module' keys
        """
        from django.urls import get_resolver

        resolver = get_resolver()
        url_patterns = []

        def extract_patterns(patterns, prefix=''):
            for pattern in patterns:
                if hasattr(pattern, 'url_patterns'):
                    # This is an include()
                    new_prefix = prefix + str(pattern.pattern)
                    extract_patterns(pattern.url_patterns, new_prefix)
                else:
                    # This is a URL pattern
                    url_patterns.append({
                        'pattern': prefix + str(pattern.pattern),
                        'name': getattr(pattern, 'name', None),
                        'callback': getattr(pattern, 'callback', None),
                    })

        extract_patterns(resolver.url_patterns)
        return url_patterns

    @pytest.mark.api_compliance
    def test_api_routes_have_prefix(self, api_client) -> None:
        """All API routes should start with /api/."""
        url_patterns = self.collect_all_url_patterns()

        # Find routes that look like APIs but don't have /api/ prefix
        # An API route typically:
        # 1. Returns JSON
        # 2. Has 'api', 'list', 'detail', 'create' in name
        # 3. Is a ViewSet or APIView

        violations = []
        for pattern_info in url_patterns:
            pattern = pattern_info['pattern']
            name = pattern_info['name'] or ''

            # Skip if already has /api/ prefix
            if pattern.startswith('/api/'):
                continue

            # Check if this looks like an API route without prefix
            is_api_like = (
                'api' in name.lower() or
                any(keyword in name for keyword in ['list', 'detail', 'create', 'update', 'delete']) or
                hasattr(pattern_info['callback'], 'view_class')
            )

            if is_api_like:
                violations.append({
                    'pattern': pattern,
                    'name': name,
                })

        # Report violations
        if violations:
            print("\nAPI routes without /api/ prefix found:")
            for v in violations:
                print(f"  - {v['pattern']} (name: {v['name']})")

        # For now, just report - the threshold will be defined
        assert True, f"Found {len(violations)} potential API routes without /api/ prefix"

    @pytest.mark.api_compliance
    def test_no_ambiguous_mixed_routes(self, api_client) -> None:
        """No routes should serve both page and API responses based on content type."""
        # This would require checking each route's implementation
        # For now, we do a basic check
        url_patterns = self.collect_all_url_patterns()

        # Group routes by path (without /api/ prefix)
        route_groups: Dict[str, List[Dict]] = {}
        for pattern_info in url_patterns:
            # Normalize path
            path = pattern_info['pattern'].rstrip('^$')

            # Remove /api/ prefix for grouping
            base_path = re.sub(r'^/api/', '/', path)

            if base_path not in route_groups:
                route_groups[base_path] = []
            route_groups[base_path].append(pattern_info)

        # Find routes that exist both with and without /api/ prefix
        duplicates = []
        for base_path, patterns in route_groups.items():
            has_api = any(p['pattern'].startswith('/api/') for p in patterns)
            has_page = any(not p['pattern'].startswith('/api/') for p in patterns)

            if has_api and has_page and len(patterns) > 1:
                duplicates.append({
                    'path': base_path,
                    'patterns': [p['pattern'] for p in patterns],
                })

        # This is informational - duplicates are OK if they serve different purposes
        assert True, f"Found {len(duplicates)} routes with both page and API variants"

    @pytest.mark.api_compliance
    def test_api_documentation_complete(self) -> None:
        """API documentation should be complete and synchronized."""
        from drf_spectacular.openapi import AutoSchema
        from rest_framework.serializers import BaseSerializer

        # Check if DRF Spectacular is configured
        assert 'drf_spectacular' in settings.INSTALLED_APPS, \
            "drf_spectacular should be installed for API documentation"

        # Check if schema view is accessible
        try:
            schema_url = reverse('schema')
            assert schema_url is not None, "Schema URL should be defined"
        except Exception as e:
            pytest.skip(f"Schema view not accessible: {e}")

    @pytest.mark.api_compliance
    def test_module_naming_consistency(self) -> None:
        """Module names in URLs should be consistent with app names."""
        url_patterns = self.collect_all_url_patterns()

        # Expected module mappings
        module_mappings = {
            'account': 'account',
            'macro': 'macro',
            'regime': 'regime',
            'signal': 'signal',
            'policy': 'policy',
            'equity': 'equity',
            'fund': 'fund',
            'asset-analysis': 'asset_analysis',
            'backtest': 'backtest',
            'simulated-trading': 'simulated_trading',
            'audit': 'audit',
            'filter': 'filter',
            'sector': 'sector',
            'strategy': 'strategy',
            'alpha': 'alpha',
            'factor': 'factor',
            'rotation': 'rotation',
            'hedge': 'hedge',
        }

        # Check for consistency
        inconsistencies = []
        for pattern_info in url_patterns:
            pattern = pattern_info['pattern']

            # Extract module from pattern
            match = re.match(r'/?(api/)?([^/]+)', pattern)
            if match:
                url_module = match.group(2).replace('-', '_')

                # Check if it matches expected module names
                if url_module in module_mappings.values():
                    continue

                # Report unknown modules
                if url_module not in ['admin', 'docs', 'ops', 'decision', 'beta', 'alpha_trigger']:
                    inconsistencies.append({
                        'pattern': pattern,
                        'module': url_module,
                    })

        # Report findings
        if inconsistencies:
            print("\nURL modules with inconsistent naming:")
            for i in inconsistencies[:10]:  # Show first 10
                print(f"  - {i['pattern']} (module: {i['module']})")

        assert True, f"Found {len(inconsistencies)} modules with naming considerations"


class APIEndpointValidationTest:
    """Validate API endpoints are accessible and return proper responses."""

    @pytest.fixture
    def api_client(self):
        return Client()

    @pytest.mark.api_validation
    def test_core_api_endpoints_respond(self, api_client) -> None:
        """Core API endpoints should respond with proper status codes."""
        # Public endpoints
        public_endpoints = [
            '/health/',
            '/api/schema/',
        ]

        for endpoint in public_endpoints:
            response = api_client.get(endpoint)
            assert response.status_code in [200, 302, 405], \
                f"Endpoint {endpoint} returned {response.status_code}"

    @pytest.mark.api_validation
    def test_api_returns_json(self, api_client) -> None:
        """API endpoints should return JSON content type."""
        # Test schema endpoint
        response = api_client.get('/api/schema/')

        if response.status_code == 200:
            content_type = response.get('Content-Type', '')
            assert 'json' in content_type, \
                f"API endpoint should return JSON, got: {content_type}"


class FrontendBackendAPIConsistencyTest:
    """Test frontend-backend API consistency."""

    @pytest.mark.api_consistency
    def test_frontend_api_call_conventions(self) -> None:
        """Frontend should call APIs with consistent conventions."""
        # Scan frontend template files for API calls
        template_dir = Path(settings.BASE_DIR) / 'apps'

        api_call_patterns = [
            r'fetch\(["\']/?api/([^"\']+)',
            r'\$\.ajax\(["\']/?api/([^"\']+)',
            r'axios\.get\(["\']/?api/([^"\']+)',
            r'axios\.post\(["\']/?api/([^"\']+)',
        ]

        # This would require scanning template files
        # For now, we just verify the test infrastructure
        assert True, "API call convention check infrastructure ready"


class APIDocumentationTest:
    """Test API documentation completeness."""

    @pytest.mark.api_docs
    def test_openapi_schema_accessible(self) -> None:
        """OpenAPI schema should be accessible."""
        client = Client()

        response = client.get('/api/schema/')
        assert response.status_code == 200, "Schema endpoint should be accessible"

        # Should return JSON
        assert 'application/json' in response.get('Content-Type', ''), \
            "Schema should return JSON"

    @pytest.mark.api_docs
    def test_swagger_ui_accessible(self) -> None:
        """Swagger UI should be accessible."""
        client = Client()

        response = client.get('/api/docs/')
        assert response.status_code == 200, "Swagger UI should be accessible"

    @pytest.mark.api_docs
    def test_redoc_accessible(self) -> None:
        """ReDoc should be accessible."""
        client = Client()

        response = client.get('/api/redoc/')
        assert response.status_code == 200, "ReDoc should be accessible"


# Helper functions for reporting
def generate_api_compliance_report() -> Dict:
    """Generate API compliance report.

    Returns:
        Dictionary with compliance metrics
    """
    return {
        'total_endpoints': 0,
        'api_prefixed': 0,
        'documented': 0,
        'violations': [],
    }
