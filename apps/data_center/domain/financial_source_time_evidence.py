"""Typed binding between one financial fact and an independent source-time artifact."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FINANCIAL_SOURCE_TIME_DATASET_KEY = "equity.financial.source-time"


class FinancialAvailabilityBasis(StrEnum):
    """The conservative basis used for a fact's first verified availability."""

    PROVIDER_NATIVE_EXACT = "provider_native_exact"


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeArtifactRef:
    """Reference one immutable response that contains provider-native source time."""

    capture_id: UUID
    location: str
    provider_name: str
    dataset_key: str
    requested_asset_code: str
    requested_announcement_date: date
    body_sha256: str
    body_size_bytes: int
    response_completed_at: datetime
    response_row_count: int
    format_version: str
    encryption_algorithm: str
    encryption_key_ref: str
    encryption_key_version: str

    def __post_init__(self) -> None:
        """Reject unscoped, mutable-looking, or non-UTC artifact metadata."""

        if not isinstance(self.capture_id, UUID):
            raise ValueError("FinancialSourceTimeArtifactRef.capture_id must be a UUID")
        for field_name, value, maximum in (
            ("location", self.location, 512),
            ("provider_name", self.provider_name, 128),
            ("dataset_key", self.dataset_key, 128),
            ("requested_asset_code", self.requested_asset_code, 64),
            ("format_version", self.format_version, 128),
            ("encryption_algorithm", self.encryption_algorithm, 128),
            ("encryption_key_ref", self.encryption_key_ref, 256),
            ("encryption_key_version", self.encryption_key_version, 128),
        ):
            _bounded_text(value, field_name, maximum)
        if self.dataset_key != FINANCIAL_SOURCE_TIME_DATASET_KEY:
            raise ValueError("financial source-time artifact dataset is invalid")
        if isinstance(self.requested_announcement_date, datetime) or not isinstance(
            self.requested_announcement_date, date
        ):
            raise ValueError("requested_announcement_date must be a date")
        if not _is_sha256(self.body_sha256):
            raise ValueError("financial source-time body_sha256 is invalid")
        if (
            isinstance(self.body_size_bytes, bool)
            or not isinstance(self.body_size_bytes, int)
            or self.body_size_bytes <= 0
        ):
            raise ValueError("financial source-time body_size_bytes must be positive")
        _aware_utc(self.response_completed_at, "response_completed_at")
        if (
            isinstance(self.response_row_count, bool)
            or not isinstance(self.response_row_count, int)
            or self.response_row_count <= 0
        ):
            raise ValueError("financial source-time response_row_count must be positive")

    def to_dict(self) -> dict[str, object]:
        """Return the exact non-secret artifact identity."""

        return {
            "capture_id": str(self.capture_id),
            "location": self.location,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "requested_asset_code": self.requested_asset_code,
            "requested_announcement_date": self.requested_announcement_date.isoformat(),
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "response_completed_at": self.response_completed_at.isoformat(),
            "response_row_count": self.response_row_count,
            "format_version": self.format_version,
            "encryption_algorithm": self.encryption_algorithm,
            "encryption_key_ref": self.encryption_key_ref,
            "encryption_key_version": self.encryption_key_version,
        }


@dataclass(frozen=True, slots=True)
class FinancialSourceTimeWitness:
    """Bind provider-native announcement time to one exact financial row."""

    artifact_reference: FinancialSourceTimeArtifactRef
    native_asset_code: str
    native_period_end: date
    financial_native_row_id: str
    financial_announced_date: date
    source_native_row_id: str
    source_timezone: str
    announced_at: datetime
    available_at: datetime
    row_projection_sha256: str
    governed_match_contract_id: str
    governed_match_contract_version: str
    governed_match_contract_sha256: str
    matched_row_count: int
    availability_basis: FinancialAvailabilityBasis

    def __post_init__(self) -> None:
        """Require an exact row relationship and conservative availability time."""

        if not isinstance(self.artifact_reference, FinancialSourceTimeArtifactRef):
            raise ValueError("FinancialSourceTimeWitness.artifact_reference must be typed")
        for field_name, value, maximum in (
            ("native_asset_code", self.native_asset_code, 64),
            ("financial_native_row_id", self.financial_native_row_id, 200),
            ("source_native_row_id", self.source_native_row_id, 200),
            ("source_timezone", self.source_timezone, 128),
            ("governed_match_contract_id", self.governed_match_contract_id, 128),
            ("governed_match_contract_version", self.governed_match_contract_version, 64),
        ):
            _bounded_text(value, field_name, maximum)
        if isinstance(self.native_period_end, datetime) or not isinstance(
            self.native_period_end, date
        ):
            raise ValueError("FinancialSourceTimeWitness.native_period_end must be a date")
        if isinstance(self.financial_announced_date, datetime) or not isinstance(
            self.financial_announced_date, date
        ):
            raise ValueError("FinancialSourceTimeWitness.financial_announced_date must be a date")
        _aware_utc(self.announced_at, "announced_at")
        _aware_utc(self.available_at, "available_at")
        if not _is_sha256(self.row_projection_sha256):
            raise ValueError("FinancialSourceTimeWitness.row_projection_sha256 is invalid")
        if not _is_sha256(self.governed_match_contract_sha256):
            raise ValueError("FinancialSourceTimeWitness governed contract hash is invalid")
        if self.matched_row_count != 1 or isinstance(self.matched_row_count, bool):
            raise ValueError("financial source-time match must resolve exactly one row")
        if not isinstance(self.availability_basis, FinancialAvailabilityBasis):
            raise ValueError("FinancialSourceTimeWitness.availability_basis must be typed")
        reference = self.artifact_reference
        if reference.requested_asset_code != self.native_asset_code:
            raise ValueError("financial source-time requested asset mismatch")
        try:
            source_zone = ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("financial source-time timezone is unknown") from exc
        if (
            self.announced_at.astimezone(source_zone).date()
            != reference.requested_announcement_date
        ):
            raise ValueError("financial source-time announcement date mismatch")
        if self.financial_announced_date != reference.requested_announcement_date:
            raise ValueError("financial announcement date does not match source-time request")
        if not self.announced_at <= self.available_at <= reference.response_completed_at:
            raise ValueError("financial source-time ordering is invalid")

    def to_dict(self) -> dict[str, object]:
        """Return the exact source-time row and artifact binding."""

        return {
            "artifact_reference": self.artifact_reference.to_dict(),
            "native_asset_code": self.native_asset_code,
            "native_period_end": self.native_period_end.isoformat(),
            "financial_native_row_id": self.financial_native_row_id,
            "financial_announced_date": self.financial_announced_date.isoformat(),
            "source_native_row_id": self.source_native_row_id,
            "source_timezone": self.source_timezone,
            "announced_at": self.announced_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "row_projection_sha256": self.row_projection_sha256,
            "governed_match_contract_id": self.governed_match_contract_id,
            "governed_match_contract_version": self.governed_match_contract_version,
            "governed_match_contract_sha256": self.governed_match_contract_sha256,
            "matched_row_count": self.matched_row_count,
            "availability_basis": self.availability_basis.value,
        }


def _bounded_text(value: object, field_name: str, maximum: int) -> None:
    """Require bounded canonical text without control characters."""

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"Financial source-time {field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"Financial source-time {field_name} contains control characters")


def _aware_utc(value: object, field_name: str) -> None:
    """Require one timezone-aware UTC instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"Financial source-time {field_name} must be timezone-aware UTC")


def _is_sha256(value: object) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "FINANCIAL_SOURCE_TIME_DATASET_KEY",
    "FinancialAvailabilityBasis",
    "FinancialSourceTimeArtifactRef",
    "FinancialSourceTimeWitness",
]
