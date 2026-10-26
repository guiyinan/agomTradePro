"""Exact canonical formatting and validation primitives for fee proofs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID


def _canonical_uuid(value: str) -> str:
    """Require a canonical local UUID locator with no URL/path interpretation."""

    parsed = UUID(value)
    canonical = str(parsed)
    if canonical != value:
        raise ValueError("evidence locator must be a canonical local UUID")
    return canonical


def _parse_canonical_aware_datetime(value: str | None) -> datetime | None:
    """Parse only the policy timestamp spelling emitted by the snapshot helper."""

    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("policy timestamp must be a canonical string or null")
    parsed_text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(parsed_text)
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or _canonical_aware_datetime(parsed) != value
    ):
        raise ValueError("policy timestamp must use canonical UTC microseconds")
    return parsed


def _valid_sha256(value: str) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""

    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _currency_token(value: object) -> bool:
    """Require an explicit uppercase three-letter currency code, with no mapping."""

    return (
        type(value) is str
        and len(value) == 3
        and all("A" <= character <= "Z" for character in value)
    )


def _decimal_fixed(value: Decimal, places: int) -> str:
    """Format exact Decimal digits to a fixed scale without using context rounding."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("fingerprint Decimal must be finite")
    raw = format(value, "f")
    negative = raw.startswith("-")
    unsigned = raw[1:] if negative else raw
    integer, separator, fraction = unsigned.partition(".")
    if separator:
        while len(fraction) > places and fraction.endswith("0"):
            fraction = fraction[:-1]
        if len(fraction) > places:
            raise ValueError("fingerprint Decimal has unsupported precision")
    fraction = fraction.ljust(places, "0")
    sign = "-" if negative and (integer != "0" or any(ch != "0" for ch in fraction)) else ""
    return f"{sign}{integer}.{fraction}"


def _optional_decimal_fixed(value: Decimal | None, places: int) -> str | None:
    """Format an optional exact Decimal, retaining unknown as null."""

    return _decimal_fixed(value, places) if value is not None else None


def _canonical_aware_datetime(value: datetime) -> str:
    """Encode an aware timestamp in UTC with a stable microsecond scale."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _required_decimal(value: Decimal | None) -> Decimal:
    """Narrow a parsed fee value only after all known/precision checks pass."""

    if type(value) is not Decimal:
        raise ValueError("fee amount is unknown")
    return value
