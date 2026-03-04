"""
Unit tests for Account Module Notification Service

Tests for the stop loss/take profit notification service.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

import pytest
from django.test import override_settings

from apps.account.domain.interfaces import StopLossNotificationData
from apps.account.infrastructure.notification_service import (
    EmailStopLossNotificationService,
    InMemoryStopLossNotificationService,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def notification_data():
    """Sample notification data for testing."""
    return StopLossNotificationData(
        user_id=1,
        user_email="test@example.com",
        position_id=100,
        asset_code="000001.SZ",
        trigger_type="fixed",
        trigger_price=Decimal("9.50"),
        trigger_time=datetime.now(timezone.utc),
        trigger_reason="价格下跌超过10%",
        pnl=Decimal("-500.00"),
        pnl_pct=-10.0,
        shares_closed=100.0,
    )


@pytest.fixture
def take_profit_notification_data():
    """Sample take profit notification data for testing."""
    return StopLossNotificationData(
        user_id=1,
        user_email="test@example.com",
        position_id=100,
        asset_code="000001.SZ",
        trigger_type="take_profit",
        trigger_price=Decimal("11.00"),
        trigger_time=datetime.now(timezone.utc),
        trigger_reason="价格上涨超过10%",
        pnl=Decimal("500.00"),
        pnl_pct=10.0,
        shares_closed=100.0,
    )


# =============================================================================
# InMemoryStopLossNotificationService Tests
# =============================================================================

class TestInMemoryStopLossNotificationService:
    """Tests for InMemoryStopLossNotificationService."""

    def test_notify_stop_loss_triggered_logs_info(self, notification_data, caplog):
        """Test that stop loss notification is logged correctly."""
        service = InMemoryStopLossNotificationService()

        with caplog.at_level(logging.INFO):
            result = service.notify_stop_loss_triggered(notification_data)

        assert result is True
        assert "[止损触发]" in caplog.text
        assert "user_id=1" in caplog.text or "用户: 1" in caplog.text
        assert "000001.SZ" in caplog.text

    def test_notify_take_profit_triggered_logs_info(self, take_profit_notification_data, caplog):
        """Test that take profit notification is logged correctly."""
        service = InMemoryStopLossNotificationService()

        with caplog.at_level(logging.INFO):
            result = service.notify_take_profit_triggered(take_profit_notification_data)

        assert result is True
        assert "[止盈触发]" in caplog.text
        assert "000001.SZ" in caplog.text

    def test_stop_loss_notification_with_partial_shares(self, caplog):
        """Test stop loss notification with partial shares closed."""
        data = StopLossNotificationData(
            user_id=1,
            user_email="test@example.com",
            position_id=100,
            asset_code="600000.SH",
            trigger_type="trailing",
            trigger_price=Decimal("8.50"),
            trigger_time=datetime.now(timezone.utc),
            trigger_reason="移动止损触发",
            pnl=Decimal("-300.00"),
            pnl_pct=-8.0,
            shares_closed=50.0,  # Partial close
        )

        service = InMemoryStopLossNotificationService()

        with caplog.at_level(logging.INFO):
            result = service.notify_stop_loss_triggered(data)

        assert result is True
        assert "移动止损触发" in caplog.text


# =============================================================================
# EmailStopLossNotificationService Tests
# =============================================================================

class TestEmailStopLossNotificationService:
    """Tests for EmailStopLossNotificationService."""

    @pytest.fixture
    def mock_event_store(self):
        """Mock event store."""
        store = Mock()
        store.append = Mock(return_value=True)
        return store

    def test_init_creates_event_store(self, mock_event_store):
        """Test that service initializes with event store."""
        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_event_store):
            service = EmailStopLossNotificationService()
            assert service.event_store == mock_event_store

    @patch('apps.account.infrastructure.notification_service.send_mail')
    @patch('apps.account.infrastructure.notification_service.User')
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_notify_stop_loss_triggered_sends_email(
        self, mock_user_cls, mock_send_mail, notification_data, mock_event_store
    ):
        """Test that stop loss notification sends email when enabled."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.return_value = True

        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_event_store):
            service = EmailStopLossNotificationService()
            result = service.notify_stop_loss_triggered(notification_data)

        assert result is True
        mock_send_mail.assert_called_once()
        assert "止损触发通知" in mock_send_mail.call_args[1]['subject']
        assert notification_data.user_email in mock_send_mail.call_args[1]['recipient_list']

    @patch('apps.account.infrastructure.notification_service.User')
    def test_notify_stop_loss_triggered_logs_event(
        self, mock_user_cls, notification_data, mock_event_store
    ):
        """Test that stop loss notification logs event to event store."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user

        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_event_store):
            service = EmailStopLossNotificationService()
            service.notify_stop_loss_triggered(notification_data)

        # Verify event was appended to store
        mock_event_store.append.assert_called_once()
        event = mock_event_store.append.call_args[0][0]
        assert event.event_type.value == "stop_loss_triggered"

    @patch('apps.account.infrastructure.notification_service.send_mail')
    @patch('apps.account.infrastructure.notification_service.User')
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_notify_take_profit_triggered_sends_email(
        self, mock_user_cls, mock_send_mail, take_profit_notification_data, mock_event_store
    ):
        """Test that take profit notification sends email when enabled."""
        mock_user = Mock()
        mock_user.email = take_profit_notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.return_value = True

        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_event_store):
            service = EmailStopLossNotificationService()
            result = service.notify_take_profit_triggered(take_profit_notification_data)

        assert result is True
        mock_send_mail.assert_called_once()
        assert "止盈触发通知" in mock_send_mail.call_args[1]['subject']

    @patch('apps.account.infrastructure.notification_service.send_mail')
    @patch('apps.account.infrastructure.notification_service.User')
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_email_send_failure_does_not_raise_exception(
        self, mock_user_cls, mock_send_mail, notification_data, mock_event_store
    ):
        """Test that email send failure is handled gracefully."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.side_effect = Exception("SMTP error")

        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_event_store):
            service = EmailStopLossNotificationService()
            # Should not raise exception
            result = service.notify_stop_loss_triggered(notification_data)

        # Should return False but not crash
        assert result is False

    @patch('apps.account.infrastructure.notification_service.send_mail')
    @patch('apps.account.infrastructure.notification_service.User')
    def test_event_store_failure_does_not_affect_notification(
        self, mock_user_cls, mock_send_mail, notification_data
    ):
        """Test that event store failure is handled gracefully."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.return_value = True

        mock_store = Mock()
        mock_store.append.side_effect = Exception("Database error")

        with patch('apps.events.infrastructure.event_store.DatabaseEventStore', return_value=mock_store):
            service = EmailStopLossNotificationService()
            # Should not raise exception
            result = service.notify_stop_loss_triggered(notification_data)

        # Should still succeed
        assert result is True

    def test_build_stop_loss_text_message(self):
        """Test stop loss email message formatting."""
        service = EmailStopLossNotificationService()
        context = {
            'user_email': 'test@example.com',
            'asset_code': '000001.SZ',
            'trigger_type': 'fixed',
            'trigger_price': Decimal('9.50'),
            'trigger_time': datetime.now(timezone.utc),
            'trigger_reason': '价格下跌超过10%',
            'pnl': Decimal('-500.00'),
            'pnl_pct': -10.0,
            'shares_closed': 100.0,
        }

        message = service._build_stop_loss_text_message(context)

        assert "止损触发通知" in message or "已触发止损" in message
        assert "000001.SZ" in message
        assert "9.5" in message or "9.50" in message
        assert "-10.00%" in message

    def test_build_take_profit_text_message(self):
        """Test take profit email message formatting."""
        service = EmailStopLossNotificationService()
        context = {
            'user_email': 'test@example.com',
            'asset_code': '600000.SH',
            'trigger_price': Decimal('11.00'),
            'trigger_time': datetime.now(timezone.utc),
            'trigger_reason': '价格上涨超过10%',
            'pnl': Decimal('500.00'),
            'pnl_pct': 10.0,
            'shares_closed': 100.0,
        }

        message = service._build_take_profit_text_message(context)

        assert "止盈触发通知" in message or "已触发止盈" in message
        assert "600000.SH" in message
        assert "+10.00%" in message or "10.00%" in message


# =============================================================================
# Market Data Adapter Tests
# =============================================================================

class TestMarketDataAdapter:
    """Tests for _MarketDataAdapter in stop_loss_use_cases."""

    @patch('apps.account.application.stop_loss_use_cases.MarketPriceService')
    def test_get_current_price_calls_service(self, mock_service_cls):
        """Test that adapter calls underlying service."""
        from apps.account.application.stop_loss_use_cases import _MarketDataAdapter

        mock_service = Mock()
        mock_service.get_current_price.return_value = Decimal("10.50")
        mock_service_cls.return_value = mock_service

        adapter = _MarketDataAdapter()
        result = adapter.get_current_price("000001.SZ")

        assert result == Decimal("10.50")
        mock_service.get_current_price.assert_called_once_with("000001.SZ")

    @patch('apps.account.application.stop_loss_use_cases.MarketPriceService')
    def test_get_current_price_returns_none_on_error(self, mock_service_cls):
        """Test that adapter returns None when service fails."""
        from apps.account.application.stop_loss_use_cases import _MarketDataAdapter

        mock_service = Mock()
        mock_service.get_current_price.side_effect = Exception("Network error")
        mock_service_cls.return_value = mock_service

        adapter = _MarketDataAdapter()
        result = adapter.get_current_price("000001.SZ")

        assert result is None

    @patch('apps.account.application.stop_loss_use_cases.MarketPriceService')
    def test_get_prices_batch(self, mock_service_cls):
        """Test batch price retrieval."""
        from apps.account.application.stop_loss_use_cases import _MarketDataAdapter

        mock_service = Mock()
        mock_service.get_prices_batch.return_value = {
            "000001.SZ": Decimal("10.50"),
            "600000.SH": Decimal("8.20"),
        }
        mock_service_cls.return_value = mock_service

        adapter = _MarketDataAdapter()
        result = adapter.get_prices_batch(["000001.SZ", "600000.SH"])

        assert result["000001.SZ"] == Decimal("10.50")
        assert result["600000.SH"] == Decimal("8.20")

    @patch('apps.account.application.stop_loss_use_cases.MarketPriceService')
    def test_is_available(self, mock_service_cls):
        """Test availability check."""
        from apps.account.application.stop_loss_use_cases import _MarketDataAdapter

        mock_service = Mock()
        mock_service.is_available.return_value = True
        mock_service_cls.return_value = mock_service

        adapter = _MarketDataAdapter()
        assert adapter.is_available() is True
