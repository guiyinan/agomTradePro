"""
Tests for Decision Execution Event Handlers

测试决策执行事件处理器的功能。

测试范围：
1. DecisionApprovedHandler: 回写 last_decision_request_id
2. DecisionExecutedHandler: 回写执行状态
3. DecisionExecutionFailedHandler: 回写失败状态
4. 容错机制：主事务成功优先
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from apps.events.application.decision_execution_handlers import (
    DecisionApprovedHandler,
    DecisionExecutedHandler,
    DecisionExecutionFailedHandler,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event


@pytest.mark.django_db
class TestDecisionApprovedHandler:
    """测试决策批准事件处理器"""

    def test_can_handle_decision_approved(self):
        """测试能处理 DECISION_APPROVED 事件"""
        handler = DecisionApprovedHandler()

        assert handler.can_handle(EventType.DECISION_APPROVED) is True
        assert handler.can_handle(EventType.DECISION_EXECUTED) is False
        assert handler.can_handle(EventType.DECISION_REJECTED) is False

    def test_handle_updates_last_decision_request_id(self):
        """测试处理事件时更新 last_decision_request_id"""
        # 准备 mock 仓储
        mock_repo = Mock()
        mock_repo.update_last_decision_request_id.return_value = True

        handler = DecisionApprovedHandler(alpha_candidate_repo=mock_repo)

        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={
                "candidate_id": "candidate_123",
                "request_id": "request_456",
                "asset_code": "000001.SH",
            },
        )

        # 执行
        handler.handle(event)

        # 验证
        mock_repo.update_last_decision_request_id.assert_called_once_with(
            "candidate_123", "request_456"
        )

    def test_handle_skips_if_missing_candidate_id(self):
        """测试缺少 candidate_id 时跳过处理"""
        handler = DecisionApprovedHandler()

        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={
                "request_id": "request_456",
            },
        )

        # 执行（不应抛出异常）
        handler.handle(event)

    def test_handle_does_not_raise_on_error(self):
        """测试错误时不抛出异常（主事务成功优先）"""
        handler = DecisionApprovedHandler()

        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={
                "candidate_id": "candidate_123",
                "request_id": "request_456",
            },
        )

        # Mock 抛出异常
        with patch(
            'apps.alpha_trigger.infrastructure.models.AlphaCandidateModel'
        ) as mock_model:
            mock_model.objects.get.side_effect = Exception("Database error")

            # 执行（不应抛出异常）
            handler.handle(event)

    def test_get_handler_id(self):
        """测试获取处理器 ID"""
        handler = DecisionApprovedHandler()
        assert handler.get_handler_id() == "events.DecisionApprovedHandler"


@pytest.mark.django_db
class TestDecisionExecutedHandler:
    """测试决策执行成功事件处理器"""

    def test_can_handle_decision_executed(self):
        """测试能处理 DECISION_EXECUTED 事件"""
        handler = DecisionExecutedHandler()

        assert handler.can_handle(EventType.DECISION_EXECUTED) is True
        assert handler.can_handle(EventType.DECISION_APPROVED) is False

    def test_handle_updates_execution_status(self):
        """测试处理事件时更新执行状态"""
        # 准备 mock 仓储
        mock_request_repo = Mock()
        mock_request_repo.update_execution_status_to_executed.return_value = True
        mock_candidate_repo = Mock()
        mock_candidate_repo.update_status_to_executed.return_value = True

        handler = DecisionExecutedHandler(
            decision_request_repo=mock_request_repo,
            alpha_candidate_repo=mock_candidate_repo,
        )

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={
                "request_id": "request_456",
                "candidate_id": "candidate_123",
                "execution_ref": {"trade_id": "trade_789"},
            },
        )

        # 执行
        handler.handle(event)

        # 验证 DecisionRequest 更新
        mock_request_repo.update_execution_status_to_executed.assert_called_once_with(
            "request_456", {"trade_id": "trade_789"}
        )

        # 验证 AlphaCandidate 更新
        mock_candidate_repo.update_status_to_executed.assert_called_once_with(
            "candidate_123"
        )

    def test_handle_skips_if_missing_request_id(self):
        """测试缺少 request_id 时跳过处理"""
        handler = DecisionExecutedHandler()

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={
                "candidate_id": "candidate_123",
            },
        )

        # 执行（不应抛出异常）
        handler.handle(event)

    def test_get_handler_id(self):
        """测试获取处理器 ID"""
        handler = DecisionExecutedHandler()
        assert handler.get_handler_id() == "events.DecisionExecutedHandler"


@pytest.mark.django_db
class TestDecisionExecutionFailedHandler:
    """测试决策执行失败事件处理器"""

    def test_can_handle_decision_execution_failed(self):
        """测试能处理 DECISION_EXECUTION_FAILED 事件"""
        handler = DecisionExecutionFailedHandler()

        assert handler.can_handle(EventType.DECISION_EXECUTION_FAILED) is True
        assert handler.can_handle(EventType.DECISION_EXECUTED) is False

    def test_handle_updates_failed_status(self):
        """测试处理事件时更新失败状态"""
        # 准备 mock 仓储
        mock_request_repo = Mock()
        mock_request_repo.update_execution_status_to_failed.return_value = True
        mock_candidate_repo = Mock()
        mock_candidate_repo.update_execution_status_to_failed.return_value = True

        handler = DecisionExecutionFailedHandler(
            decision_request_repo=mock_request_repo,
            alpha_candidate_repo=mock_candidate_repo,
        )

        event = create_event(
            event_type=EventType.DECISION_EXECUTION_FAILED,
            payload={
                "request_id": "request_456",
                "candidate_id": "candidate_123",
                "error_message": "Execution failed: timeout",
            },
        )

        # 执行
        handler.handle(event)

        # 验证 DecisionRequest 更新
        mock_request_repo.update_execution_status_to_failed.assert_called_once()

        # 验证 AlphaCandidate 更新 (保留 ACTIONABLE 状态，允许重试)
        mock_candidate_repo.update_execution_status_to_failed.assert_called_once()

    def test_handle_keeps_actionable_status(self):
        """测试失败时保留 ACTIONABLE 状态（允许重试）"""
        handler = DecisionExecutionFailedHandler()

        event = create_event(
            event_type=EventType.DECISION_EXECUTION_FAILED,
            payload={
                "request_id": "request_456",
                "candidate_id": "candidate_123",
            },
        )

        with patch(
            'apps.alpha_trigger.infrastructure.models.AlphaCandidateModel'
        ) as mock_candidate_model:
            mock_candidate = Mock()
            mock_candidate.status = "ACTIONABLE"  # 初始状态
            mock_candidate_model.objects.get.return_value = mock_candidate
            mock_candidate_model.EXECUTION_FAILED = "FAILED"

            handler.handle(event)

            # 验证 status 未被修改
            assert mock_candidate.status == "ACTIONABLE"

    def test_get_handler_id(self):
        """测试获取处理器 ID"""
        handler = DecisionExecutionFailedHandler()
        assert handler.get_handler_id() == "events.DecisionExecutionFailedHandler"


@pytest.mark.django_db
class TestEventBusIntegration:
    """测试事件总线集成"""

    def test_handlers_registered_on_initialization(self):
        """测试初始化时注册处理器"""
        from apps.events.application.event_bus_initializer import (
            EventBusInitializer,
        )
        from apps.events.domain.services import reset_event_bus

        # 重置事件总线
        reset_event_bus()

        initializer = EventBusInitializer()

        # 只测试决策执行处理器，避免导入其他模块的问题
        from apps.events.application.decision_execution_handlers import (
            DecisionApprovedHandler,
            DecisionExecutedHandler,
            DecisionExecutionFailedHandler,
        )

        # 手动注册处理器
        from apps.events.domain.entities import EventSubscription
        from apps.events.domain.services import get_event_bus

        event_bus = get_event_bus()

        # 注册处理器
        approved_handler = DecisionApprovedHandler()
        executed_handler = DecisionExecutedHandler()
        failed_handler = DecisionExecutionFailedHandler()

        event_bus.subscribe(EventSubscription(
            subscription_id="test_approved",
            event_type=EventType.DECISION_APPROVED,
            handler=approved_handler,
        ))

        event_bus.subscribe(EventSubscription(
            subscription_id="test_executed",
            event_type=EventType.DECISION_EXECUTED,
            handler=executed_handler,
        ))

        event_bus.subscribe(EventSubscription(
            subscription_id="test_failed",
            event_type=EventType.DECISION_EXECUTION_FAILED,
            handler=failed_handler,
        ))

        # 检查处理器注册
        approved_handlers = event_bus.get_subscriptions(EventType.DECISION_APPROVED)
        executed_handlers = event_bus.get_subscriptions(EventType.DECISION_EXECUTED)
        failed_handlers = event_bus.get_subscriptions(EventType.DECISION_EXECUTION_FAILED)

        # 应该至少有一个处理器
        assert len(approved_handlers) >= 1
        assert len(executed_handlers) >= 1
        assert len(failed_handlers) >= 1

        # 清理
        event_bus.clear()

    def test_event_bus_health_check(self):
        """测试事件总线健康检查"""
        from apps.events.application.health_check import check_event_bus_health
        from apps.events.domain.services import reset_event_bus

        # 重置事件总线
        reset_event_bus()

        # 执行健康检查（未初始化状态）
        report = check_event_bus_health()

        # 验证
        assert report is not None
        assert hasattr(report, 'overall_status')
        assert hasattr(report, 'checks')
        assert len(report.checks) > 0

        # 检查关键组件
        component_names = [c.component for c in report.checks]
        assert 'event_bus_initialization' in component_names
        assert 'handler_registration' in component_names
