"""Canonical hashing and validation primitives for governed optimization evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal


def hash_components(*components: str) -> str:
    """Return an unambiguous length-prefixed SHA-256 digest."""

    digest = hashlib.sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def decimal_text(value: Decimal) -> str:
    """Return a scale-independent canonical Decimal representation."""

    require_finite(value, "decimal")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def utc_text(value: datetime) -> str:
    """Return a canonical UTC ISO timestamp."""

    require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat()


def require_token(value: str, field_name: str) -> None:
    """Require a bounded whitespace-free identifier."""

    if not value or len(value) > 192 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def require_text(value: str, field_name: str) -> None:
    """Require bounded non-blank evidence text."""

    if not value.strip() or len(value) > 512:
        raise ValueError(f"{field_name} must be bounded non-blank text")


def require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_finite(value: Decimal, field_name: str) -> None:
    """Require a finite Decimal at the Domain boundary."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def require_positive(value: Decimal, field_name: str) -> None:
    """Require a positive finite Decimal."""

    require_finite(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def require_unit_interval(value: Decimal, field_name: str) -> None:
    """Require a finite Decimal within the closed unit interval."""

    require_finite(value, field_name)
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{field_name} must be within [0, 1]")


def require_nonnegative_int(value: int, field_name: str) -> None:
    """Require an integer count while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def require_ordered_unique(values: tuple[str, ...], field_name: str) -> None:
    """Require a non-empty canonical ordered set of string identifiers."""

    if not values or len(values) != len(set(values)) or values != tuple(sorted(values)):
        raise ValueError(f"{field_name} must be non-empty, unique, and ordered")


def require_sha256(value: str, field_name: str) -> None:
    """Require a lowercase SHA-256 digest."""

    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def validate_content_hash(content_hash: str, expected_hash: str, label: str) -> None:
    """Validate a recomputed content digest."""

    require_sha256(content_hash, f"{label} content_hash")
    if content_hash != expected_hash:
        raise ValueError(f"{label} content hash mismatch")


__all__ = [
    "hash_components",
    "decimal_text",
    "require_aware",
    "require_finite",
    "require_nonnegative_int",
    "require_ordered_unique",
    "require_positive",
    "require_sha256",
    "require_text",
    "require_token",
    "require_unit_interval",
    "utc_text",
    "validate_content_hash",
]
