"""Shared parsing helpers for macro fetchers."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


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
