"""Typed evidence for one bounded provider response.

The value objects in this module describe transport observations only.  They
do not turn a response completion time into a source announcement or
availability time, and they deliberately contain no row-level source
identity.  A later provider-specific parser must establish that binding
before a fact can be considered source-complete.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum


class FinancialResponseBodyScope(StrEnum):
    """The exact body scope covered by one captured response digest."""

    BATCH = "batch_response_body"
    RECORD = "record_response_body"


@dataclass(frozen=True, slots=True)
class FinancialRequestScope:
    """Non-sensitive dimensions requested from a financial provider."""

    provider_name: str
    dataset_key: str
    asset_code: str
    period_limit: int

    def __post_init__(self) -> None:
        """Reject padded or untyped request dimensions before capture."""

        _bounded_text(self.provider_name, "provider_name", 128)
        _bounded_text(self.dataset_key, "dataset_key", 128)
        _bounded_text(self.asset_code, "asset_code", 64)
        _positive_int(self.period_limit, "period_limit")

    def to_dict(self) -> dict[str, object]:
        """Return only the explicitly modelled, non-sensitive scope."""

        return {
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "asset_code": self.asset_code,
            "period_limit": self.period_limit,
        }


@dataclass(frozen=True, slots=True)
class FinancialResponseScope:
    """Caller-declared response coverage awaiting provider-body validation.

    The capture seam records these dimensions for later parser validation; it
    does not inspect the body or establish a row-level source binding.
    """

    asset_codes: tuple[str, ...]
    period_ends: tuple[date, ...]
    row_count: int

    def __post_init__(self) -> None:
        """Validate explicit response coverage without deriving source facts."""

        if not isinstance(self.asset_codes, tuple):
            raise ValueError("FinancialResponseScope.asset_codes must be a tuple")
        if not isinstance(self.period_ends, tuple):
            raise ValueError("FinancialResponseScope.period_ends must be a tuple")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int):
            raise ValueError("FinancialResponseScope.row_count must be an integer")
        if self.row_count < 0:
            raise ValueError("FinancialResponseScope.row_count cannot be negative")
        if self.row_count and not self.asset_codes:
            raise ValueError("FinancialResponseScope.asset_codes are required for rows")
        normalized_assets = tuple(
            _bounded_text(asset_code, "asset_codes", 64) for asset_code in self.asset_codes
        )
        if len(set(normalized_assets)) != len(normalized_assets):
            raise ValueError("FinancialResponseScope.asset_codes cannot contain duplicates")
        for period_end in self.period_ends:
            if isinstance(period_end, datetime) or not isinstance(period_end, date):
                raise ValueError("FinancialResponseScope.period_ends must contain dates")
        object.__setattr__(self, "asset_codes", normalized_assets)

    def to_dict(self) -> dict[str, object]:
        """Return caller-declared response coverage as JSON-compatible values."""

        return {
            "asset_codes": list(self.asset_codes),
            "period_ends": [period_end.isoformat() for period_end in self.period_ends],
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class FinancialResponseEvidence:
    """Hash, size, completion, and explicit scopes for one raw response."""

    body_sha256: str
    body_size_bytes: int
    response_completed_at: datetime
    request_scope: FinancialRequestScope
    response_scope: FinancialResponseScope
    body_scope: FinancialResponseBodyScope = FinancialResponseBodyScope.BATCH

    def __post_init__(self) -> None:
        """Require a raw-body digest and an aware UTC completion timestamp."""

        if not _is_sha256(self.body_sha256):
            raise ValueError("FinancialResponseEvidence.body_sha256 must be lowercase sha256")
        if isinstance(self.body_size_bytes, bool) or not isinstance(self.body_size_bytes, int):
            raise ValueError("FinancialResponseEvidence.body_size_bytes must be an integer")
        if self.body_size_bytes < 0:
            raise ValueError("FinancialResponseEvidence.body_size_bytes cannot be negative")
        _aware_utc(self.response_completed_at, "response_completed_at")
        if not isinstance(self.request_scope, FinancialRequestScope):
            raise ValueError("FinancialResponseEvidence.request_scope must be typed")
        if not isinstance(self.response_scope, FinancialResponseScope):
            raise ValueError("FinancialResponseEvidence.response_scope must be typed")
        if not isinstance(self.body_scope, FinancialResponseBodyScope):
            raise ValueError("FinancialResponseEvidence.body_scope must be typed")

    def to_dict(self) -> dict[str, object]:
        """Return safe transport evidence without body bytes or headers."""

        return {
            "evidence_basis": "raw_response_bytes",
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "response_completed_at": self.response_completed_at.isoformat(),
            "request_scope": self.request_scope.to_dict(),
            "response_scope": self.response_scope.to_dict(),
            "response_scope_basis": "caller_declared",
            "body_scope": self.body_scope.value,
        }


def raw_body_sha256(body: bytes) -> str:
    """Return the SHA-256 digest of the exact response bytes."""

    if not isinstance(body, bytes):
        raise ValueError("raw response body must be bytes")
    return hashlib.sha256(body).hexdigest()


def _bounded_text(value: object, field_name: str, max_length: int) -> str:
    """Validate a stable scope dimension without silently normalizing it."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"Financial scope {field_name} must be non-empty text")
    if value != value.strip():
        raise ValueError(f"Financial scope {field_name} cannot be padded")
    if len(value) > max_length:
        raise ValueError(f"Financial scope {field_name} is too long")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"Financial scope {field_name} contains control characters")
    return value


def _positive_int(value: object, field_name: str) -> int:
    """Validate one positive integer scope value."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Financial scope {field_name} must be positive")
    return value


def _aware_utc(value: datetime, field_name: str) -> None:
    """Require a timezone-aware UTC value, without converting local time."""

    if not isinstance(value, datetime):
        raise ValueError(f"FinancialResponseEvidence.{field_name} must be a datetime")
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError(f"FinancialResponseEvidence.{field_name} must be timezone-aware UTC")
    if offset != timedelta(0):
        raise ValueError(f"FinancialResponseEvidence.{field_name} must be UTC")


def _is_sha256(value: object) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "FinancialRequestScope",
    "FinancialResponseBodyScope",
    "FinancialResponseEvidence",
    "FinancialResponseScope",
    "raw_body_sha256",
]
