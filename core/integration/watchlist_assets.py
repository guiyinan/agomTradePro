"""Bridge helpers for shared watchlist asset access."""

from __future__ import annotations

from django.apps import apps


def get_active_watchlist_asset_codes() -> list[str]:
    """Return active watchlist asset codes from the asset pool model."""

    asset_pool_entry = apps.get_model("asset_analysis", "AssetPoolEntry")
    codes = asset_pool_entry._default_manager.filter(
        pool_type="watch",
        is_active=True,
    ).values_list("asset_code", flat=True).distinct()
    return list(codes)
