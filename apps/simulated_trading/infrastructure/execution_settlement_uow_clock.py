"""Validate the aware execution clock used by the simulated settlement UoW."""

from __future__ import annotations

from datetime import datetime

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)


def _aware_time(value: object) -> datetime:
    """Require an aware execution clock before any timestamp is stored."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware")
    try:
        if value.utcoffset() is None:
            raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked("execution clock must be timezone-aware") from error
    return value
