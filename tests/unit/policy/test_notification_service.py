"""
Unit Tests for Policy Notification Service

测试通知服务的各个组件：
- NotificationMessage 实体
- LoggingNotificationService
- EmailNotificationService
- InAppNotificationService
- PolicyAlertService
"""

import logging
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, datetime, timezone

from apps.policy.domain.interfaces import (
    NotificationMessage,
    NotificationChannel,
    NotificationServicePort,
    PolicyAlertServicePort,
)
from apps.policy.domain.entities import PolicyLevel, PolicyEvent
from apps.policy.infrastructure.notification_service import (
    LoggingNotificationService,
    EmailNotificationService,
    InAppNotificationService,
    PolicyAlertService,
    NotificationServiceFactory,
)


class TestNotificationMessage:
    """测试 NotificationMessage 实体"""

    def test_create_minimal_message(self):
        """测试创建最小消息"""
        msg = NotificationMessage(
            title="Test",
            content="Test content"
        )
        assert msg.title == "Test"
        assert msg.content == "Test content"
        assert msg.channel == NotificationChannel.IN_APP
        assert msg.priority == "normal"
        assert msg.recipients == []
        assert msg.metadata == {}

    def test_create_full_message(self):
        """测试创建完整消息"""
        msg = NotificationMessage(
            title="Alert",
            content="Important",
            channel=NotificationChannel.EMAIL,
            priority="high",
            recipients=["user@example.com"],
            metadata={"key": "value"}
        )
        assert msg.title == "Alert"
        assert msg.channel == NotificationChannel.EMAIL
        assert msg.priority == "high"
        assert msg.recipients == ["user@example.com"]
        assert msg.metadata == {"key": "value"}


class TestLoggingNotificationService:
    """测试日志通知服务"""

    @pytest.fixture
    def service(self):
        return LoggingNotificationService(enabled=True)

    def test_send_logs_message(self, service, caplog):
        """测试发送消息记录日志"""
        msg = NotificationMessage(
            title="Test Alert",
            content="Test content",
            priority="high"
        )

        result = service.send(msg)

        assert result is True
        assert "Test Alert" in caplog.text

    def test_send_disabled(self, caplog):
        """测试禁用状态"""
        service = LoggingNotificationService(enabled=False)
        msg = NotificationMessage(title="Test", content="Content")

        result = service.send(msg)

        assert result is True
        # 不应该有日志
        assert "Test" not in caplog.text

    def test_send_batch(self, service):
        """测试批量发送"""
        messages = [
            NotificationMessage(title=f"Msg {i}", content=f"Content {i}")
            for i in range(3)
        ]

        result = service.send_batch(messages)

        assert result["success"] == 3
        assert result["failed"] == 0
        assert result["errors"] == []

    def test_get_log_level(self, service):
        """测试日志级别映射"""
        assert service._get_log_level("critical") == "error"
        assert service._get_log_level("high") == "warning"
        assert service._get_log_level("normal") == "info"
        assert service._get_log_level("low") == "debug"
        assert service._get_log_level("unknown") == "info"


class TestEmailNotificationService:
    """测试邮件通知服务"""

    @pytest.fixture
    def service(self):
        return EmailNotificationService(
            enabled=True,
            default_recipients=["admin@example.com"]
        )

    def test_send_with_recipients(self, service):
        """测试发送邮件给指定收件人"""
        msg = NotificationMessage(
            title="Test Alert",
            content="Test content",
            channel=NotificationChannel.EMAIL,
            recipients=["user@example.com"]
        )

        with patch('apps.policy.infrastructure.notification_service.send_mail') as mock_send:
            mock_send.return_value = True
            result = service.send(msg)

            assert result is True
            mock_send.assert_called_once()

    def test_send_uses_default_recipients(self, service):
        """测试使用默认收件人"""
        msg = NotificationMessage(
            title="Test",
            content="Content",
            channel=NotificationChannel.EMAIL
        )

        with patch('apps.policy.infrastructure.notification_service.send_mail') as mock_send:
            mock_send.return_value = True
            result = service.send(msg)

            assert result is True
            # 应该使用默认收件人
            call_args = mock_send.call_args
            assert "admin@example.com" in call_args[1]["recipient_list"]

    def test_send_no_recipients(self, service):
        """测试没有收件人的情况"""
        # 创建没有默认收件人的服务
        service = EmailNotificationService(enabled=True, default_recipients=[])
        msg = NotificationMessage(
            title="Test",
            content="Content",
            channel=NotificationChannel.EMAIL,
            recipients=[]
        )

        result = service.send(msg)

        assert result is False

    def test_send_fallback_to_logging(self, service, caplog):
        """测试邮件发送失败时降级到日志"""
        caplog.set_level(logging.DEBUG)
        msg = NotificationMessage(
            title="Test",
            content="Content",
            channel=NotificationChannel.EMAIL
        )

        with patch('apps.policy.infrastructure.notification_service.send_mail') as mock_send:
            mock_send.side_effect = Exception("SMTP error")
            result = service.send(msg)

            # 应该降级到日志
            assert result is True
            # 检查日志中包含通知信息（可能是 INFO 级别）
            assert "Test" in caplog.text or "[Notification]" in caplog.text

    def test_send_batch_merges_email(self, service):
        """测试批量发送合并邮件"""
        messages = [
            NotificationMessage(
                title=f"Msg {i}",
                content=f"Content {i}",
                channel=NotificationChannel.EMAIL
            )
            for i in range(3)
        ]

        with patch('apps.policy.infrastructure.notification_service.send_mail') as mock_send:
            mock_send.return_value = True
            result = service.send_batch(messages)

            assert result["success"] == 3
            # 应该只发送一封合并邮件
            assert mock_send.call_count == 1

    def test_get_priority_prefix(self, service):
        """测试优先级前缀"""
        assert service._get_priority_prefix("critical") == "[CRITICAL]"
        assert service._get_priority_prefix("high") == "[HIGH]"
        assert service._get_priority_prefix("normal") == "[INFO]"
        assert service._get_priority_prefix("low") == "[LOW]"


class TestInAppNotificationService:
    """测试站内通知服务"""

    @pytest.fixture
    def service(self):
        return InAppNotificationService(enabled=True)

    def test_send_with_recipients(self, service):
        """测试发送给指定用户"""
        msg = NotificationMessage(
            title="Test",
            content="Content",
            recipients=["user1", "user2"]
        )

        with patch('apps.policy.infrastructure.models.InAppNotification.objects') as mock_manager:
            result = service.send(msg)

            assert result is True
            # 应该为每个用户创建通知
            assert mock_manager.create.call_count == 2

    def test_send_global_notification(self, service):
        """测试发送全局通知"""
        msg = NotificationMessage(
            title="Global Alert",
            content="Important"
        )

        with patch('apps.policy.infrastructure.models.InAppNotification.objects') as mock_manager:
            result = service.send(msg)

            assert result is True
            call_kwargs = mock_manager.create.call_args[1]
            assert call_kwargs["is_global"] is True

    def test_send_disabled(self):
        """测试禁用状态"""
        service = InAppNotificationService(enabled=False)
        msg = NotificationMessage(title="Test", content="Content")

        result = service.send(msg)

        assert result is True

    def test_send_batch(self, service):
        """测试批量发送"""
        messages = [
            NotificationMessage(title=f"Msg {i}", content=f"Content {i}")
            for i in range(3)
        ]

        with patch('apps.policy.infrastructure.models.InAppNotification.objects') as mock_manager:
            result = service.send_batch(messages)

            assert result["success"] == 3


class TestPolicyAlertService:
    """测试政策告警服务"""

    @pytest.fixture
    def mock_email_service(self):
        return Mock(spec=EmailNotificationService)

    @pytest.fixture
    def mock_in_app_service(self):
        return Mock(spec=InAppNotificationService)

    @pytest.fixture
    def service(self, mock_email_service, mock_in_app_service):
        return PolicyAlertService(
            email_service=mock_email_service,
            in_app_service=mock_in_app_service
        )

    @pytest.fixture
    def sample_event(self):
        return PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P2,
            title="Test Policy Event",
            description="Test description",
            evidence_url="https://example.com/evidence"
        )

    @pytest.fixture
    def sample_status(self):
        """创建模拟的状态对象"""
        status = Mock()
        status.level_name = "干预"
        status.response_config.cash_adjustment = 10
        status.response_config.market_action.value = "reduce_position"
        status.response_config.signal_pause_hours = 24
        status.recommendations = ["建议1", "建议2"]
        return status

    def test_send_policy_alert_p3(self, service, sample_event, sample_status, mock_email_service, mock_in_app_service):
        """测试发送 P3 告警"""
        sample_event = PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P3,
            title="Critical Event",
            description="Critical description",
            evidence_url="https://example.com"
        )

        mock_email_service.send.return_value = True
        mock_in_app_service.send.return_value = True

        result = service.send_policy_alert(PolicyLevel.P3, sample_event, sample_status)

        assert result is True
        mock_email_service.send.assert_called_once()
        mock_in_app_service.send.assert_called_once()

        # 检查邮件消息的优先级
        email_msg = mock_email_service.send.call_args[0][0]
        assert email_msg.priority == "critical"

    def test_send_policy_alert_p2(self, service, sample_event, sample_status, mock_email_service, mock_in_app_service):
        """测试发送 P2 告警"""
        mock_email_service.send.return_value = True
        mock_in_app_service.send.return_value = True

        result = service.send_policy_alert(PolicyLevel.P2, sample_event, sample_status)

        assert result is True

        email_msg = mock_email_service.send.call_args[0][0]
        assert email_msg.priority == "warning"

    def test_send_transition_summary(self, service, mock_email_service, mock_in_app_service):
        """测试发送变更摘要"""
        changes = [
            {"date": "2026-03-04", "from": "P0", "to": "P2", "title": "Change 1"},
            {"date": "2026-03-04", "from": "P2", "to": "P3", "title": "Change 2"},
        ]

        mock_email_service.send.return_value = True
        mock_in_app_service.send.return_value = True

        result = service.send_transition_summary(changes)

        assert result is True
        mock_email_service.send.assert_called_once()
        mock_in_app_service.send.assert_called_once()

    def test_send_transition_summary_empty(self, service, mock_email_service, mock_in_app_service):
        """测试空变更列表"""
        result = service.send_transition_summary([])

        assert result is True
        mock_email_service.send.assert_not_called()
        mock_in_app_service.send.assert_not_called()

    def test_send_sla_alert(self, service, mock_email_service, mock_in_app_service):
        """测试发送 SLA 告警"""
        mock_email_service.send.return_value = True
        mock_in_app_service.send.return_value = True

        result = service.send_sla_alert(p23_count=5, normal_count=10)

        assert result is True
        mock_email_service.send.assert_called_once()
        mock_in_app_service.send.assert_called_once()

        # 检查消息内容
        email_msg = mock_email_service.send.call_args[0][0]
        assert "SLA 超时警告" in email_msg.content
        assert "P2/P3 超时: 5" in email_msg.content
        assert "普通超时: 10" in email_msg.content

    def test_send_sla_alert_no_exceeded(self, service, mock_email_service, mock_in_app_service):
        """测试无 SLA 超时"""
        result = service.send_sla_alert(p23_count=0, normal_count=0)

        assert result is True
        mock_email_service.send.assert_not_called()
        mock_in_app_service.send.assert_not_called()

    def test_build_alert_content(self, service, sample_event, sample_status):
        """测试告警内容构建"""
        content = service._build_alert_content(
            PolicyLevel.P2,
            sample_event,
            sample_status,
            "warning"
        )

        assert "政策状态告警" in content
        assert "P2 - 干预" in content
        assert "Test Policy Event" in content
        assert "现金调整: +10%" in content
        assert "信号暂停: 24 小时" in content

    def test_build_transition_content(self, service):
        """测试变更摘要内容构建"""
        changes = [
            {"date": "2026-03-04", "from": "P0", "to": "P2", "title": "Change 1"},
        ]
        content = service._build_transition_content(changes)

        assert "政策档位变更摘要" in content
        assert "2026-03-04: P0 -> P2" in content
        assert "Change 1" in content


class TestNotificationServiceFactory:
    """测试通知服务工厂"""

    def teardown_method(self):
        """每个测试后重置单例"""
        NotificationServiceFactory.reset()

    def test_get_email_service_singleton(self):
        """测试邮件服务单例"""
        service1 = NotificationServiceFactory.get_email_service()
        service2 = NotificationServiceFactory.get_email_service()

        assert service1 is service2

    def test_get_in_app_service_singleton(self):
        """测试站内通知服务单例"""
        service1 = NotificationServiceFactory.get_in_app_service()
        service2 = NotificationServiceFactory.get_in_app_service()

        assert service1 is service2

    def test_get_alert_service_singleton(self):
        """测试告警服务单例"""
        service1 = NotificationServiceFactory.get_alert_service()
        service2 = NotificationServiceFactory.get_alert_service()

        assert service1 is service2

    @patch('apps.policy.infrastructure.notification_service.settings')
    def test_email_service_uses_settings(self, mock_settings):
        """测试邮件服务使用设置"""
        mock_settings.POLICY_ALERT_EMAILS = ["test@example.com"]
        mock_settings.POLICY_EMAIL_NOTIFICATIONS_ENABLED = True

        service = NotificationServiceFactory.get_email_service()

        assert service.default_recipients == ["test@example.com"]
        assert service.enabled is True

    def test_reset(self):
        """测试重置工厂"""
        service1 = NotificationServiceFactory.get_email_service()
        NotificationServiceFactory.reset()
        service2 = NotificationServiceFactory.get_email_service()

        assert service1 is not service2
