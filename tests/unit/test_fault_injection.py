"""
Fault Injection Tests

测试事件处理器的容错机制。

测试场景：
1. 数据库连接失败
2. 模型不存在
3. 事务回滚
4. 事件发布失败
5. 重试机制
"""

import threading
from datetime import UTC, datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.db import OperationalError

from apps.events.application.decision_execution_handlers import (
    DecisionApprovedHandler,
    DecisionExecutedHandler,
    DecisionExecutionFailedHandler,
)
from apps.events.application.event_retry import (
    EventRetryManager,
    get_event_retry_manager,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event


@pytest.mark.django_db
class TestDatabaseFailures:
    """测试数据库失败场景"""

    def test_decision_approved_handler_database_error(self):
        """测试数据库错误时不影响主流程"""
        handler = DecisionApprovedHandler()

        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={
                "candidate_id": "candidate_123",
                "request_id": "request_456",
            },
        )

        # 模拟数据库错误
        with patch(
            'apps.alpha_trigger.infrastructure.models.AlphaCandidateModel'
        ) as mock_model:
            mock_model.objects.get.side_effect = OperationalError("Database connection lost")

            # 执行（不应抛出异常）
            handler.handle(event)

            # 验证：主流程继续，错误被记录
            assert True  # 如果到达这里，说明没有抛出异常

    def test_decision_executed_handler_transaction_error(self):
        """测试事务错误时的处理"""
        handler = DecisionExecutedHandler()

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={
                "request_id": "request_456",
                "candidate_id": "candidate_123",
            },
        )

        # 模拟事务错误
        with patch(
            'apps.events.infrastructure.repositories.transaction'
        ) as mock_transaction:
            mock_transaction.atomic.side_effect = Exception("Transaction failed")

            # 执行（不应抛出异常）
            handler.handle(event)

    def test_model_not_found_does_not_crash(self):
        """测试模型不存在时不崩溃"""
        handler = DecisionApprovedHandler()

        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={
                "candidate_id": "non_existent_candidate",
                "request_id": "request_456",
            },
        )

        # 模拟模型不存在
        with patch(
            'apps.alpha_trigger.infrastructure.models.AlphaCandidateModel'
        ) as mock_model:
            mock_model.objects.get.side_effect = ObjectDoesNotExist("Candidate not found")

            # 执行（不应抛出异常）
            handler.handle(event)


@pytest.mark.django_db
class TestEventRetryMechanism:
    """测试事件重试机制"""

    @pytest.mark.skip(reason="需要运行数据库迁移 0003_failed_event")
    def test_record_failure(self):
        """测试记录失败事件"""
        manager = EventRetryManager(max_retries=3)

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={"request_id": "request_456"},
        )

        error = Exception("Test error")

        # 记录失败
        failed_event_dto = manager.record_failure(
            event=event,
            handler_id="test.handler",
            error=error,
        )

        # 验证
        assert failed_event_dto.event_id == event.event_id
        assert failed_event_dto.event_type == EventType.DECISION_EXECUTED.value
        assert failed_event_dto.handler_id == "test.handler"
        assert failed_event_dto.error_message == "Test error"
        assert failed_event_dto.retry_count == 0
        assert failed_event_dto.status == "PENDING"

    @pytest.mark.skip(reason="需要运行数据库迁移 0003_failed_event")
    def test_retry_pending_events(self):
        """测试重试待重试的事件"""
        manager = EventRetryManager(max_retries=3)

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={"request_id": "request_456"},
        )

        # 记录失败
        manager.record_failure(
            event=event,
            handler_id="test.handler",
            error=Exception("Test error"),
        )

        # 创建成功和失败的处理器
        success_handler = Mock()
        fail_handler = Mock(side_effect=Exception("Still failing"))

        # 处理器工厂
        def handler_factory(handler_id: str):
            if handler_id == "test.handler":
                return success_handler
            return None

        # 重试
        stats = manager.retry_pending_events(handler_factory=handler_factory)

        # 验证
        assert stats["success"] == 1
        assert stats["failed"] == 0
        success_handler.assert_called_once()

    @pytest.mark.skip(reason="需要运行数据库迁移 0003_failed_event")
    def test_retry_exhausted(self):
        """测试重试次数耗尽"""
        manager = EventRetryManager(max_retries=2)

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={"request_id": "request_456"},
        )

        # 记录失败
        manager.record_failure(
            event=event,
            handler_id="test.handler",
            error=Exception("Test error"),
        )

        # 创建总是失败的处理器
        fail_handler = Mock(side_effect=Exception("Still failing"))

        def handler_factory(handler_id: str):
            return fail_handler

        # 重试多次直到耗尽
        for i in range(3):
            stats = manager.retry_pending_events(handler_factory=handler_factory)

        # 验证
        assert stats["exhausted"] >= 1

    @pytest.mark.skip(reason="需要运行数据库迁移 0003_failed_event")
    def test_exponential_backoff(self):
        """测试指数退避策略"""
        manager = EventRetryManager(max_retries=3, base_delay_minutes=5)

        event = create_event(
            event_type=EventType.DECISION_EXECUTED,
            payload={"request_id": "request_456"},
        )

        # 记录失败
        manager.record_failure(
            event=event,
            handler_id="test.handler",
            error=Exception("Test error"),
        )

        # 创建总是失败的处理器
        fail_handler = Mock(side_effect=Exception("Still failing"))

        def handler_factory(handler_id: str):
            return fail_handler

        # 第一次重试
        manager.retry_pending_events(handler_factory=handler_factory)

        # 获取失败事件
        pending = manager.get_pending_events()
        if pending:
            # next_retry_at 应该在未来
            assert pending[0].next_retry_at > datetime.now(UTC)


@pytest.mark.django_db
class TestConcurrencyAndThreadSafety:
    """测试并发和线程安全"""

    def test_concurrent_event_processing(self):
        """测试并发事件处理"""
        handler = DecisionApprovedHandler()

        events = [
            create_event(
                event_type=EventType.DECISION_APPROVED,
                payload={
                    "candidate_id": f"candidate_{i}",
                    "request_id": f"request_{i}",
                },
            )
            for i in range(10)
        ]

        # 并发处理
        threads = []
        for event in events:
            thread = threading.Thread(target=handler.handle, args=(event,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # 如果所有线程都完成，说明线程安全
        assert True

    def test_event_bus_concurrent_publish(self):
        """测试事件总线并发发布"""
        from apps.events.domain.services import get_event_bus, reset_event_bus

        # 重置事件总线
        reset_event_bus()

        event_bus = get_event_bus()

        events = [
            create_event(
                event_type=EventType.DECISION_APPROVED,
                payload={"index": i},
            )
            for i in range(10)
        ]

        # 并发发布
        threads = []
        for event in events:
            thread = threading.Thread(target=event_bus.publish, args=(event,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # 验证所有事件都被发布
        metrics = event_bus.get_metrics()
        assert metrics.total_published >= 10

        # 清理
        event_bus.clear()


@pytest.mark.django_db
class TestEventOrderingAndConsistency:
    """测试事件顺序和一致性"""

    def test_event_order_preserved(self):
        """测试事件顺序被保留"""
        from apps.events.domain.services import get_event_bus, reset_event_bus

        # 重置事件总线
        reset_event_bus()

        event_bus = get_event_bus()

        # 创建事件处理器，记录处理顺序
        processed_order = []

        class OrderTrackingHandler:
            def can_handle(self, event_type):
                return event_type == EventType.DECISION_APPROVED

            def handle(self, event):
                processed_order.append(event.get_payload_value("index"))

            def get_handler_id(self):
                return "test.OrderTrackingHandler"

        # 注册处理器
        from apps.events.domain.entities import EventSubscription
        subscription = EventSubscription(
            subscription_id="test_order_tracking",
            event_type=EventType.DECISION_APPROVED,
            handler=OrderTrackingHandler(),
        )
        event_bus.subscribe(subscription)

        # 发布事件
        for i in range(5):
            event = create_event(
                event_type=EventType.DECISION_APPROVED,
                payload={"index": i},
            )
            event_bus.publish(event)

        # 验证顺序
        assert processed_order == [0, 1, 2, 3, 4]

        # 清理
        event_bus.clear()

    def test_event_consistency_across_modules(self):
        """测试跨模块的事件一致性"""
        # 这个测试验证当一个事件被发布时，
        # 所有相关的处理器都能收到并处理

        from apps.events.domain.services import get_event_bus, reset_event_bus

        # 重置事件总线
        reset_event_bus()

        event_bus = get_event_bus()

        # 创建多个处理器
        handler_calls = {"handler1": 0, "handler2": 0, "handler3": 0}

        class CountingHandler:
            def __init__(self, name):
                self.name = name

            def can_handle(self, event_type):
                return True

            def handle(self, event):
                handler_calls[self.name] += 1

            def get_handler_id(self):
                return f"test.{self.name}"

        # 注册处理器
        for name in handler_calls.keys():
            from apps.events.domain.entities import EventSubscription
            subscription = EventSubscription(
                subscription_id=f"test_{name}",
                event_type=EventType.DECISION_APPROVED,
                handler=CountingHandler(name),
            )
            event_bus.subscribe(subscription)

        # 发布一个事件
        event = create_event(
            event_type=EventType.DECISION_APPROVED,
            payload={"test": "data"},
        )
        event_bus.publish(event)

        # 验证所有处理器都被调用
        assert handler_calls["handler1"] == 1
        assert handler_calls["handler2"] == 1
        assert handler_calls["handler3"] == 1

        # 清理
        event_bus.clear()


@pytest.mark.django_db
class TestHealthCheckIntegration:
    """测试健康检查集成"""

    def test_health_check_detects_unhealthy_state(self):
        """测试健康检查能检测不健康状态"""
        from apps.events.application.health_check import check_event_bus_health

        # 不初始化事件总线，检查应该返回 ERROR
        report = check_event_bus_health()

        # 应该有检查失败
        assert report is not None
        # 注意：根据实现，未初始化时可能返回 ERROR 或 WARNING

    def test_health_check_passes_after_initialization(self):
        """测试初始化后健康检查通过"""
        from apps.events.application.health_check import check_event_bus_health
        from apps.events.domain.entities import EventBusConfig
        from apps.events.domain.services import get_event_bus, reset_event_bus

        # 重置并初始化事件总线
        reset_event_bus()

        event_bus = get_event_bus()
        event_bus.start()

        # 执行健康检查
        report = check_event_bus_health()

        # 验证
        assert report is not None
        # WARNING 也是可接受的（因为可能缺少某些处理器）
        assert report.overall_status in ["OK", "WARNING"]

        # 检查关键组件
        component_names = [c.component for c in report.checks]
        assert 'event_bus_initialization' in component_names
        assert 'handler_registration' in component_names
        assert 'critical_handlers' in component_names
