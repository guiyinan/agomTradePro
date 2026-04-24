"""Strategy domain rules."""

from apps.strategy.domain.entities import OrderEvent, OrderStatus
from apps.strategy.domain.services import OrderStateMachine


def can_apply_order_event(status: OrderStatus, event: OrderEvent) -> bool:
    """Return whether an order event is valid for the current status."""
    return OrderStateMachine.can_transition(status, event)


def apply_order_event(status: OrderStatus, event: OrderEvent) -> OrderStatus:
    """Apply an order event and return the next status."""
    return OrderStateMachine.transition(status, event)


def is_terminal_order_status(status: OrderStatus) -> bool:
    """Return whether an order status is terminal."""
    return OrderStateMachine.is_terminal(status)
