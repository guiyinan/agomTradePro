"""Bridge helpers for simulated-trading position access."""

from __future__ import annotations

from apps.simulated_trading.application.query_services import (
    get_position_snapshots as _get_position_snapshots,
)
from apps.simulated_trading.application.query_services import (
    list_held_asset_codes as _list_held_asset_codes,
)
from apps.simulated_trading.application.repository_provider import get_simulated_position_repository


def get_simulated_position_price_updater():
    """Return the default simulated position repository for price updates."""

    return get_simulated_position_repository()


def list_held_simulated_asset_codes() -> list[str]:
    """Return distinct asset codes held in simulated-trading positions."""

    return _list_held_asset_codes()


def get_position_snapshots(account_id: int | str) -> list[dict]:
    """Return lightweight simulated position snapshots for cross-app planning."""

    normalized = str(account_id or "").strip()
    if not normalized:
        return []
    if not normalized.isdigit():
        return []
    return _get_position_snapshots(account_id=int(normalized))
