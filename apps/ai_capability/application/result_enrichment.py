"""Enrich capability result payloads with security display names."""

from __future__ import annotations

import logging
from typing import Any

from apps.asset_analysis.application.asset_name_service import (
    resolve_asset_names_read_only,
)

SECURITY_FIELD_PAIRS: tuple[tuple[str, str], ...] = (
    ("asset_code", "asset_name"),
    ("stock_code", "stock_name"),
    ("fund_code", "fund_name"),
    ("security_code", "security_name"),
)

logger = logging.getLogger(__name__)


def _missing_name_codes(value: Any) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        for code_field, name_field in SECURITY_FIELD_PAIRS:
            code = str(value.get(code_field) or "").strip()
            name = str(value.get(name_field) or "").strip()
            if code and not name:
                codes.add(code)
        for item in value.values():
            codes.update(_missing_name_codes(item))
    elif isinstance(value, list | tuple):
        for item in value:
            codes.update(_missing_name_codes(item))
    return codes


def _resolved_name(code: str, name_map: dict[str, str]) -> str:
    resolved = str(name_map.get(code) or name_map.get(code.upper()) or "").strip()
    return resolved if resolved and resolved != code else ""


def _enrich_value(value: Any, name_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        enriched = {key: _enrich_value(item, name_map) for key, item in value.items()}
        for code_field, name_field in SECURITY_FIELD_PAIRS:
            code = str(enriched.get(code_field) or "").strip()
            existing_name = str(enriched.get(name_field) or "").strip()
            if not code or existing_name:
                continue
            name = _resolved_name(code, name_map)
            if name:
                enriched[name_field] = name
        return enriched
    if isinstance(value, list):
        return [_enrich_value(item, name_map) for item in value]
    if isinstance(value, tuple):
        return tuple(_enrich_value(item, name_map) for item in value)
    return value


def enrich_security_names(payload: Any) -> Any:
    """Return a copy of a capability payload with missing security names filled."""

    codes = sorted(_missing_name_codes(payload))
    if not codes:
        return payload

    try:
        resolved = resolve_asset_names_read_only(codes)
    except Exception as exc:
        logger.warning("Failed to enrich capability security names: %s", exc)
        return payload
    name_map = {
        str(code).strip().upper(): str(name).strip()
        for code, name in resolved.items()
        if str(code).strip() and str(name).strip()
    }
    return _enrich_value(payload, name_map)
