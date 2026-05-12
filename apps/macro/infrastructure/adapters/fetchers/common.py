"""Shared parsing helpers for macro fetchers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from core.integration.runtime_settings import get_runtime_macro_index_metadata_map


def pick_column(
    df: pd.DataFrame,
    candidates: Iterable[str],
    fallback_index: int = 0,
) -> str:
    """Return the first matching column name or fall back by position."""
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return df.columns[fallback_index]


def safe_float(value: object) -> float:
    """Parse a numeric value from AKShare payloads."""
    if value is None or pd.isna(value):
        raise ValueError("empty numeric value")

    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        if not cleaned or cleaned in {"--", "nan", "None", "null"}:
            raise ValueError(f"invalid numeric value: {value!r}")
        return float(cleaned)

    return float(value)


def _load_indicator_metadata(indicator_code: str) -> dict[str, Any]:
    try:
        metadata = dict(get_runtime_macro_index_metadata_map().get(indicator_code, {}) or {})
    except Exception:
        metadata = {}
    if metadata:
        return metadata

    try:
        from apps.data_center.application.repository_provider import (
            get_indicator_catalog_repository,
        )

        catalog = get_indicator_catalog_repository().get_by_code(indicator_code)
    except Exception:
        catalog = None

    if catalog is None:
        return {}

    extra = dict(catalog.extra or {})
    extra.setdefault("default_unit", catalog.default_unit or "")
    extra.setdefault("default_period_type", catalog.default_period_type or "")
    return extra


def resolve_indicator_units(indicator_code: str) -> tuple[str, str]:
    """Resolve fetcher-facing units from governed metadata or active unit rules.

    Fetchers should continue emitting source/raw units. Canonical conversion is
    still owned by data_center normalization and unit-rule governance.
    """

    metadata = _load_indicator_metadata(indicator_code)
    governance_scope = str(metadata.get("governance_scope") or "").strip()
    original_unit = ""
    original_unit = str(
        metadata.get("default_unit")
        or metadata.get("original_unit")
        or metadata.get("unit")
        or ""
    ).strip()

    if not original_unit:
        try:
            from apps.data_center.application.repository_provider import (
                get_indicator_unit_rule_repository,
            )

            rule = get_indicator_unit_rule_repository().resolve_active_rule(indicator_code)
            if rule is not None:
                original_unit = str(
                    rule.original_unit or rule.display_unit or rule.storage_unit or ""
                ).strip()
        except Exception:
            original_unit = ""

    if not original_unit:
        if governance_scope:
            raise ValueError(
                f"Governed indicator {indicator_code} is missing runtime unit metadata "
                "and active unit-rule coverage"
            )
        raise ValueError(
            f"Indicator {indicator_code} is missing runtime unit metadata "
            "and active unit-rule coverage"
        )

    return original_unit, original_unit
