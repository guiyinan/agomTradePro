"""Asset analysis repository providers for application consumers."""

from __future__ import annotations

from typing import Any, cast

from apps.asset_analysis.domain.pool import PoolCategory
from apps.asset_analysis.infrastructure.asset_name_resolver import (  # noqa: F401
    AssetNameResolver,
    enrich_with_asset_names,
    resolve_asset_name,
    resolve_asset_names,
    resolve_asset_names_read_only,
)
from apps.asset_analysis.infrastructure.providers import (
    AssetAnalysisLogRepository,
    DjangoAssetPoolQueryRepository,
    DjangoAssetRepository,
    DjangoWeightConfigRepository,
)
from core.integration.asset_analysis_market_registry import (
    AssetPoolScreener,
    get_asset_analysis_market_registry,
)


def get_asset_analysis_log_repository() -> AssetAnalysisLogRepository:
    """Return the default asset-analysis log repository."""

    return AssetAnalysisLogRepository()


def get_asset_pool_query_repository() -> DjangoAssetPoolQueryRepository:
    """Return the default asset-pool query repository."""

    return DjangoAssetPoolQueryRepository()


def list_investable_asset_categories() -> tuple[str, ...]:
    """Return asset categories managed by the investable asset pool."""

    return tuple(category.value for category in PoolCategory)


def resolve_index_asset_names(codes: list[str]) -> dict[str, str]:
    """Resolve asset names from asset-pool entries for index-like assets."""

    raw_names: object = get_asset_pool_query_repository().resolve_asset_names(codes)
    if not isinstance(raw_names, dict):
        return {}
    return {
        code.strip().upper(): name.strip()
        for code, name in raw_names.items()
        if isinstance(code, str) and code.strip() and isinstance(name, str) and name.strip()
    }


def get_registered_pool_screener(asset_type: str) -> AssetPoolScreener:
    """Return a registered pool screener from the runtime integration registry."""

    return get_asset_analysis_market_registry().get_pool_screener(asset_type)


def list_latest_scored_assets(
    asset_type: str,
    *,
    min_score: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Return latest score-cache assets for consumers that need a legacy fallback."""

    return cast(
        list[dict[str, Any]],
        get_asset_pool_query_repository().list_latest_scored_assets(
            asset_type=asset_type,
            min_score=min_score,
            limit=limit,
        ),
    )


def get_asset_repository() -> DjangoAssetRepository:
    """Return the default asset repository."""

    return DjangoAssetRepository()


def get_weight_config_repository() -> DjangoWeightConfigRepository:
    """Return the default weight config repository."""

    return DjangoWeightConfigRepository()


__all__ = [
    "AssetAnalysisLogRepository",
    "AssetNameResolver",
    "DjangoAssetPoolQueryRepository",
    "DjangoAssetRepository",
    "DjangoWeightConfigRepository",
    "enrich_with_asset_names",
    "get_asset_analysis_log_repository",
    "get_asset_pool_query_repository",
    "get_asset_repository",
    "get_registered_pool_screener",
    "get_weight_config_repository",
    "list_investable_asset_categories",
    "list_latest_scored_assets",
    "resolve_asset_name",
    "resolve_asset_names",
    "resolve_asset_names_read_only",
    "resolve_index_asset_names",
]
