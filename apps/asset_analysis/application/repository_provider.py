"""Asset analysis repository providers for application consumers."""

from __future__ import annotations

from apps.asset_analysis.infrastructure.asset_name_resolver import (
    AssetNameResolver,
    enrich_with_asset_names,
    resolve_asset_name,
    resolve_asset_names,
)
from apps.asset_analysis.infrastructure.providers import (
    AssetAnalysisLogRepository,
    DjangoAssetRepository,
    DjangoAssetPoolQueryRepository,
    DjangoWeightConfigRepository,
)


def get_asset_analysis_log_repository() -> AssetAnalysisLogRepository:
    """Return the default asset-analysis log repository."""

    return AssetAnalysisLogRepository()


def get_asset_pool_query_repository() -> DjangoAssetPoolQueryRepository:
    """Return the default asset-pool query repository."""

    return DjangoAssetPoolQueryRepository()


def get_asset_repository() -> DjangoAssetRepository:
    """Return the default asset repository."""

    return DjangoAssetRepository()


def get_weight_config_repository() -> DjangoWeightConfigRepository:
    """Return the default weight config repository."""

    return DjangoWeightConfigRepository()
