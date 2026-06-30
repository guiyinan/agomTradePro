"""Application-level query helpers for asset-analysis consumers."""

from __future__ import annotations

from typing import Any

from apps.asset_analysis.application.repository_provider import get_asset_pool_query_repository


def list_active_watchlist_asset_codes() -> list[str]:
    """Return active watchlist asset codes through the asset-analysis boundary."""

    return get_asset_pool_query_repository().list_active_watchlist_asset_codes()


def list_asset_master_pool_candidate_codes() -> list[str]:
    """Return asset-pool codes that can seed data-center asset master rows."""

    return get_asset_pool_query_repository().list_asset_master_candidate_codes()


def list_asset_master_pool_rows(lookup_codes: list[str]) -> list[dict[str, Any]]:
    """Return local asset-pool rows for data-center asset master backfill."""

    return get_asset_pool_query_repository().list_asset_master_pool_rows(lookup_codes)
