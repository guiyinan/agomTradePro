"""
Unit tests for health check endpoints.

Tests the liveness and readiness probes for Kubernetes deployment.
"""

import pytest
from datetime import datetime, timezone
from django.test import Client
from django.core.cache import cache
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestHealthCheckEndpoints:
    """Test health check endpoint responses"""

    def test_liveness_probe_returns_ok(self, db):
        """Test liveness probe returns 200 with ok status"""
        client = Client()
        response = client.get('/api/health/')

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data

    def test_readiness_probe_with_healthy_database(self, db):
        """Test readiness probe returns 200 when database is healthy"""
        client = Client()
        response = client.get('/api/ready/')

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert 'timestamp' in data
        assert 'checks' in data
        assert data['checks']['database']['status'] == 'ok'

    def test_readiness_probe_content_type(self, db):
        """Test health endpoints return JSON content type"""
        client = Client()

        response = client.get('/api/health/')
        assert response['Content-Type'] == 'application/json'

        response = client.get('/api/ready/')
        assert response['Content-Type'] == 'application/json'


@pytest.mark.unit
class TestHealthCheckFunctions:
    """Test health check module functions"""

    def test_check_database_healthy(self, db):
        """Test database check returns ok when database is accessible"""
        from core.health_checks import check_database

        result = check_database()
        assert result['status'] == 'ok'

    @patch('core.health_checks.connections')
    def test_check_database_error(self, mock_connections):
        """Test database check returns error when database fails"""
        from core.health_checks import check_database
        from django.db import DatabaseError

        # Mock database connection to fail
        mock_conn = MagicMock()
        mock_conn.ensure_connection.side_effect = DatabaseError("Connection failed")
        mock_connections.__getitem__.return_value = mock_conn

        result = check_database()
        assert result['status'] == 'error'
        assert 'error' in result

    def test_check_redis_with_locmem_cache(self, db):
        """Test Redis check returns skipped when using LocMemCache"""
        from core.health_checks import check_redis

        result = check_redis()
        # In development/test environment, LocMemCache is used
        assert result['status'] in ('skipped', 'ok')

    def test_check_redis_skipped_when_not_configured(self, db):
        """Test Redis check returns skipped when Redis is not configured"""
        from core.health_checks import check_redis

        result = check_redis()
        # Either skipped (if no Redis) or ok (if cache is working)
        assert result['status'] in ('skipped', 'ok')

    @patch('django.core.cache.cache.get', side_effect=Exception("Redis connection failed"))
    @patch('django.conf.settings')
    def test_check_redis_error(self, mock_settings, mock_get):
        """Test Redis check returns error when cache operations fail"""
        from core.health_checks import check_redis

        # Mock Redis cache configuration
        mock_settings.CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache'
            }
        }

        result = check_redis()
        assert result['status'] == 'error'
        assert 'error' in result

    def test_run_readiness_checks(self, db):
        """Test readiness checks runs all checks"""
        from core.health_checks import run_readiness_checks

        checks = run_readiness_checks()
        assert 'database' in checks
        assert 'redis' in checks

    def test_is_healthy_all_ok(self, db):
        """Test is_healthy returns True when all checks are ok"""
        from core.health_checks import is_healthy

        checks = {
            'database': {'status': 'ok'},
            'redis': {'status': 'ok'}
        }
        assert is_healthy(checks) is True

    def test_is_healthy_with_skipped(self, db):
        """Test is_healthy returns True when checks include skipped"""
        from core.health_checks import is_healthy

        checks = {
            'database': {'status': 'ok'},
            'redis': {'status': 'skipped'}
        }
        assert is_healthy(checks) is True

    def test_is_healthy_with_error(self, db):
        """Test is_healthy returns False when any check fails"""
        from core.health_checks import is_healthy

        checks = {
            'database': {'status': 'ok'},
            'redis': {'status': 'error', 'error': 'Connection failed'}
        }
        assert is_healthy(checks) is False


@pytest.mark.unit
class TestHealthCheckIntegration:
    """Integration tests for health checks"""

    def test_readiness_probe_full_response_format(self, db):
        """Test readiness probe returns complete response format"""
        client = Client()
        response = client.get('/api/ready/')

        data = response.json()

        # Verify all expected fields are present
        assert 'status' in data
        assert 'timestamp' in data
        assert 'checks' in data
        assert 'database' in data['checks']
        assert 'redis' in data['checks']

    def test_readiness_probe_timestamp_format(self, db):
        """Test readiness probe returns ISO format timestamp"""
        client = Client()
        response = client.get('/api/ready/')

        data = response.json()
        timestamp_str = data['timestamp']

        # Verify timestamp can be parsed as ISO format datetime
        try:
            datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"Timestamp {timestamp_str} is not in ISO format")

    @patch('core.health_checks.check_database')
    def test_readiness_propagates_database_error(self, mock_check_db, db):
        """Test readiness probe returns 503 when database check fails"""
        from core.health_checks import check_database

        # Mock database check to fail
        mock_check_db.return_value = {'status': 'error', 'error': 'Connection failed'}

        client = Client()
        response = client.get('/api/ready/')

        assert response.status_code == 503
        data = response.json()
        assert data['status'] == 'error'
        assert data['checks']['database']['status'] == 'error'
