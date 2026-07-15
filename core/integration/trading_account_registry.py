"""App-neutral registry for read-only trading-account queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_active_accounts_reader: Callable[[int], list[Any]] | None = None


def register_active_accounts_reader(reader: Callable[[int], list[Any]]) -> None:
    """Register the trading-account owner query."""

    global _active_accounts_reader
    _active_accounts_reader = reader


def list_active_accounts_for_user(user_id: int) -> list[Any]:
    """Return active account rows for one user."""

    if _active_accounts_reader is None:
        return []
    return _active_accounts_reader(user_id)


__all__ = ["list_active_accounts_for_user", "register_active_accounts_reader"]
