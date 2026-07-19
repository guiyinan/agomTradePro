"""Shared numeric parsing helpers for untrusted external values."""

from __future__ import annotations

import math
from typing import Any, cast, overload

_MISSING_NUMERIC_TOKENS = frozenset({"", "-", "n/a", "na", "null", "none"})


@overload
def safe_float(
    value: object,
    *,
    default: None = None,
    strip_chars: str = "",
    scale: float = 1.0,
) -> float | None: ...


@overload
def safe_float(
    value: object,
    *,
    default: float,
    strip_chars: str = "",
    scale: float = 1.0,
) -> float: ...


def safe_float(
    value: object,
    *,
    default: float | None = None,
    strip_chars: str = "",
    scale: float = 1.0,
) -> float | None:
    """Parse an external numeric value without leaking conversion errors.

    Missing tokens, malformed values, NaN, and infinities resolve to ``default``.
    ``strip_chars`` removes explicitly allowed source formatting characters,
    while ``scale`` converts scaled integer payloads such as EastMoney fields.
    """

    if scale == 0:
        raise ValueError("scale must be non-zero")
    if value is None:
        return default

    candidate: object = value
    if isinstance(candidate, str):
        text = candidate.strip()
        if text.casefold() in _MISSING_NUMERIC_TOKENS:
            return default
        if strip_chars:
            text = text.translate(str.maketrans("", "", strip_chars))
        candidate = text.strip()

    try:
        number = float(cast(Any, candidate))
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    return number / scale
