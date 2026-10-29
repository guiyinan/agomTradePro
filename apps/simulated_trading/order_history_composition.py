"""Composition for owner-scoped simulated order and receipt history reads."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.order_history import ReadOrderHistoryUseCase
from apps.simulated_trading.infrastructure.order_history_repository import (
    DjangoOrderHistoryRepository,
)


class _DjangoOrderHistoryClock:
    """Provide the server-side response timestamp for one read request."""

    def now(self) -> datetime:
        """Return the current timezone-aware application clock."""

        return timezone.now()


def build_read_order_history_use_case(
    *,
    using: str = DEFAULT_DB_ALIAS,
    clock: SimulatedTradeExecutionClock | None = None,
) -> ReadOrderHistoryUseCase:
    """Compose only persisted order/receipt reads; no source or writer is bound."""

    return ReadOrderHistoryUseCase(
        reader=DjangoOrderHistoryRepository(using=using),
        clock=clock if clock is not None else _DjangoOrderHistoryClock(),
    )


__all__ = ("build_read_order_history_use_case",)
