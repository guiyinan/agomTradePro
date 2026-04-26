"""Asset analysis repository providers for application consumers."""

from __future__ import annotations

from apps.asset_analysis.infrastructure.providers import (
    AssetAnalysisLogRepository,
    DjangoAssetPoolQueryRepository,
)


def get_asset_analysis_log_repository() -> AssetAnalysisLogRepository:
    """Return the default asset-analysis log repository."""

    return AssetAnalysisLogRepository()


def get_asset_pool_query_repository() -> DjangoAssetPoolQueryRepository:
    """Return the default asset-pool query repository."""

    return DjangoAssetPoolQueryRepository()
