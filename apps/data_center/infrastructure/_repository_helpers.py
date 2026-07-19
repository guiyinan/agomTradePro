"""Shared private helpers for Data Center ORM repository owners.

Asset-code candidate resolution and small normalization helpers live here so
each repository owner stays focused on one persistence responsibility. This
module is internal to the infrastructure package; callers outside it should
use the compatibility facade ``repositories.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.infrastructure.models import AssetAliasModel, AssetMasterModel


def _to_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _dedupe_codes(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        normalized = code.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_names(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _infer_market_suffixes(base_code: str) -> list[str]:
    if not base_code:
        return []
    if base_code.startswith(("0", "1", "2", "3")):
        return ["SZ"]
    if base_code.startswith(("5", "6", "9")):
        return ["SH"]
    if base_code.startswith(("4", "8")):
        return ["BJ"]
    return []


def _build_asset_code_candidates(asset_code: str) -> list[str]:
    normalized = (asset_code or "").strip().upper()
    if not normalized:
        return []

    suffix_aliases = {
        "XSHE": "SZ",
        "SZSE": "SZ",
        "XSHG": "SH",
        "SSE": "SH",
        "BSE": "BJ",
    }

    candidates = [normalized]
    if "." in normalized:
        base_code, suffix = normalized.rsplit(".", 1)
        canonical_suffix = suffix_aliases.get(suffix)
        if canonical_suffix:
            candidates.append(f"{base_code}.{canonical_suffix}")
    else:
        base_code = normalized.split(".", 1)[0]
        for suffix in _infer_market_suffixes(base_code):
            candidates.append(f"{base_code}.{suffix}")
        candidates.append(base_code)

    return _dedupe_codes(candidates)


def _resolve_asset_code_candidates(asset_code: str) -> list[str]:
    normalized = (asset_code or "").strip().upper()
    candidates = _build_asset_code_candidates(normalized)
    if not candidates:
        return []

    resolved_codes = list(
        AssetMasterModel.objects.filter(code__in=candidates).values_list("code", flat=True)
    )
    resolved_codes.extend(
        AssetAliasModel.objects.filter(alias_code__in=candidates)
        .select_related("asset")
        .values_list("asset__code", flat=True)
    )

    base_code = candidates[0].split(".", 1)[0]
    if base_code and "." not in normalized:
        resolved_codes.extend(
            AssetMasterModel.objects.filter(code__startswith=f"{base_code}.").values_list(
                "code", flat=True
            )[:5]
        )

    return _dedupe_codes(candidates + resolved_codes)
