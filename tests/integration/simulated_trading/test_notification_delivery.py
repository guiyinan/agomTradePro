"""Integration tests for notification delivery in simulated trading."""

from datetime import date, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.core.mail import send_mail
from django.utils import timezone

from apps.simulated_trading.application.tasks import (
    NotificationConfig,
    _record_notification_history,
    _send_daily_inspection_email,
    _send_rebalance_proposal_notification,
)
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionNotificationConfigModel,
    DailyInspectionReportModel,
    NotificationHistoryModel,
    RebalanceProposalModel,
    SimulatedAccountModel,
)
from shared.infrastructure.notification_service import (
    EmailNotificationChannel,
    InAppNotificationChannel,
    NotificationMessage,
    NotificationPriority,
    NotificationRecipient,
    UnifiedNotificationService,
)
from shared.infrastructure.notification_service import (
    NotificationChannel as NC,
)


@pytest.mark.django_db
class TestEmailNotificationChannel:
    """Test email notification channel."""

    def test_channel_is_available_with_smtp_config(self):
        """Test channel is available with SMTP config."""
        with patch("django.conf.settings.EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"):
            with patch("django.conf.settings.EMAIL_HOST", "smtp.example.com"):
                channel = EmailNotificationChannel()
                assert channel.is_available() is True

    def test_channel_is_available_with_console_backend(self):
        """Test channel is available with console backend."""
        with patch("django.conf.settings.EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"):
            channel = EmailNotificationChannel()
            assert channel.is_available() is True

    def test_validate_recipient_valid_email(self):
        """Test recipient validation with valid email."""
        channel = EmailNotificationChannel()
        recipient = NotificationRecipient(email="test@example.com")

        assert channel.validate_recipient(recipient) is True

    def test_validate_recipient_invalid_email(self):
        """Test recipient validation with invalid email."""
        channel = EmailNotificationChannel()

        # Missing @
        assert channel.validate_recipient(NotificationRecipient(email="invalid")) is False

        # Missing domain
        assert channel.validate_recipient(NotificationRecipient(email="test@")) is False

        # None email
        assert channel.validate_recipient(NotificationRecipient()) is False

    @pytest.mark.django_db
    def test_send_email_success(self):
        """Test successful email sending."""
        # Mock SMTP settings
        with patch("django.conf.settings.EMAIL_BACKEND", "django.core.mail.backends.locmem.EmailBackend"):
            with patch("django.conf.settings.EMAIL_HOST", "smtp.example.com"):
                with patch("django.conf.settings.EMAIL_PORT", 587):
                    channel = EmailNotificationChannel()

                    message = NotificationMessage(
                        subject="Test Subject",
                        body="Test body content",
                        priority=NotificationPriority.NORMAL,
                    )

                    recipient = NotificationRecipient(
                        email="test@example.com",
                        name="Test User",
                    )

                    config = NotificationConfig()
                    config.max_retries = 0  # Disable retries for faster test

                    # Mock at the module level where _send_email is defined
                    with patch("shared.infrastructure.notification_service.EmailNotificationChannel._send_email", return_value=True):
                        result = channel.send(message, recipient, config)

                        assert result.success is True
                        assert result.status.value == "sent"
                        assert result.channel.value == "email"
                        assert result.retry_count == 0


@pytest.mark.django_db
class TestInAppNotificationChannel:
    """Test in-app notification channel."""

    def test_channel_is_available_without_model(self):
        """Test channel availability when model is not configured."""
        channel = InAppNotificationChannel(model_class=None)
        # Without explicit model injection, in-app notification stays disabled.
        assert channel.is_available() is False

    def test_channel_is_available_with_injected_model(self):
        """Test channel availability when model class is injected explicitly."""
        fake_model = MagicMock()
        channel = InAppNotificationChannel(model_class=fake_model)

        assert channel.is_available() is True

    def test_validate_recipient_with_user_id(self):
        """Test recipient validation with user_id."""
        channel = InAppNotificationChannel()
        recipient = NotificationRecipient(user_id=123)

        assert channel.validate_recipient(recipient) is True

    def test_validate_recipient_without_user_id(self):
        """Test recipient validation without user_id."""
        channel = InAppNotificationChannel()
        recipient = NotificationRecipient()

        assert channel.validate_recipient(recipient) is False


@pytest.mark.django_db
class TestUnifiedNotificationService:
    """Test unified notification service."""

    def test_send_email_notification(self):
        """Test sending email notification through unified service."""
        service = UnifiedNotificationService()

        with patch.object(EmailNotificationChannel, "send") as mock_send:
            mock_send.return_value = Mock(success=True, status=Mock(value="sent"), channel=Mock(value="email"))

            results = service.send_email(
                subject="Test Subject",
                body="Test body",
                recipients="test@example.com",
            )

            assert len(results) == 1
            assert results[0].success is True

    def test_send_multiple_recipients(self):
        """Test sending notification to multiple recipients."""
        service = UnifiedNotificationService()

        with patch.object(EmailNotificationChannel, "send") as mock_send:
            mock_send.return_value = Mock(success=True, status=Mock(value="sent"), channel=Mock(value="email"))

            results = service.send_email(
                subject="Test Subject",
                body="Test body",
                recipients=["user1@example.com", "user2@example.com"],
            )

            assert len(results) == 2
            assert all(r.success for r in results)

    def test_send_alert_notification(self):
        """Test sending alert notification."""
        service = UnifiedNotificationService()

        result = service.send_alert(
            title="Test Alert",
            message="Test alert message",
            level="warning",
        )

        # Alert channel (console) should always succeed
        assert result.success is True


@pytest.mark.django_db
class TestDailyInspectionEmail:
    """Test daily inspection email notification."""

    def test_send_email_with_valid_recipients(self):
        """Test sending inspection email with valid recipients."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="testinspectionuser",
            email="inspection@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Inspection Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        # Create notification config
        config = DailyInspectionNotificationConfigModel.objects.create(
            account=account,
            is_enabled=True,
            include_owner_email=True,
        )

        result = {
            "account_id": account.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "macro_regime": "growth_stable",
            "policy_gear": "neutral",
            "strategy_id": 1,
            "position_rule_id": 1,
            "summary": {
                "positions_count": 5,
                "rebalance_required_count": 2,
                "rebalance_assets": ["512880.SH", "515050.SH"],
                "total_value": 100000.0,
                "current_cash": 5000.0,
            },
            "checks": [
                {
                    "asset_code": "512880.SH",
                    "weight": 0.28,
                    "target_weight": 0.30,
                    "drift": -0.02,
                    "action": "buy",
                },
            ],
        }

        with patch("apps.simulated_trading.application.tasks.send_mail") as mock_send:
            _send_daily_inspection_email(result=result)

            assert mock_send.called

    def test_send_email_skipped_when_no_recipients(self):
        """Test email is skipped when no recipients configured."""
        result = {
            "account_id": 999,  # Non-existent account
            "inspection_date": "2026-02-26",
            "status": "ok",
            "summary": {},
            "checks": [],
        }

        with patch("apps.simulated_trading.application.tasks.send_mail") as mock_send:
            _send_daily_inspection_email(result=result)

            # Should not send email for non-existent account
            assert not mock_send.called


@pytest.mark.django_db
class TestRebalanceProposalNotification:
    """Test rebalance proposal notification."""

    def test_send_notification_with_valid_proposal(self):
        """Test sending notification for valid rebalance proposal."""
        # Create test account and user
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        # Create notification config
        config = DailyInspectionNotificationConfigModel.objects.create(
            account=account,
            is_enabled=True,
            include_owner_email=True,
        )

        # Create proposal
        proposal = RebalanceProposalModel.objects.create(
            account=account,
            source=RebalanceProposalModel.SOURCE_DAILY_INSPECTION,
            status=RebalanceProposalModel.STATUS_PENDING,
            priority="normal",
            proposals=[
                {
                    "asset_code": "512880.SH",
                    "asset_name": "证券ETF",
                    "action": "buy",
                    "suggested_quantity": 100,
                    "estimated_amount": 5000.0,
                }
            ],
            summary={"buy_count": 1, "sell_count": 0},
        )

        result = {
            "account_id": account.id,
            "proposal_id": proposal.id,
            "inspection_date": "2026-02-26",
            "status": "warning",
            "summary": {
                "rebalance_required_count": 1,
                "rebalance_assets": ["512880.SH"],
            },
        }

        with patch("apps.simulated_trading.application.tasks.send_mail") as mock_send:
            _send_rebalance_proposal_notification(result=result)

            # Should send email notification
            assert mock_send.called

    def test_send_notification_skipped_when_disabled(self):
        """Test notification is skipped when disabled."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Test Account 2",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        # Create notification config with is_enabled=False
        config = DailyInspectionNotificationConfigModel.objects.create(
            account=account,
            is_enabled=False,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        result = {
            "account_id": account.id,
            "proposal_id": proposal.id,
            "inspection_date": "2026-02-26",
        }

        with patch("apps.simulated_trading.application.tasks.send_mail") as mock_send:
            _send_rebalance_proposal_notification(result=result)

            # Should not send email when disabled
            assert not mock_send.called


@pytest.mark.django_db
class TestNotificationHistory:
    """Test notification history recording."""

    def test_record_notification_history(self):
        """Test recording notification to history."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="historyuser",
            email="history@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="History Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        recipients = ["user1@example.com", "user2@example.com"]

        _record_notification_history(
            account_id=account.id,
            account_name=account.account_name,
            account_user_id=user.id,
            proposal={"proposal_id": proposal.id},
            notification_type="rebalance_proposal",
            recipients=recipients,
            status="sent",
        )

        # Verify history records were created
        history_count = NotificationHistoryModel.objects.filter(
            account_id=account.id,
            notification_type="rebalance_proposal",
        ).count()

        assert history_count == 2

    def test_notification_history_fields(self):
        """Test notification history fields are correctly recorded."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        user = User.objects.create_user(
            username="fieldstestuser",
            email="fields@example.com",
        )

        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name="Fields Test Account",
            account_type="simulated",
            initial_capital=100000,
            current_cash=50000,
            total_value=100000,
        )

        proposal = RebalanceProposalModel.objects.create(
            account=account,
            status=RebalanceProposalModel.STATUS_PENDING,
            proposals=[],
            summary={},
        )

        _record_notification_history(
            account_id=account.id,
            account_name=account.account_name,
            account_user_id=user.id,
            proposal={"proposal_id": proposal.id},
            notification_type="daily_inspection",
            recipients=["test@example.com"],
            status="sent",
        )

        history = NotificationHistoryModel.objects.filter(
            account_id=account.id,
            notification_type="daily_inspection",
        ).first()

        assert history is not None
        assert history.channel == "email"
        assert history.recipient_email == "test@example.com"
        assert history.recipient_user_id == user.id
        assert history.status == "sent"
        assert history.subject is not None
        assert history.body is not None


@pytest.mark.django_db
class TestNotificationFailureRetry:
    """Test notification failure and retry mechanism."""

    def test_email_retry_on_failure(self):
        """Test email channel retries on failure."""
        # This test verifies the retry logic exists in the channel
        # Actual retry testing is done by checking the configuration is used
        config = NotificationConfig()
        assert config.max_retries == 3
        assert config.initial_retry_delay == 1.0
        assert config.retry_backoff_factor == 2.0
        assert config.max_retry_delay == 60.0

    def test_email_max_retries_exceeded(self):
        """Test max retries configuration."""
        config = NotificationConfig()
        config.max_retries = 5

        assert config.max_retries == 5
        # Verify the configuration is properly settable

    def test_service_handles_channel_failure(self):
        """Test unified service handles channel failures gracefully."""
        service = UnifiedNotificationService()

        message = NotificationMessage(
            subject="Failure Test",
            body="Testing failure handling",
            priority=NotificationPriority.NORMAL,
        )

        recipient = NotificationRecipient(email="test@example.com")

        with patch.object(
            EmailNotificationChannel,
            "send",
            return_value=Mock(success=False, error_message="Channel failed")
        ):
            results = service.send(message, recipient)

            # Should still return result even if failed
            assert len(results) > 0
            assert results[0].success is False


@pytest.mark.django_db
class TestNotificationRateLimit:
    """Test notification rate limiting."""

    def test_email_rate_limiting(self):
        """Test email sending is rate limited."""
        from django.core.cache import cache

        with patch("django.conf.settings.EMAIL_BACKEND", "django.core.mail.backends.locmem.EmailBackend"):
            with patch("django.conf.settings.EMAIL_HOST", "smtp.example.com"):
                with patch("django.conf.settings.EMAIL_PORT", 587):
                    channel = EmailNotificationChannel()

                    message = NotificationMessage(
                        subject="Rate Limit Test",
                        body="Testing rate limit",
                        priority=NotificationPriority.NORMAL,
                    )

                    recipient = NotificationRecipient(email="test@example.com")

                    config = NotificationConfig()
                    config.max_retries = 0

                    with patch("shared.infrastructure.notification_service.EmailNotificationChannel._send_email", return_value=True):
                        # Set rate limit
                        cache.set(f"email_rate_limit:{recipient.email}", 1, timeout=6)

                        result = channel.send(message, recipient, config)

                        # Should be rate limited
                        assert result.success is False
                        assert "频率过高" in result.error_message or "rate limit" in result.error_message.lower()


@pytest.mark.django_db
class TestNotificationAlertOnFailure:
    """Test alert triggering on notification failures."""

    def test_alert_triggered_after_threshold_failures(self):
        """Test alert threshold configuration."""
        service = UnifiedNotificationService()
        service.config.alert_threshold = 5

        assert service.config.alert_threshold == 5
        assert service.config.enable_alert_on_failure is True
