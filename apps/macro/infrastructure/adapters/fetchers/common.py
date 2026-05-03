"""Shared parsing helpers for macro fetchers."""

from __future__ import annotations

from typing import Iterable

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


def resolve_indicator_units(
    indicator_code: str,
    fallback_unit: str = "",
    fallback_original_unit: str = "",
) -> tuple[str, str]:
    """Resolve fetcher-facing units from runtime metadata first, then fall back.

    Fetchers should continue emitting source/raw units. Canonical conversion is
    still owned by data_center normalization and unit-rule governance.
    """

    original_unit = ""
    try:
        metadata = get_runtime_macro_index_metadata_map().get(indicator_code, {})
        original_unit = str(
            metadata.get("default_unit")
            or metadata.get("original_unit")
            or metadata.get("unit")
            or ""
        ).strip()
    except Exception:
        original_unit = ""

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
        original_unit = fallback_original_unit or fallback_unit or ""

    return original_unit, original_unit
