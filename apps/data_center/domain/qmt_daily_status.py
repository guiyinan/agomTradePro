"""Pure contract for native QMT daily suspension-status evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

_SCHEMA_VERSION = "qmt-native-daily-status.v1"
_BATCH_KIND = "daily_status"
_MAX_BATCH_SIZE = 500
_MAX_ASSET_CODE_LENGTH = 20
_MAX_REQUEST_SPAN_DAYS = 31
_CHINA_TIMEZONE = timezone(timedelta(hours=8))


class QmtDailyStatusValidationError(ValueError):
    """Raised when a native daily-status batch cannot be represented safely."""


class QmtDailyStatusState(StrEnum):
    """Normalized status labels that keep missing native values unknown."""

    NORMAL = "normal"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BridgeDailyStatusSample:
    """One QMT native suspension flag for an exact security and date."""

    asset_code: str
    bar_date: date
    suspend_flag: int | None

    def validate(self) -> None:
        """Validate the exact native fields without inferring missing status."""

        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or len(self.asset_code) > _MAX_ASSET_CODE_LENGTH
            or self.asset_code != self.asset_code.strip()
        ):
            raise QmtDailyStatusValidationError(
                "daily status asset_code must be bounded, nonempty, and unpadded"
            )
        if type(self.bar_date) is not date:
            raise QmtDailyStatusValidationError("daily status bar_date must be an exact date")
        if self.suspend_flag is not None and (
            type(self.suspend_flag) is not int or self.suspend_flag not in (-1, 0, 1)
        ):
            raise QmtDailyStatusValidationError("daily status suspend_flag is unsupported")

    @property
    def state(self) -> QmtDailyStatusState:
        """Return the native flag's explicit state; absent values stay unknown."""

        self.validate()
        if self.suspend_flag is None:
            return QmtDailyStatusState.UNKNOWN
        if self.suspend_flag == 1:
            return QmtDailyStatusState.SUSPENDED
        if self.suspend_flag == -1:
            return QmtDailyStatusState.RESUMED
        return QmtDailyStatusState.NORMAL


@dataclass(frozen=True, slots=True)
class BridgeDailyStatusBatch:
    """An immutable, request-scoped batch of source-native daily status rows.

    The self-reported date range constrains contained rows but does not prove
    completeness for that range or for any market universe.
    """

    batch_id: str
    kind: str
    collected_at: datetime
    request_start: date
    request_end: date
    samples: tuple[BridgeDailyStatusSample, ...]
    schema_version: str

    def validate(self, now: datetime) -> None:
        """Validate exact identity, declared coverage, and collection chronology."""

        self._validate_static_fields()
        _require_aware(self.collected_at, "collected_at")
        _require_aware(now, "now")
        if self.collected_at > now:
            raise QmtDailyStatusValidationError("daily status collection time is in the future")
        try:
            local_collection_date = self.collected_at.astimezone(_CHINA_TIMEZONE).date()
        except (OverflowError, ValueError) as error:
            raise QmtDailyStatusValidationError(
                "daily status collection time cannot be represented in China local time"
            ) from error
        if self.request_end >= local_collection_date:
            raise QmtDailyStatusValidationError(
                "daily status request_end must precede the China-local collection date"
            )

        unique_keys: set[tuple[str, date]] = set()
        for sample in self.samples:
            if type(sample) is not BridgeDailyStatusSample:
                raise QmtDailyStatusValidationError("daily status batch contains an untyped sample")
            sample.validate()
            if not self.request_start <= sample.bar_date <= self.request_end:
                raise QmtDailyStatusValidationError(
                    "daily status sample date is outside its declared request range"
                )
            key = (sample.asset_code, sample.bar_date)
            if key in unique_keys:
                raise QmtDailyStatusValidationError(
                    "daily status batch contains a duplicate asset and date"
                )
            unique_keys.add(key)

    def _validate_static_fields(self) -> None:
        """Validate schema, UUID, exact date types, request bounds and sample count."""

        if type(self.batch_id) is not str:
            raise QmtDailyStatusValidationError("daily status batch_id must be a canonical UUID")
        try:
            parsed_batch_id = UUID(self.batch_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise QmtDailyStatusValidationError(
                "daily status batch_id must be a canonical UUID"
            ) from error
        if str(parsed_batch_id) != self.batch_id:
            raise QmtDailyStatusValidationError(
                "daily status batch_id must use canonical UUID text"
            )
        if type(self.kind) is not str or self.kind != _BATCH_KIND:
            raise QmtDailyStatusValidationError("daily status kind is unsupported")
        if type(self.schema_version) is not str or self.schema_version != _SCHEMA_VERSION:
            raise QmtDailyStatusValidationError("daily status schema version is unsupported")
        if type(self.collected_at) is not datetime:
            raise QmtDailyStatusValidationError("daily status collected_at must be a datetime")
        if type(self.request_start) is not date or type(self.request_end) is not date:
            raise QmtDailyStatusValidationError("daily status request range must use exact dates")
        if self.request_start > self.request_end:
            raise QmtDailyStatusValidationError("daily status request range is inverted")
        if (self.request_end - self.request_start).days > _MAX_REQUEST_SPAN_DAYS:
            raise QmtDailyStatusValidationError("daily status request range exceeds 31 days")
        if type(self.samples) is not tuple or not 1 <= len(self.samples) <= _MAX_BATCH_SIZE:
            raise QmtDailyStatusValidationError(
                "daily status batch requires 1 through 500 samples in a tuple"
            )

    def to_payload(self) -> dict[str, object]:
        """Return the exact canonical wire fields using only recorded clocks."""

        self.validate(self.collected_at)
        return {
            "batch_id": self.batch_id,
            "kind": self.kind,
            "collected_at": self.collected_at.astimezone(UTC).isoformat(),
            "request_start": self.request_start.isoformat(),
            "request_end": self.request_end.isoformat(),
            "samples": [
                {
                    "asset_code": sample.asset_code,
                    "bar_date": sample.bar_date.isoformat(),
                    "suspend_flag": sample.suspend_flag,
                }
                for sample in self.samples
            ],
            "schema_version": self.schema_version,
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 digest of the complete canonical native payload."""

        canonical_payload = json.dumps(
            self.to_payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical_payload).hexdigest()


def _require_aware(value: object, field_name: str) -> datetime:
    """Require an exact aware datetime while translating failures to Domain error."""

    if type(value) is not datetime:
        raise QmtDailyStatusValidationError(f"daily status {field_name} must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise QmtDailyStatusValidationError(f"daily status {field_name} must be timezone-aware")
    except (OverflowError, TypeError, ValueError) as error:
        if isinstance(error, QmtDailyStatusValidationError):
            raise
        raise QmtDailyStatusValidationError(
            f"daily status {field_name} must be timezone-aware"
        ) from error
    return value


__all__ = (
    "BridgeDailyStatusBatch",
    "BridgeDailyStatusSample",
    "QmtDailyStatusState",
    "QmtDailyStatusValidationError",
)
