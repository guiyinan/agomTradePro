"""
Unit tests for Account Module Notification Service

Tests for the stop loss/take profit notification service.
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, call, patch

import pytest
from django.test import override_settings

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.account.application.stop_loss_use_cases import AutoStopLossUseCase
from apps.account.domain.interfaces import StopLossNotificationData
from apps.account.infrastructure import market_price_service as market_price_service_module
from apps.account.infrastructure.market_price_service import MarketPriceService
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
        trigger_time=datetime.now(UTC),
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
        trigger_time=datetime.now(UTC),
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
            trigger_time=datetime.now(UTC),
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
        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore",
            return_value=mock_event_store,
        ):
            service = EmailStopLossNotificationService()
            assert service.event_store == mock_event_store

    @patch("apps.account.infrastructure.notification_service.send_mail")
    @patch("apps.account.infrastructure.notification_service.User")
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_notify_stop_loss_triggered_sends_email(
        self, mock_user_cls, mock_send_mail, notification_data, mock_event_store
    ):
        """Test that stop loss notification sends email when enabled."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.return_value = True

        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore",
            return_value=mock_event_store,
        ):
            service = EmailStopLossNotificationService()
            result = service.notify_stop_loss_triggered(notification_data)

        assert result is True
        mock_send_mail.assert_called_once()
        assert "止损触发通知" in mock_send_mail.call_args[1]["subject"]
        assert notification_data.user_email in mock_send_mail.call_args[1]["recipient_list"]

    @patch("apps.account.infrastructure.notification_service.User")
    def test_notify_stop_loss_triggered_logs_event(
        self, mock_user_cls, notification_data, mock_event_store
    ):
        """Test that stop loss notification logs event to event store."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user

        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore",
            return_value=mock_event_store,
        ):
            service = EmailStopLossNotificationService()
            service.notify_stop_loss_triggered(notification_data)

        # Verify event was appended to store
        mock_event_store.append.assert_called_once()
        event = mock_event_store.append.call_args[0][0]
        assert event.event_type.value == "stop_loss_triggered"

    @patch("apps.account.infrastructure.notification_service.send_mail")
    @patch("apps.account.infrastructure.notification_service.User")
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_notify_take_profit_triggered_sends_email(
        self, mock_user_cls, mock_send_mail, take_profit_notification_data, mock_event_store
    ):
        """Test that take profit notification sends email when enabled."""
        mock_user = Mock()
        mock_user.email = take_profit_notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.return_value = True

        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore",
            return_value=mock_event_store,
        ):
            service = EmailStopLossNotificationService()
            result = service.notify_take_profit_triggered(take_profit_notification_data)

        assert result is True
        mock_send_mail.assert_called_once()
        assert "止盈触发通知" in mock_send_mail.call_args[1]["subject"]

    @patch("apps.account.infrastructure.notification_service.send_mail")
    @patch("apps.account.infrastructure.notification_service.User")
    @override_settings(SEND_EMAIL_NOTIFICATIONS=True)
    def test_email_send_failure_does_not_raise_exception(
        self, mock_user_cls, mock_send_mail, notification_data, mock_event_store
    ):
        """Test that email send failure is handled gracefully."""
        mock_user = Mock()
        mock_user.email = notification_data.user_email
        mock_user_cls._default_manager.get.return_value = mock_user
        mock_send_mail.side_effect = Exception("SMTP error")

        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore",
            return_value=mock_event_store,
        ):
            service = EmailStopLossNotificationService()
            # Should not raise exception
            result = service.notify_stop_loss_triggered(notification_data)

        # Should return False but not crash
        assert result is False

    @patch("apps.account.infrastructure.notification_service.send_mail")
    @patch("apps.account.infrastructure.notification_service.User")
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

        with patch(
            "apps.events.infrastructure.event_store.DatabaseEventStore", return_value=mock_store
        ):
            service = EmailStopLossNotificationService()
            # Should not raise exception
            result = service.notify_stop_loss_triggered(notification_data)

        # Should still succeed
        assert result is True

    def test_build_stop_loss_text_message(self):
        """Test stop loss email message formatting."""
        service = EmailStopLossNotificationService()
        context = {
            "user_email": "test@example.com",
            "asset_code": "000001.SZ",
            "trigger_type": "fixed",
            "trigger_price": Decimal("9.50"),
            "trigger_time": datetime.now(UTC),
            "trigger_reason": "价格下跌超过10%",
            "pnl": Decimal("-500.00"),
            "pnl_pct": -10.0,
            "shares_closed": 100.0,
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
            "user_email": "test@example.com",
            "asset_code": "600000.SH",
            "trigger_price": Decimal("11.00"),
            "trigger_time": datetime.now(UTC),
            "trigger_reason": "价格上涨超过10%",
            "pnl": Decimal("500.00"),
            "pnl_pct": 10.0,
            "shares_closed": 100.0,
        }

        message = service._build_take_profit_text_message(context)

        assert "止盈触发通知" in message or "已触发止盈" in message
        assert "600000.SH" in message
        assert "+10.00%" in message or "10.00%" in message


# =============================================================================
# Stop-Loss Market Price Boundary Tests
# =============================================================================


def _stop_loss_config(
    *, position_id: int, asset_code: str, average_cost: Decimal
) -> dict[str, object]:
    """Build the minimum valid legacy position context for an observation check."""

    return {
        "position": {
            "id": position_id,
            "asset_code": asset_code,
            "avg_cost": average_cost,
            "shares": 100.0,
        },
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.1,
        "highest_price": average_cost,
    }


def _market_price_result(
    *, asset_code: str, price: float, source: str, observed_at: datetime
) -> MarketPriceResult:
    """Create one valid realtime provider result without depending on a live feed."""

    return MarketPriceResult(
        normalized_code=asset_code,
        price=price,
        as_of=None,
        source=source,
        freshness="realtime",
        is_fallback=False,
        observed_at=observed_at,
    )


def test_default_stop_loss_factory_uses_one_metadata_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default use case keeps the service factory and source clock intact."""

    observed_at = datetime.now(UTC)
    provider = Mock()
    provider.get_price_result.return_value = _market_price_result(
        asset_code="000001.SZ",
        price=10.5,
        source="test_realtime_quote",
        observed_at=observed_at,
    )
    provider_factory = Mock(return_value=provider)
    monkeypatch.setattr(
        market_price_service_module,
        "build_market_price_provider",
        provider_factory,
    )
    scalar_lookup = Mock(return_value=Decimal("99.00"))
    monkeypatch.setattr(MarketPriceService, "get_current_price", scalar_lookup)
    batch_lookup = Mock(return_value={"000001.SZ": Decimal("99.00")})
    monkeypatch.setattr(MarketPriceService, "get_prices_batch", batch_lookup)

    repository = Mock()
    repository.get_active_stop_loss_configs.return_value = [
        _stop_loss_config(
            position_id=101,
            asset_code="000001.SZ",
            average_cost=Decimal("10.00"),
        )
    ]
    use_case = AutoStopLossUseCase(stop_loss_repo=repository)

    results = use_case.check_and_execute_stop_loss(user_id=7)

    assert isinstance(use_case.market_data_service, MarketPriceService)
    provider_factory.assert_called_once_with(30)
    provider.get_price_result.assert_called_once_with("000001.SZ", None)
    scalar_lookup.assert_not_called()
    batch_lookup.assert_not_called()
    repository.get_active_stop_loss_configs.assert_called_once_with(user_id=7)
    assert len(results) == 1
    assert results[0].asset_code == "000001.SZ"
    assert results[0].current_price == 10.5
    assert results[0].price_source == "test_realtime_quote"
    assert results[0].price_observed_at == observed_at
    assert results[0].price_freshness == "realtime"


def test_provider_exception_returns_unavailable_without_scalar_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed canonical provider lookup cannot be replaced by a scalar price."""

    provider = Mock()
    provider.get_price_result.side_effect = RuntimeError("provider unavailable")
    provider_factory = Mock(return_value=provider)
    monkeypatch.setattr(
        market_price_service_module,
        "build_market_price_provider",
        provider_factory,
    )
    scalar_lookup = Mock(return_value=Decimal("10.50"))
    monkeypatch.setattr(MarketPriceService, "get_current_price", scalar_lookup)

    repository = Mock()
    repository.get_active_stop_loss_configs.return_value = [
        _stop_loss_config(
            position_id=102,
            asset_code="000001.SZ",
            average_cost=Decimal("10.00"),
        )
    ]
    use_case = AutoStopLossUseCase(stop_loss_repo=repository)

    results = use_case.check_and_execute_stop_loss(user_id=7)

    provider_factory.assert_called_once_with(30)
    provider.get_price_result.assert_called_once_with("000001.SZ", None)
    scalar_lookup.assert_not_called()
    assert len(results) == 1
    assert results[0].check_status == "unavailable"
    assert results[0].reason_code == "market_price_unavailable"
    assert results[0].current_price is None
    assert results[0].unrealized_pnl is None
    assert results[0].unrealized_pnl_pct is None
    assert results[0].price_source is None
    assert results[0].price_observed_at is None


def test_default_service_reads_each_security_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-position loop preserves each requested code, price, and source time."""

    observed_at_by_code = {
        "000001.SZ": datetime.now(UTC),
        "600000.SH": datetime.now(UTC),
    }
    results_by_code = {
        "000001.SZ": _market_price_result(
            asset_code="000001.SZ",
            price=10.5,
            source="sz_quote",
            observed_at=observed_at_by_code["000001.SZ"],
        ),
        "600000.SH": _market_price_result(
            asset_code="600000.SH",
            price=20.5,
            source="sh_quote",
            observed_at=observed_at_by_code["600000.SH"],
        ),
    }
    provider = Mock()

    def get_price_result(
        asset_code: str, trade_date: date | None = None
    ) -> MarketPriceResult | None:
        """Return the exact fixture result keyed by the requested security."""

        return results_by_code.get(asset_code)

    provider.get_price_result.side_effect = get_price_result
    provider_factory = Mock(return_value=provider)
    monkeypatch.setattr(
        market_price_service_module,
        "build_market_price_provider",
        provider_factory,
    )
    scalar_lookup = Mock(return_value=Decimal("99.00"))
    monkeypatch.setattr(MarketPriceService, "get_current_price", scalar_lookup)
    batch_lookup = Mock(return_value={})
    monkeypatch.setattr(MarketPriceService, "get_prices_batch", batch_lookup)

    repository = Mock()
    repository.get_active_stop_loss_configs.return_value = [
        _stop_loss_config(
            position_id=201,
            asset_code="000001.SZ",
            average_cost=Decimal("10.00"),
        ),
        _stop_loss_config(
            position_id=202,
            asset_code="600000.SH",
            average_cost=Decimal("20.00"),
        ),
    ]
    use_case = AutoStopLossUseCase(stop_loss_repo=repository)

    results = use_case.check_and_execute_stop_loss(user_id=7)

    provider_factory.assert_called_once_with(30)
    assert provider.get_price_result.call_args_list == [
        call("000001.SZ", None),
        call("600000.SH", None),
    ]
    scalar_lookup.assert_not_called()
    batch_lookup.assert_not_called()
    by_position = {result.position_id: result for result in results}
    assert by_position[201].asset_code == "000001.SZ"
    assert by_position[201].current_price == 10.5
    assert by_position[201].price_source == "sz_quote"
    assert by_position[201].price_observed_at == observed_at_by_code["000001.SZ"]
    assert by_position[202].asset_code == "600000.SH"
    assert by_position[202].current_price == 20.5
    assert by_position[202].price_source == "sh_quote"
    assert by_position[202].price_observed_at == observed_at_by_code["600000.SH"]


def test_available_provider_without_metadata_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider configuration availability does not authorize scalar fallback."""

    provider = Mock()
    provider.get_price_result.return_value = None
    provider_factory = Mock(return_value=provider)
    monkeypatch.setattr(
        market_price_service_module,
        "build_market_price_provider",
        provider_factory,
    )
    scalar_lookup = Mock(return_value=Decimal("10.50"))
    monkeypatch.setattr(MarketPriceService, "get_current_price", scalar_lookup)

    repository = Mock()
    repository.get_active_stop_loss_configs.return_value = [
        _stop_loss_config(
            position_id=103,
            asset_code="000001.SZ",
            average_cost=Decimal("10.00"),
        )
    ]
    use_case = AutoStopLossUseCase(stop_loss_repo=repository)
    service = use_case.market_data_service

    assert isinstance(service, MarketPriceService)
    assert service.is_available() is True
    results = use_case.check_and_execute_stop_loss(user_id=7)

    provider_factory.assert_called_once_with(30)
    provider.get_price_result.assert_called_once_with("000001.SZ", None)
    scalar_lookup.assert_not_called()
    assert len(results) == 1
    assert results[0].check_status == "unavailable"
    assert results[0].reason_code == "market_price_unavailable"
    assert results[0].current_price is None
    assert results[0].price_source is None
    assert results[0].price_observed_at is None
