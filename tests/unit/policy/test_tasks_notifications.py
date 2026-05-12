"""
Unit Tests for Policy Tasks Notification Integration

测试 policy tasks 与通知服务的集成。
"""

from datetime import date, timedelta
from unittest.mock import Mock, patch

from apps.policy.application import tasks
from apps.policy.domain.entities import PolicyEvent, PolicyLevel


class TestNotificationServiceIntegration:
    """测试任务与通知服务的集成"""

    def setup_method(self):
        """每个测试前重置通知服务"""
        tasks._notification_service = None

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    def test_send_policy_alert_uses_notification_service(self, mock_get_notification):
        """测试 _send_policy_alert 使用通知服务"""
        # 创建模拟服务
        mock_alert_service = Mock()
        mock_alert_service.send_policy_alert.return_value = True
        mock_get_notification.return_value = mock_alert_service

        # 创建测试数据
        event = PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P2,
            title="Test Event",
            description="Test description",
            evidence_url="https://example.com"
        )

        status = Mock()
        status.level_name = "干预"

        # 调用函数
        tasks._send_policy_alert(PolicyLevel.P2, event, status)

        # 验证调用了通知服务
        mock_alert_service.send_policy_alert.assert_called_once_with(
            PolicyLevel.P2, event, status
        )

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    def test_send_transition_summary_uses_notification_service(self, mock_get_notification):
        """测试 _send_transition_summary 使用通知服务"""
        mock_alert_service = Mock()
        mock_alert_service.send_transition_summary.return_value = True
        mock_get_notification.return_value = mock_alert_service

        changes = [
            {"date": "2026-03-04", "from": "P0", "to": "P2", "title": "Change 1"},
        ]

        tasks._send_transition_summary(changes)

        mock_alert_service.send_transition_summary.assert_called_once_with(changes)

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    def test_send_policy_alert_handles_exception(self, mock_get_notification):
        """测试 _send_policy_alert 处理异常"""
        mock_alert_service = Mock()
        mock_alert_service.send_policy_alert.side_effect = Exception("Send failed")
        mock_get_notification.return_value = mock_alert_service

        event = PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P2,
            title="Test",
            description="Test",
            evidence_url="https://example.com"
        )
        status = Mock()

        # 不应该抛出异常
        tasks._send_policy_alert(PolicyLevel.P2, event, status)

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    def test_send_transition_summary_handles_exception(self, mock_get_notification):
        """测试 _send_transition_summary 处理异常"""
        mock_alert_service = Mock()
        mock_alert_service.send_transition_summary.side_effect = Exception("Send failed")
        mock_get_notification.return_value = mock_alert_service

        # 不应该抛出异常
        tasks._send_transition_summary([])


class TestMonitorSlaExceededTask:
    """测试 SLA 超时监控任务"""

    def setup_method(self):
        """每个测试前重置通知服务"""
        tasks._notification_service = None

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    @patch("apps.policy.application.tasks.get_workbench_repository")
    def test_sla_exceeded_sends_alert(
        self, mock_get_workbench_repository, mock_get_notification
    ):
        """测试 SLA 超时时发送告警"""
        # 设置模拟配置
        mock_config = Mock()
        mock_config.p23_sla_hours = 2
        mock_config.normal_sla_hours = 24
        mock_repo = mock_get_workbench_repository.return_value
        mock_repo.get_ingestion_config.return_value = mock_config
        mock_repo.get_sla_exceeded_breakdown.return_value = {
            "p23_exceeded": 3,
            "normal_exceeded": 5,
            "total_exceeded": 8,
        }

        # 设置模拟通知服务
        mock_alert_service = Mock()
        mock_get_notification.return_value = mock_alert_service

        # 执行任务
        result = tasks.monitor_sla_exceeded_task()

        # 验证告警被发送
        mock_alert_service.send_sla_alert.assert_called_once_with(3, 5)

        # 验证返回值
        assert result["status"] == "success"
        assert result["p23_exceeded"] == 3
        assert result["normal_exceeded"] == 5

    @patch("apps.policy.application.tasks.get_policy_notification_service")
    @patch("apps.policy.application.tasks.get_workbench_repository")
    def test_no_sla_exceeded_no_alert(
        self, mock_get_workbench_repository, mock_get_notification
    ):
        """测试无 SLA 超时不发送告警"""
        mock_config = Mock()
        mock_config.p23_sla_hours = 2
        mock_config.normal_sla_hours = 24
        mock_repo = mock_get_workbench_repository.return_value
        mock_repo.get_ingestion_config.return_value = mock_config
        mock_repo.get_sla_exceeded_breakdown.return_value = {
            "p23_exceeded": 0,
            "normal_exceeded": 0,
            "total_exceeded": 0,
        }

        mock_alert_service = Mock()
        mock_get_notification.return_value = mock_alert_service

        result = tasks.monitor_sla_exceeded_task()

        # 不应该发送告警
        mock_alert_service.send_sla_alert.assert_not_called()

        assert result["status"] == "success"
        assert result["total_exceeded"] == 0


class TestCheckPolicyStatusAlert:
    """测试政策状态检查任务"""

    @patch('apps.policy.application.tasks._send_policy_alert')
    @patch('apps.policy.application.tasks.GetPolicyStatusUseCase')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_sends_alert_for_p2_level(
        self, mock_get_repository, mock_use_case_cls, mock_send_alert
    ):
        """测试 P2 档位发送告警"""
        # 创建模拟状态
        mock_status = Mock()
        mock_status.current_level = PolicyLevel.P2

        mock_event = PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P2,
            title="P2 Event",
            description="P2 Description",
            evidence_url="https://example.com"
        )
        mock_status.latest_event = mock_event

        mock_use_case_cls.return_value.execute.return_value = mock_status

        # 执行任务
        tasks.check_policy_status_alert("2026-03-04")

        # 验证告警被发送
        mock_send_alert.assert_called_once()
        call_args = mock_send_alert.call_args
        assert call_args[1]["level"] == PolicyLevel.P2
        assert call_args[1]["event"] == mock_event

    @patch('apps.policy.application.tasks._send_policy_alert')
    @patch('apps.policy.application.tasks.GetPolicyStatusUseCase')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_sends_alert_for_p3_level(
        self, mock_get_repository, mock_use_case_cls, mock_send_alert
    ):
        """测试 P3 档位发送告警"""
        mock_status = Mock()
        mock_status.current_level = PolicyLevel.P3

        mock_event = PolicyEvent(
            event_date=date(2026, 3, 4),
            level=PolicyLevel.P3,
            title="P3 Event",
            description="P3 Description",
            evidence_url="https://example.com"
        )
        mock_status.latest_event = mock_event

        mock_use_case_cls.return_value.execute.return_value = mock_status

        tasks.check_policy_status_alert("2026-03-04")

        mock_send_alert.assert_called_once()

    @patch('apps.policy.application.tasks._send_policy_alert')
    @patch('apps.policy.application.tasks.GetPolicyStatusUseCase')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_no_alert_for_p0_p1_levels(
        self, mock_get_repository, mock_use_case_cls, mock_send_alert
    ):
        """测试 P0/P1 档位不发送告警"""
        for level in [PolicyLevel.P0, PolicyLevel.P1]:
            mock_status = Mock()
            mock_status.current_level = level
            mock_status.latest_event = Mock()

            mock_use_case_cls.return_value.execute.return_value = mock_status

            tasks.check_policy_status_alert("2026-03-04")

            # P0/P1 不应该发送告警
            mock_send_alert.assert_not_called()


class TestMonitorPolicyTransitions:
    """测试政策档位变更监控任务"""

    @patch('apps.policy.application.tasks._send_transition_summary')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_sends_summary_on_transitions(
        self, mock_get_repository, mock_send_summary
    ):
        """测试有档位变更时发送摘要"""
        today = date(2026, 3, 4)
        yesterday = today - timedelta(days=1)

        # 创建模拟事件（有档位变更）
        event1 = PolicyEvent(yesterday, PolicyLevel.P0, "Event 1", "Desc 1", "url1")
        event2 = PolicyEvent(today, PolicyLevel.P2, "Event 2", "Desc 2", "url2")

        mock_get_repository.return_value.get_events_in_range.return_value = [event1, event2]

        tasks.monitor_policy_transitions()

        # 应该发送变更摘要
        mock_send_summary.assert_called_once()
        call_args = mock_send_summary.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["from"] == "P0"
        assert call_args[0]["to"] == "P2"

    @patch('apps.policy.application.tasks._send_transition_summary')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_no_summary_on_same_level(
        self, mock_get_repository, mock_send_summary
    ):
        """测试无档位变更时不发送摘要"""
        today = date(2026, 3, 4)
        yesterday = today - timedelta(days=1)

        # 创建模拟事件（相同档位）
        event1 = PolicyEvent(yesterday, PolicyLevel.P0, "Event 1", "Desc 1", "url1")
        event2 = PolicyEvent(today, PolicyLevel.P0, "Event 2", "Desc 2", "url2")

        mock_get_repository.return_value.get_events_in_range.return_value = [event1, event2]

        tasks.monitor_policy_transitions()

        # 不应该发送变更摘要
        mock_send_summary.assert_not_called()

    @patch('apps.policy.application.tasks._send_transition_summary')
    @patch('apps.policy.application.tasks.get_current_policy_repository')
    def test_handles_insufficient_events(
        self, mock_get_repository, mock_send_summary
    ):
        """测试事件不足时处理"""
        mock_get_repository.return_value.get_events_in_range.return_value = [
            PolicyEvent(date(2026, 3, 4), PolicyLevel.P0, "Event", "Desc", "url")
        ]

        result = tasks.monitor_policy_transitions()

        # 不应该发送变更摘要
        mock_send_summary.assert_not_called()
        assert result["transitions_found"] == 0
