"""Private canonicalization and validation helpers for R3 runner modules."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal


def require_text(value: str, field_name: str, *, maximum: int = 255) -> None:
    """Require bounded nonblank text."""

    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    """Require bounded nonblank text without whitespace."""

    require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def require_sha256(value: str, field_name: str) -> None:
    """Require a hexadecimal SHA-256 digest."""

    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware datetime."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_finite(value: Decimal, field_name: str) -> None:
    """Require a finite Decimal."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def require_positive(value: int, field_name: str) -> None:
    """Require a positive integer and reject bool."""

    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def decimal_text(value: Decimal) -> str:
    """Return stable non-exponent Decimal text."""

    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def canonical_json(payload: object) -> str:
    """Return stable UTF-8-ready canonical JSON."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_payload(payload: object) -> str:
    """Return the SHA-256 of canonical JSON."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def utc_text(value: datetime) -> str:
    """Normalize an aware datetime to canonical UTC text."""

    return value.astimezone(UTC).isoformat()


__all__ = [
    "canonical_json",
    "decimal_text",
    "hash_payload",
    "require_aware",
    "require_finite",
    "require_positive",
    "require_sha256",
    "require_text",
    "require_token",
    "utc_text",
]
