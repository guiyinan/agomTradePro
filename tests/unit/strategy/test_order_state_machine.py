"""
OrderIntent 状态机单元测试
"""
import pytest

from apps.strategy.domain.entities import OrderEvent, OrderStatus
from apps.strategy.domain.services import OrderStateMachine


class TestOrderStateMachine:
    """订单状态机测试"""

    def test_can_transition_valid(self):
        """测试有效的状态转换"""
        # DRAFT -> SUBMIT -> PENDING_APPROVAL
        assert OrderStateMachine.can_transition(OrderStatus.DRAFT, OrderEvent.SUBMIT)

        # PENDING_APPROVAL -> APPROVE -> APPROVED
        assert OrderStateMachine.can_transition(OrderStatus.PENDING_APPROVAL, OrderEvent.APPROVE)

        # APPROVED -> SEND -> SENT
        assert OrderStateMachine.can_transition(OrderStatus.APPROVED, OrderEvent.SEND)

        # SENT -> FILL -> FILLED
        assert OrderStateMachine.can_transition(OrderStatus.SENT, OrderEvent.FILL)


        # SENT -> CANCEL -> CANCELED
        assert OrderStateMachine.can_transition(OrderStatus.SENT, OrderEvent.CANCEL)


        # SENT -> FAIL -> FAILED
        assert OrderStateMachine.can_transition(OrderStatus.SENT, OrderEvent.FAIL)

    def test_can_transition_invalid(self):
        """测试无效的状态转换"""
        # DRAFT 不能直接到 APPROVED
        assert not OrderStateMachine.can_transition(OrderStatus.DRAFT, OrderEvent.APPROVE)

        # DRAFT 不能直接到 SENT
        assert not OrderStateMachine.can_transition(OrderStatus.DRAFT, OrderEvent.SEND)

        # PENDING_APPROVAL 不能直接到 SENT
        assert not OrderStateMachine.can_transition(OrderStatus.PENDING_APPROVAL, OrderEvent.SEND)

        # FILLED 不能转换到任何状态
        assert not OrderStateMachine.can_transition(OrderStatus.FILLED, OrderEvent.CANCEL)
        assert not OrderStateMachine.can_transition(OrderStatus.FILLED, OrderEvent.FILL)

        # CANCELED 不能转换
        assert not OrderStateMachine.can_transition(OrderStatus.CANCELED, OrderEvent.CANCEL)


        # REJECTED 不能转换
        assert not OrderStateMachine.can_transition(OrderStatus.REJECTED, OrderEvent.APPROVE)

        # FAILED 不能转换
        assert not OrderStateMachine.can_transition(OrderStatus.FAILED, OrderEvent.SEND)


        # PARTIAL_FILLED 不能到 SENT
        assert not OrderStateMachine.can_transition(OrderStatus.PARTIAL_FILLED, OrderEvent.SEND)

    def test_transition_success(self):
        """测试成功的状态转换"""
        # DRAFT -> SUBMIT -> PENDING_APPROVAL
        new_status = OrderStateMachine.transition(OrderStatus.DRAFT, OrderEvent.SUBMIT)
        assert new_status == OrderStatus.PENDING_APPROVAL

        # PENDING_APPROVAL -> APPROVE -> APPROVED
        new_status = OrderStateMachine.transition(OrderStatus.PENDING_APPROVAL, OrderEvent.APPROVE)
        assert new_status == OrderStatus.APPROVED

        # APPROVED -> SEND -> SENT
        new_status = OrderStateMachine.transition(OrderStatus.APPROVED, OrderEvent.SEND)
        assert new_status == OrderStatus.SENT

        # SENT -> FILL -> FILLED
        new_status = OrderStateMachine.transition(OrderStatus.SENT, OrderEvent.FILL)
        assert new_status == OrderStatus.FILLED

    def test_transition_invalid_raises(self):
        """测试无效的状态转换抛出异常"""
        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.DRAFT, OrderEvent.FILL)
        assert "Invalid transition" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.FILLED, OrderEvent.CANCEL)
        assert "Invalid transition" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.CANCELED, OrderEvent.FILL)
        assert "Invalid transition" in str(exc_info.value)


        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.REJECTED, OrderEvent.SEND)
        assert "Invalid transition" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.FAILED, OrderEvent.FILL)
        assert "Invalid transition" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            OrderStateMachine.transition(OrderStatus.PARTIAL_FILLED, OrderEvent.SEND)
        assert "Invalid transition" in str(exc_info.value)

    def test_is_terminal(self):
        """测试终态判断"""
        assert OrderStateMachine.is_terminal(OrderStatus.FILLED)
        assert OrderStateMachine.is_terminal(OrderStatus.CANCELED)
        assert OrderStateMachine.is_terminal(OrderStatus.REJECTED)
        assert OrderStateMachine.is_terminal(OrderStatus.FAILED)

        assert not OrderStateMachine.is_terminal(OrderStatus.DRAFT)
        assert not OrderStateMachine.is_terminal(OrderStatus.PENDING_APPROVAL)
        assert not OrderStateMachine.is_terminal(OrderStatus.APPROVED)
        assert not OrderStateMachine.is_terminal(OrderStatus.SENT)
        assert not OrderStateMachine.is_terminal(OrderStatus.PARTIAL_FILLED)

    def test_get_valid_events(self):
        """测试获取有效事件"""
        # DRAFT 状态只能 SUBMIT
        events = OrderStateMachine.get_valid_events(OrderStatus.DRAFT)
        assert len(events) == 1
        assert OrderEvent.SUBMIT in events

        # PENDING_APPROVAL 状态可以 APPROVE 或 REJECT
        events = OrderStateMachine.get_valid_events(OrderStatus.PENDING_APPROVAL)
        assert len(events) == 2
        assert OrderEvent.APPROVE in events
        assert OrderEvent.REJECT in events

        # APPROVED 状态可以 SEND 或 CANCEL
        events = OrderStateMachine.get_valid_events(OrderStatus.APPROVED)
        assert len(events) == 2
        assert OrderEvent.SEND in events
        assert OrderEvent.CANCEL in events

        # SENT 状态可以 PARTIAL_FILL, FILL, CANCEL, FAIL
        events = OrderStateMachine.get_valid_events(OrderStatus.SENT)
        assert len(events) == 4
        assert OrderEvent.PARTIAL_FILL in events
        assert OrderEvent.FILL in events
        assert OrderEvent.CANCEL in events
        assert OrderEvent.FAIL in events

        # FILLED 状态没有可用事件
        events = OrderStateMachine.get_valid_events(OrderStatus.FILLED)
        assert len(events) == 0

        # CANCELED 状态没有可用事件
        events = OrderStateMachine.get_valid_events(OrderStatus.CANCELED)
        assert len(events) == 0

        # REJECTED 状态没有可用事件
        events = OrderStateMachine.get_valid_events(OrderStatus.REJECTED)
        assert len(events) == 0

        # FAILED 状态没有可用事件
        events = OrderStateMachine.get_valid_events(OrderStatus.FAILED)
        assert len(events) == 0

    def test_validate_transition_path(self):
        """测试验证状态转换路径"""
        # 有效路径: DRAFT -> SUBMIT -> PENDING_APPROVAL -> APPROVE -> APPROVED -> SEND -> SENT -> FILL -> FILLED
        valid_path = [
            (OrderStatus.DRAFT, OrderEvent.SUBMIT),
            (OrderStatus.PENDING_APPROVAL, OrderEvent.APPROVE),
            (OrderStatus.APPROVED, OrderEvent.SEND),
            (OrderStatus.SENT, OrderEvent.FILL),
        ]
        assert OrderStateMachine.validate_transition_path(valid_path)

        # 无效路径: DRAFT -> SUBMIT -> PENDING_APPROVAL -> REJECT (REJECTED 不能再转换)
        invalid_path = [
            (OrderStatus.DRAFT, OrderEvent.SUBMIT),
            (OrderStatus.PENDING_APPROVAL, OrderEvent.REJECT),
            (OrderStatus.REJECTED, OrderEvent.APPROVE),  # 这步无效
        ]
        assert not OrderStateMachine.validate_transition_path(invalid_path)

        # 无效路径: DRAFT 直接 FILL
        invalid_path = [
            (OrderStatus.DRAFT, OrderEvent.FILL),
        ]
        assert not OrderStateMachine.validate_transition_path(invalid_path)

        # 空路径无效
        assert not OrderStateMachine.validate_transition_path([])
