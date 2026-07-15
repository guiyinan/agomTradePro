"""Consumer-owned gateway for Simulated Trading strategy consumers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

_facade_factory: Callable[[], Any] | None = None
_trade_payload_provider: Callable[..., list[dict[str, Any]]] | None = None


def register_simulated_trading_providers(
    *,
    facade_factory: Callable[[], Any],
    trade_payload_provider: Callable[..., list[dict[str, Any]]],
) -> None:
    """Register Simulated Trading providers used by Strategy."""

    global _facade_factory
    global _trade_payload_provider
    _facade_factory = facade_factory
    _trade_payload_provider = trade_payload_provider


def get_simulated_trading_facade() -> Any:
    """Return the registered Simulated Trading facade."""

    if _facade_factory is None:
        raise RuntimeError("Simulated Trading facade factory is not registered")
    return _facade_factory()


def list_account_trade_payloads(
    *,
    account_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Return account trades through the registered provider."""

    if _trade_payload_provider is None:
        return []
    return _trade_payload_provider(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


__all__ = [
    "get_simulated_trading_facade",
    "list_account_trade_payloads",
    "register_simulated_trading_providers",
]
