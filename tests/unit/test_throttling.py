"""
Tests for core/throttling.py

Tests for:
- BacktestRateThrottle: Only applies to POST requests
- WriteRateThrottle: Only applies to write methods
- BurstRateThrottle
- get_client_ip utility

P0-2: Verify that read operations are NOT throttled by BacktestRateThrottle
"""

from unittest.mock import MagicMock, patch

import pytest

from core.throttling import (
    BacktestRateThrottle,
    BurstRateThrottle,
    WriteRateThrottle,
    get_client_ip,
)


class TestBacktestRateThrottle:
    """Tests for BacktestRateThrottle."""

    def test_scope_is_backtest(self):
        """Test that the scope is set correctly."""
        throttle = BacktestRateThrottle()
        assert throttle.scope == "backtest"

    def test_allows_get_requests(self):
        """Test that GET requests are NOT throttled by BacktestRateThrottle."""
        throttle = BacktestRateThrottle()

        request = MagicMock()
        request.method = "GET"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1

        view = MagicMock()

        result = throttle.allow_request(request, view)
        # GET should pass through without throttling
        assert result is True

    def test_allows_head_requests(self):
        """Test that HEAD requests are NOT throttled."""
        throttle = BacktestRateThrottle()

        request = MagicMock()
        request.method = "HEAD"
        request.user = MagicMock()

        view = MagicMock()

        result = throttle.allow_request(request, view)
        assert result is True

    def test_allows_options_requests(self):
        """Test that OPTIONS requests are NOT throttled."""
        throttle = BacktestRateThrottle()

        request = MagicMock()
        request.method = "OPTIONS"
        request.user = MagicMock()

        view = MagicMock()

        result = throttle.allow_request(request, view)
        assert result is True

    def test_throttles_post_requests_under_limit(self):
        """Test that POST requests go through throttle check."""
        throttle = BacktestRateThrottle()

        request = MagicMock()
        request.method = "POST"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        view = MagicMock()

        # Mock the parent allow_request to return True (under limit)
        with patch.object(
            BacktestRateThrottle.__bases__[0],
            "allow_request",
            return_value=True
        ):
            result = throttle.allow_request(request, view)
            assert result is True

    def test_logs_when_throttled(self):
        """Test that throttled POST requests are logged."""
        throttle = BacktestRateThrottle()

        request = MagicMock()
        request.method = "POST"
        request.user = MagicMock()
        request.user.id = 1

        view = MagicMock()
        view.__class__.__name__ = "TestView"

        with patch.object(
            BacktestRateThrottle.__bases__[0],
            "allow_request",
            return_value=False
        ):
            with patch("core.throttling.logger") as mock_logger:
                result = throttle.allow_request(request, view)
                assert result is False
                mock_logger.warning.assert_called_once()


class TestWriteRateThrottle:
    """Tests for WriteRateThrottle."""

    def test_scope_is_write(self):
        """Test that the scope is set correctly."""
        throttle = WriteRateThrottle()
        assert throttle.scope == "write"

    def test_allows_get_requests(self):
        """Test that GET requests are NOT throttled."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "GET"
        request.user = MagicMock()

        view = MagicMock()

        result = throttle.allow_request(request, view)
        assert result is True

    def test_allows_head_requests(self):
        """Test that HEAD requests are NOT throttled."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "HEAD"
        request.user = MagicMock()

        view = MagicMock()

        result = throttle.allow_request(request, view)
        assert result is True

    def test_throttles_post_requests(self):
        """Test that POST requests are checked."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "POST"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        view = MagicMock()

        with patch.object(
            WriteRateThrottle.__bases__[0],
            "allow_request",
            return_value=True
        ):
            result = throttle.allow_request(request, view)
            assert result is True

    def test_throttles_put_requests(self):
        """Test that PUT requests are checked."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "PUT"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        view = MagicMock()

        with patch.object(
            WriteRateThrottle.__bases__[0],
            "allow_request",
            return_value=True
        ):
            result = throttle.allow_request(request, view)
            assert result is True

    def test_throttles_patch_requests(self):
        """Test that PATCH requests are checked."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "PATCH"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        view = MagicMock()

        with patch.object(
            WriteRateThrottle.__bases__[0],
            "allow_request",
            return_value=True
        ):
            result = throttle.allow_request(request, view)
            assert result is True

    def test_throttles_delete_requests(self):
        """Test that DELETE requests are checked."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "DELETE"
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 1
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        view = MagicMock()

        with patch.object(
            WriteRateThrottle.__bases__[0],
            "allow_request",
            return_value=True
        ):
            result = throttle.allow_request(request, view)
            assert result is True

    def test_logs_when_throttled(self):
        """Test that throttled write requests are logged."""
        throttle = WriteRateThrottle()

        request = MagicMock()
        request.method = "POST"
        request.user = MagicMock()
        request.user.id = 1

        view = MagicMock()
        view.__class__.__name__ = "TestView"

        with patch.object(
            WriteRateThrottle.__bases__[0],
            "allow_request",
            return_value=False
        ):
            with patch("core.throttling.logger") as mock_logger:
                result = throttle.allow_request(request, view)
                assert result is False
                mock_logger.warning.assert_called_once()


class TestBurstRateThrottle:
    """Tests for BurstRateThrottle."""

    def test_scope_is_burst(self):
        """Test that the scope is set correctly."""
        throttle = BurstRateThrottle()
        assert throttle.scope == "burst"


class TestGetClientIP:
    """Tests for get_client_ip utility."""

    def test_returns_remote_addr(self):
        """Test that REMOTE_ADDR is returned when no proxy."""
        request = MagicMock()
        request.META = {"REMOTE_ADDR": "192.168.1.1"}

        ip = get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_returns_first_x_forwarded_for(self):
        """Test that first X-Forwarded-For IP is returned."""
        request = MagicMock()
        request.META = {
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 10.0.0.2, 10.0.0.3",
            "REMOTE_ADDR": "192.168.1.1"
        }

        ip = get_client_ip(request)
        assert ip == "10.0.0.1"

    def test_handles_empty_x_forwarded_for(self):
        """Test handling of empty X-Forwarded-For."""
        request = MagicMock()
        request.META = {
            "HTTP_X_FORWARDED_FOR": "",
            "REMOTE_ADDR": "192.168.1.1"
        }

        ip = get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_handles_missing_remote_addr(self):
        """Test handling of missing REMOTE_ADDR."""
        request = MagicMock()
        request.META = {}

        ip = get_client_ip(request)
        assert ip == ""


class TestThrottleConfiguration:
    """Tests for throttle configuration via settings."""

    def test_backtest_throttle_uses_scope(self):
        """Test that BacktestRateThrottle has correct scope for settings lookup."""
        throttle = BacktestRateThrottle()
        # DRF uses the scope to look up rate from DEFAULT_THROTTLE_RATES
        assert throttle.scope == "backtest"

    def test_write_throttle_uses_scope(self):
        """Test that WriteRateThrottle has correct scope for settings lookup."""
        throttle = WriteRateThrottle()
        assert throttle.scope == "write"

    def test_burst_throttle_uses_scope(self):
        """Test that BurstRateThrottle has correct scope for settings lookup."""
        throttle = BurstRateThrottle()
        assert throttle.scope == "burst"

    def test_all_throttles_inherit_from_user_rate_throttle(self):
        """Test that all custom throttles inherit from UserRateThrottle."""
        from rest_framework.throttling import UserRateThrottle

        assert issubclass(BacktestRateThrottle, UserRateThrottle)
        assert issubclass(WriteRateThrottle, UserRateThrottle)
        assert issubclass(BurstRateThrottle, UserRateThrottle)

    def test_no_custom_get_rate_method(self):
        """Test that throttles don't override get_rate, allowing DRF to read from settings."""
        # If we override get_rate(), DRF can't read from DEFAULT_THROTTLE_RATES
        # So we should NOT have a custom get_rate method
        assert "get_rate" not in BacktestRateThrottle.__dict__
        assert "get_rate" not in WriteRateThrottle.__dict__
        assert "get_rate" not in BurstRateThrottle.__dict__
