"""App-neutral Decision Rhythm query used by Share snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_reader: Callable[..., list[Any]] | None = None


def register_share_decision_reader(reader: Callable[..., list[Any]]) -> None:
    """Register the Decision Rhythm owned snapshot query."""

    global _reader
    _reader = reader


def list_share_decisions_for_account_assets(
    *, account_id: int, asset_codes: set[str], limit: int
) -> list[Any]:
    """Return decision rows used when building a Share snapshot."""

    if _reader is None:
        return []
    return _reader(account_id=account_id, asset_codes=asset_codes, limit=limit)


__all__ = [
    "list_share_decisions_for_account_assets",
    "register_share_decision_reader",
]
