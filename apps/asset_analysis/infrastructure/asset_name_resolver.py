"""
Asset name resolver owned by the asset_analysis module.

Provides a single place to resolve asset codes to display names while keeping
the implementation out of shared/.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, TypedDict

from django.core.cache import cache

from apps.data_center.application.public import get_asset_repository_port
from core.integration.asset_analysis_market_registry import (
    get_asset_analysis_market_registry,
)

logger = logging.getLogger(__name__)

CACHE_PREFIX = "asset_names:v5"
CACHE_TTL = 3600


class _AssetNameCachePayload(TypedDict):
    """Versioned exact-scope cache payload for asset display names."""

    version: int
    scope: list[str]
    names: dict[str, str]


def _normalize_code(value: object) -> str | None:
    """Normalize one display-name lookup key without inventing a market suffix."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if not normalized or len(normalized) > 64 or any(char.isspace() for char in normalized):
        return None
    return normalized


def _normalize_codes(values: list[object]) -> list[str]:
    """Normalize and deduplicate lookup codes while preserving input order."""

    normalized: list[str] = []
    for value in values:
        code = _normalize_code(value)
        if code is not None and code not in normalized:
            normalized.append(code)
    return normalized


def _validate_name_mapping(value: object, requested_codes: set[str]) -> dict[str, str]:
    """Keep only requested codes with bounded non-empty display names."""

    if not isinstance(value, dict):
        return {}
    resolved: dict[str, str] = {}
    conflicts: set[str] = set()
    for raw_code, raw_name in value.items():
        code = _normalize_code(raw_code)
        if (
            code is None
            or code not in requested_codes
            or not isinstance(raw_name, str)
            or not raw_name.strip()
            or len(raw_name.strip()) > 512
        ):
            continue
        name = raw_name.strip()
        if code in resolved and resolved[code] != name:
            conflicts.add(code)
            continue
        resolved[code] = name
    for code in conflicts:
        resolved.pop(code, None)
    return resolved


def _resolve_names(source_name: str, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    resolver = get_asset_analysis_market_registry().get_name_resolver(source_name)
    raw_names: object = resolver(sorted(codes))
    return _validate_name_mapping(raw_names, codes)


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
        code_set = set(_normalize_codes(list(codes)))
        if not code_set:
            return {}

        resolved: dict[str, str] = {}

        explicit_fund_codes = {code for code in code_set if str(code).upper().endswith(".OF")}
        resolved.update(self._resolve_funds(explicit_fund_codes))

        # Rotation assets take precedence for configured ETFs.  This keeps a
        # stable product display name instead of replacing it with a remote
        # exchange security name.
        resolved.update(self._resolve_rotation_assets(code_set - set(resolved.keys())))

        # Explicit fund identifiers must never fall through to the equity
        # resolver, whose read-through path may call remote market providers.
        unresolved_stock_codes = {
            code
            for code in code_set - set(resolved.keys())
            if not str(code).upper().endswith(".OF")
        }
        resolved.update(self._resolve_stocks(unresolved_stock_codes))
        resolved.update(self._resolve_funds(code_set - set(resolved.keys())))
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

        normalized_code = _normalize_code(code)
        if normalized_code is None:
            return code
        result = self.resolve_asset_names([normalized_code])
        return result.get(normalized_code, normalized_code)

    def resolve_canonical_asset_names(self, codes: list[str]) -> dict[str, str]:
        """Resolve names strictly from the canonical Data Center asset master."""

        requested_codes = _normalize_codes(list(codes))
        if not requested_codes:
            return {}

        repository = get_asset_repository_port()
        resolved: dict[str, str] = {}
        for requested_code in requested_codes:
            asset = repository.get_by_code(requested_code)
            if asset is None or not asset.is_active:
                continue
            name = str(asset.short_name or asset.name or "").strip()
            if name and len(name) <= 512:
                resolved[requested_code] = name
        return resolved

    def _resolve_stocks(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from stock master data."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("equity", codes))
        except Exception as exc:
            logger.warning("Failed to resolve stock names: %s", type(exc).__name__)

        return resolved

    def _resolve_funds(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from fund master data."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("fund", codes))
        except Exception as exc:
            logger.warning("Failed to resolve fund names: %s", type(exc).__name__)

        return resolved

    def _resolve_rotation_assets(self, codes: set[str]) -> dict[str, str]:
        """Resolve ETF, bond, and commodity names from rotation assets."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("rotation", codes))
        except Exception as exc:
            logger.warning("Failed to resolve rotation asset names: %s", type(exc).__name__)

        return resolved

    def _resolve_fund_holdings(self, codes: set[str]) -> dict[str, str]:
        """Backfill stock names from fund holdings for ETF downgrade paths."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("fund_holding", codes))
        except Exception as exc:
            logger.warning(
                "Failed to resolve stock names from fund holdings: %s",
                type(exc).__name__,
            )

        return resolved

    def _resolve_indices(self, codes: set[str]) -> dict[str, str]:
        """Resolve names from asset pool entries."""
        if not codes:
            return {}

        resolved: dict[str, str] = {}
        try:
            resolved.update(_resolve_names("index", codes))
        except Exception as exc:
            logger.debug(
                "Failed to resolve index names from AssetPoolEntry: %s",
                type(exc).__name__,
            )

        return resolved


def _build_cache_key(codes: list[str]) -> str:
    """Build the cache key for a code batch."""
    sorted_codes = sorted(_normalize_codes(list(codes)))
    codes_hash = hashlib.sha256(
        json.dumps(sorted_codes, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"{CACHE_PREFIX}:{codes_hash}"


def _read_cached_names(value: object, expected_scope: list[str]) -> dict[str, str] | None:
    """Validate a cache payload against its exact normalized request scope."""

    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    scope = value.get("scope")
    names = value.get("names")
    if scope != expected_scope:
        return None
    validated_names = _validate_name_mapping(names, set(expected_scope))
    if not isinstance(names, dict) or len(validated_names) != len(names):
        return None
    return validated_names


def _resolve_asset_names_with_cache_policy(
    codes: list[str],
    *,
    populate_cache: bool,
    canonical_only: bool = False,
) -> dict[str, str]:
    """Resolve asset names while controlling whether cache misses may write."""

    normalized_codes = _normalize_codes(list(codes))
    if not normalized_codes:
        return {}
    normalized_scope = sorted(normalized_codes)
    code_set = set(normalized_scope)

    resolver = AssetNameResolver()
    if canonical_only:
        return resolver.resolve_canonical_asset_names(normalized_scope)

    cache_key = _build_cache_key(normalized_scope)

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            cached_names = _read_cached_names(cached, normalized_scope)
            if cached_names is not None:
                return cached_names
    except Exception as exc:
        logger.warning("Asset name cache get failed: %s", type(exc).__name__)

    result = resolver.resolve_asset_names(list(code_set))

    if populate_cache:
        try:
            payload: _AssetNameCachePayload = {
                "version": 1,
                "scope": normalized_scope,
                "names": dict(result),
            }
            cache.set(cache_key, payload, CACHE_TTL)
        except Exception as exc:
            logger.warning("Asset name cache set failed: %s", type(exc).__name__)

    return result


def resolve_asset_names(codes: list[str]) -> dict[str, str]:
    """
    Resolve asset names and populate the shared cache on cache misses.

    Args:
        codes: Asset code list.

    Returns:
        Mapping from asset code to asset name.
    """

    return _resolve_asset_names_with_cache_policy(codes, populate_cache=True)


def resolve_asset_names_read_only(codes: list[str]) -> dict[str, str]:
    """Resolve names from canonical master data without cache, network, or writes."""

    return _resolve_asset_names_with_cache_policy(
        codes,
        populate_cache=False,
        canonical_only=True,
    )


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

    normalized_code = _normalize_code(code)
    if normalized_code is None:
        return code
    result = resolve_asset_names([normalized_code])
    return result.get(normalized_code, normalized_code)


def enrich_with_asset_names(
    items: list[dict[str, Any]],
    code_field: str = "asset_code",
    name_field: str = "asset_name",
) -> list[dict[str, Any]]:
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

    codes = _normalize_codes([item.get(code_field) for item in items])
    if not codes:
        return items

    name_map = resolve_asset_names(codes)

    for item in items:
        code = _normalize_code(item.get(code_field))
        if code is not None and not item.get(name_field):
            item[name_field] = name_map.get(code, code)

    return items
