"""Bridge helpers for shared watchlist asset access."""

from __future__ import annotations

from apps.asset_analysis.application.query_services import (
    list_active_watchlist_asset_codes,
)


def get_active_watchlist_asset_codes() -> list[str]:
    """Return active watchlist asset codes from the asset pool model."""

    return list_active_watchlist_asset_codes()
