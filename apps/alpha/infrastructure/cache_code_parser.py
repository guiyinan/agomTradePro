"""Helpers for normalising asset codes stored inside Alpha cache payloads."""

from __future__ import annotations

import re
from collections.abc import Iterable

_CANONICAL_CODE_PATTERN = re.compile(r"^(?P<digits>\d{6})\.(?P<exchange>SH|SZ|BJ)$")
_PREFIX_CODE_PATTERN = re.compile(r"(?P<exchange>SH|SZ|BJ)(?P<digits>\d{6})")


def normalize_cached_stock_code(raw_code: object) -> str:
    """Return a canonical tushare-style stock code from Alpha cache payloads."""
    if isinstance(raw_code, (list, tuple)) and raw_code:
        return normalize_cached_stock_code(raw_code[-1])

    value = str(raw_code or "").strip().upper()
    if not value:
        return ""

    match = _CANONICAL_CODE_PATTERN.match(value)
    if match:
        return f"{match.group('digits')}.{match.group('exchange')}"

    match = _PREFIX_CODE_PATTERN.search(value)
    if match:
        return f"{match.group('digits')}.{match.group('exchange')}"

    if value.isdigit() and len(value) == 6:
        if value.startswith(("6", "5", "9")):
            return f"{value}.SH"
        if value.startswith(("0", "1", "3")):
            return f"{value}.SZ"
        if value.startswith(("4", "8")):
            return f"{value}.BJ"
    return ""


def extract_cached_score_code(score_item: object) -> str:
    """Extract and normalise one security code from a cache score item."""
    if isinstance(score_item, dict):
        return normalize_cached_stock_code(score_item.get("code"))
    return normalize_cached_stock_code(score_item)


def collect_cached_score_codes(scores: Iterable[object]) -> list[str]:
    """Return unique canonical security codes in original order."""
    normalized_codes: list[str] = []
    seen: set[str] = set()
    for item in scores:
        normalized = extract_cached_score_code(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_codes.append(normalized)
    return normalized_codes
