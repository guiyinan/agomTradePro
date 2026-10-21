"""Read-only Application queries used by simulated-trading Admin."""

from __future__ import annotations

from typing import Protocol, cast

from apps.simulated_trading.application.repository_provider import (
    get_simulated_trade_repository,
)


class AdminTradeHistoryReadRepositoryProtocol(Protocol):
    """Read selected immutable trade-history identifiers for Admin policy."""

    def get_admin_read_only_trade_ids(self, trade_ids: tuple[int, ...]) -> frozenset[int]:
        """Return selected Trades with a V4 marker or durable fill receipt."""
        ...


def get_admin_read_only_trade_ids(trade_ids: tuple[int, ...]) -> frozenset[int]:
    """Return selected Trades carrying a V4 marker or immutable fill receipt."""

    repository = cast(
        AdminTradeHistoryReadRepositoryProtocol,
        get_simulated_trade_repository(),
    )
    return repository.get_admin_read_only_trade_ids(trade_ids)
