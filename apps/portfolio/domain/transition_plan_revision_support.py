"""Shared canonical validation and serialization helpers for plan revisions."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

PlanOutcome = Literal["allowed", "blocked", "partial", "unknown"]
ObservationPrecision = Literal["timestamp", "date", "unknown"]


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> None:
    """Require a bounded canonical identifier or user-facing policy token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_digest(value: object, field_name: str) -> None:
    """Require a lowercase hexadecimal SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    """Require an aware datetime without normalizing its source timezone."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_decimal(value: object, field_name: str, *, nonnegative: bool = True) -> None:
    """Require a finite exact Decimal and optionally reject negative values."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _decimal_text(value: Decimal | None) -> str | None:
    """Serialize exact Decimal values while retaining absence as null."""

    return str(value) if value is not None else None


def _datetime_text(value: datetime | None) -> str | None:
    """Serialize an original aware clock while preserving its offset."""

    return value.isoformat() if value is not None else None


def _date_text(value: date | None) -> str | None:
    """Serialize a date without inventing a time of day."""

    return value.isoformat() if value is not None else None


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash a JSON-safe object using a stable portfolio revision form."""

    data = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ObservationPrecision",
    "PlanOutcome",
    "_canonical_hash",
    "_date_text",
    "_datetime_text",
    "_decimal_text",
    "_require_aware",
    "_require_decimal",
    "_require_digest",
    "_require_token",
]
