"""
Asset name resolver owned by the asset_analysis module.

Provides a single place to resolve asset codes to display names while keeping
the implementation out of shared/.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.core.cache import cache

from core.integration.asset_analysis_market_registry import (
    get_asset_analysis_market_registry,
)

logger = logging.getLogger(__name__)

CACHE_PREFIX = "asset_names:v3"
CACHE_TTL = 3600


def _resolve_names(source_name: str, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    resolver = get_asset_analysis_market_registry().get_name_resolver(source_name)
    return resolver(list(codes))


class AssetNameResolver:
    """
    Resolve asset codes to display names across supported asset tables.
    """

    def resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        """
        Resolve a batch of asset codes.

        Args:
            codes: Asset code list.

        Returns:
            Mapping from asset code to asset name.
        """
        code_set: set[str] = {code for code in codes if code}
        if not code_set:
            return {}

        resolved: dict[str, str] = {}

        resolved.update(self._resolve_stocks(code_set - set(resolved.keys())))
        resolved.update(self._resolve_funds(code_set - set(resolved.keys())))
        resolved.update(self._resolve_rotation_assets(code_set - set(resolved.keys())))
        resolved.update(self._resolve_fund_holdings(code_set - set(resolved.keys())))
        resolved.update(self._resolve_indices(code_set - set(resolved.keys())))

        return resolved

    def resolve_asset_name(self, code: str) -> str:
        """
        Resolve a single asset code.

        Args:
            code: Asset code.

        Returns:
            Asset name when found, otherwise the original code.
        """
        if not code:
            return code

        result = self.resolve_asset_names([code])
        return result.get(code, code)

    def _resolve_stocks(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from stock master data."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("equity", codes))
        except Exception as exc:
            logger.warning("Failed to resolve stock names: %s", exc)

        return resolved

    def _resolve_funds(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from fund master data."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("fund", codes))
        except Exception as exc:
            logger.warning("Failed to resolve fund names: %s", exc)

        return resolved

    def _resolve_rotation_assets(self, codes: set[str]) -> dict[str, str]:
        """Resolve ETF, bond, and commodity names from rotation assets."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("rotation", codes))
        except Exception as exc:
            logger.warning("Failed to resolve rotation asset names: %s", exc)

        return resolved

    def _resolve_fund_holdings(self, codes: set[str]) -> dict[str, str]:
        """Backfill stock names from fund holdings for ETF downgrade paths."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("fund_holding", codes))
        except Exception as exc:
            logger.warning("Failed to resolve stock names from fund holdings: %s", exc)

        return resolved

    def _resolve_indices(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from asset pool entries."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("index", codes))
        except Exception as exc:
            logger.debug("Failed to resolve index names from AssetPoolEntry: %s", exc)

        return resolved


def _build_cache_key(codes: list[str]) -> str:
    """Build the cache key for a code batch."""
    sorted_codes = sorted({c for c in codes if c})
    codes_hash = hashlib.sha256(json.dumps(sorted_codes).encode()).hexdigest()[:32]
    return f"{CACHE_PREFIX}:{codes_hash}"


def resolve_asset_names(codes: list[str]) -> dict[str, str]:
    """
    Resolve asset names with cache support.

    Args:
        codes: Asset code list.

    Returns:
        Mapping from asset code to asset name.
    """
    code_set = {code for code in codes if code}
    if not code_set:
        return {}

    cache_key = _build_cache_key(list(code_set))

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception as exc:
        logger.warning("Cache get failed: %s", exc)

    resolver = AssetNameResolver()
    result = resolver.resolve_asset_names(list(code_set))

    try:
        cache.set(cache_key, result, CACHE_TTL)
    except Exception as exc:
        logger.warning("Cache set failed: %s", exc)

    return result


def resolve_asset_name(code: str) -> str:
    """
    Resolve a single asset code to its display name.

    Args:
        code: Asset code.

    Returns:
        Asset name when found, otherwise the original code.
    """
    if not code:
        return code

    result = resolve_asset_names([code])
    return result.get(code, code)


def enrich_with_asset_names(
    items: list[dict], code_field: str = "asset_code", name_field: str = "asset_name"
) -> list[dict]:
    """
    Enrich dict items with resolved asset names.

    Args:
        items: Item list.
        code_field: Source code field name.
        name_field: Destination name field name.

    Returns:
        The input items with names filled in when missing.
    """
    if not items:
        return items

    codes = [item.get(code_field) for item in items if item.get(code_field)]
    if not codes:
        return items

    name_map = resolve_asset_names(codes)

    for item in items:
        code = item.get(code_field)
        if code and not item.get(name_field):
            item[name_field] = name_map.get(code, code)

    return items
