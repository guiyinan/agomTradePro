"""Application query service for target-date A-share universe scope."""

from __future__ import annotations

from datetime import date

from apps.data_center.domain.protocols import AssetRepositoryProtocol
from apps.data_center.domain.target_date_universe import (
    TargetDateAssetUniverseScope,
    build_target_date_a_share_scope,
)


def build_target_date_a_share_universe_scope(
    target_date: date,
    asset_repository: AssetRepositoryProtocol,
) -> TargetDateAssetUniverseScope:
    """Resolve active A-share candidates against persisted listing-date evidence."""

    assets = asset_repository.list_active_stock_assets()
    return build_target_date_a_share_scope(target_date, assets)
