"""Decode the exact locked account stop-loss threshold."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)


def normalize_locked_stop_loss_pct(value: object) -> Decimal | None:
    """Convert the locked account FloatField through its exact decimal text."""

    if value is None:
        return None
    if type(value) not in (int, float) or type(value) is bool:
        raise SimulatedTradeExecutionBlocked(
            "locked account stop-loss threshold is invalid",
            code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
        )
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "locked account stop-loss threshold is invalid",
            code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
        ) from error
