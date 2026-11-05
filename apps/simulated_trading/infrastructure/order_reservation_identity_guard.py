"""Shared exact owner/key validation for durable simulated-order reservations."""

from __future__ import annotations

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)


def require_order_reservation_owner_key(
    *, account_id: int, user_id: int, idempotency_key: str
) -> None:
    """Reject malformed owner scope before looking up a persisted reservation."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(user_id) is not int
        or user_id <= 0
        or type(idempotency_key) is not str
        or not idempotency_key
        or len(idempotency_key) > 128
        or idempotency_key.strip() != idempotency_key
        or any(character.isspace() for character in idempotency_key)
    ):
        raise SimulatedTradeExecutionBlocked(
            "order reservation owner or key is invalid",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        )
