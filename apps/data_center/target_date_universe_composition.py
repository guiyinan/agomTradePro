"""Composition boundary for target-date A-share universe queries."""

from __future__ import annotations

from datetime import date

from apps.data_center.application.target_date_universe_scope import (
    build_target_date_a_share_universe_scope as _build_target_date_a_share_universe_scope,
)
from apps.data_center.composition import get_asset_repository
from apps.data_center.domain.target_date_universe import TargetDateAssetUniverseScope


def build_target_date_a_share_universe_scope(
    target_date: date,
) -> TargetDateAssetUniverseScope:
    """Compose the target-date scope query with the asset repository port."""

    return _build_target_date_a_share_universe_scope(target_date, get_asset_repository())
