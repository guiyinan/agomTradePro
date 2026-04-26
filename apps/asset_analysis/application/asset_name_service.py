"""
Application-facing asset name resolution service.

Other modules should depend on this application service instead of importing
shared or asset_analysis infrastructure modules directly.
"""

from __future__ import annotations

from apps.asset_analysis.application.repository_provider import (
    AssetNameResolver,
    enrich_with_asset_names,
    resolve_asset_name,
    resolve_asset_names,
)

__all__ = [
    "AssetNameResolver",
    "enrich_with_asset_names",
    "resolve_asset_name",
    "resolve_asset_names",
]
