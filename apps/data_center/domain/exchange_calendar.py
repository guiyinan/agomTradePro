"""Source-bound exchange calendar snapshots with explicit knowledge time."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

_CALENDAR_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExchangeCalendarError(ValueError):
    """Recognized, fail-closed invalid or unavailable exchange-calendar input."""

    def __init__(self, code: str, message: str) -> None:
        """Keep a stable machine code without importing application exceptions."""

        self.code = code
        super().__init__(message)


def _require_utc(value: datetime, field_name: str) -> None:
    """Require a timezone-aware UTC instant for source and knowledge evidence."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_TIME_INVALID",
            f"{field_name} must be timezone-aware UTC",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_TIME_INVALID",
            f"{field_name} must be timezone-aware UTC",
        )


def _require_date(value: date, field_name: str) -> None:
    """Reject datetime subclasses where a calendar date is required."""

    if type(value) is not date:
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_DATE_INVALID",
            f"{field_name} must be a date without a time component",
        )


def _require_text(value: str, field_name: str, maximum_length: int = 160) -> None:
    """Require bounded canonical non-empty identity text."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum_length
        or any(character.isspace() for character in value)
    ):
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_IDENTITY_INVALID",
            f"{field_name} must be bounded canonical text",
        )


def _matches_digest(pattern: re.Pattern[str], value: object) -> bool:
    """Check a digest token without leaking regex TypeError for malformed inputs."""

    return type(value) is str and pattern.fullmatch(value) is not None


def exchange_calendar_request_scope_hash(
    exchange: str,
    coverage_start: date,
    coverage_end: date,
) -> str:
    """Hash the exact unfiltered Tushare calendar request shape."""

    _require_text(exchange, "exchange", 32)
    _require_date(coverage_start, "coverage_start")
    _require_date(coverage_end, "coverage_end")
    if coverage_start > coverage_end:
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_COVERAGE_INVALID",
            "coverage_start cannot follow coverage_end",
        )
    material: dict[str, object] = {
        "api_name": "trade_cal",
        "exchange": exchange,
        "start_date": coverage_start.strftime("%Y%m%d"),
        "end_date": coverage_end.strftime("%Y%m%d"),
        "fields": _CALENDAR_FIELDS,
        "is_open_filter": None,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ExchangeCalendarDay:
    """One explicit open/closed state returned for one exchange date."""

    exchange: str
    calendar_date: date
    is_open: bool
    previous_open_date: date

    def __post_init__(self) -> None:
        """Reject ambiguous venue, date, state, and previous-session fields."""

        _require_text(self.exchange, "day.exchange", 32)
        _require_date(self.calendar_date, "day.calendar_date")
        _require_date(self.previous_open_date, "day.previous_open_date")
        if type(self.is_open) is not bool:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_STATE_INVALID",
                "day.is_open must be a boolean",
            )
        if self.previous_open_date >= self.calendar_date:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_PREVIOUS_OPEN_INVALID",
                "previous_open_date must precede calendar_date",
            )

    def to_payload(self) -> dict[str, object]:
        """Return the strict canonical wire representation for one date."""

        return {
            "exchange": self.exchange,
            "calendar_date": self.calendar_date.isoformat(),
            "is_open": self.is_open,
            "previous_open_date": self.previous_open_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarRawReference:
    """Exact source-response reference, distinct from normalized content hash."""

    payload_id: str
    payload_hash: str
    record_digest: str
    body_sha256: str
    retained_content_sha256: str
    request_scope_sha256: str
    original_body_retained: bool
    response_completed_at: datetime
    provider_name: str
    dataset_key: str
    transport: str

    def __post_init__(self) -> None:
        """Validate retained-body identity and local completion-time semantics."""

        try:
            parsed_id = UUID(self.payload_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw payload id must be a UUID",
            ) from exc
        if str(parsed_id) != self.payload_id:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw payload id must be canonical",
            )
        if not _matches_digest(_PREFIXED_SHA256_RE, self.payload_hash):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw payload hash is invalid",
            )
        if not _matches_digest(_PREFIXED_SHA256_RE, self.record_digest):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw record digest is invalid",
            )
        if not _matches_digest(_SHA256_RE, self.body_sha256):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "original body digest is invalid",
            )
        if self.retained_content_sha256 != self.body_sha256:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "calendar source evidence requires exact retained original bytes",
            )
        if not _matches_digest(_SHA256_RE, self.request_scope_sha256):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "request scope digest is invalid",
            )
        if self.original_body_retained is not True:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_BODY_NOT_RETAINED",
                "calendar source evidence requires retained original response bytes",
            )
        _require_utc(self.response_completed_at, "raw_reference.response_completed_at")
        _require_text(self.provider_name, "raw_reference.provider_name", 100)
        _require_text(self.dataset_key, "raw_reference.dataset_key", 160)
        if type(self.transport) is not str or self.transport not in {"direct", "egress"}:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw response transport is unsupported",
            )

    def to_payload(self) -> dict[str, object]:
        """Return the exact persisted RawPayload identity and byte evidence."""

        return {
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "record_digest": self.record_digest,
            "body_sha256": self.body_sha256,
            "retained_content_sha256": self.retained_content_sha256,
            "request_scope_sha256": self.request_scope_sha256,
            "original_body_retained": self.original_body_retained,
            "response_completed_at": self.response_completed_at.isoformat(),
            "response_time_semantics": "local_response_body_completion",
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "transport": self.transport,
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSnapshotCandidate:
    """Complete, validated source response before its first database write."""

    exchange: str
    coverage_start: date
    coverage_end: date
    days: tuple[ExchangeCalendarDay, ...]
    provider_name: str
    raw_reference: ExchangeCalendarRawReference
    first_seen_at: datetime
    source_published_at: datetime | None = None

    def __post_init__(self) -> None:
        """Require exact daily coverage and bind the local first-seen clock."""

        _require_text(self.exchange, "exchange", 32)
        _require_text(self.provider_name, "provider_name", 100)
        _require_date(self.coverage_start, "coverage_start")
        _require_date(self.coverage_end, "coverage_end")
        if self.coverage_start > self.coverage_end:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_COVERAGE_INVALID",
                "coverage_start cannot follow coverage_end",
            )
        if not isinstance(self.days, tuple) or not self.days:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE",
                "calendar snapshot must contain every requested calendar date",
            )
        if any(not isinstance(item, ExchangeCalendarDay) for item in self.days):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_DAY_INVALID",
                "calendar day rows must be typed",
            )
        if not isinstance(self.raw_reference, ExchangeCalendarRawReference):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID",
                "raw reference must be typed",
            )
        _require_utc(self.first_seen_at, "first_seen_at")
        if self.first_seen_at != self.raw_reference.response_completed_at:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_FIRST_SEEN_MISMATCH",
                "first_seen_at must equal local response completion time",
            )
        if self.raw_reference.provider_name != self.provider_name:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_PROVIDER_MISMATCH",
                "raw response provider does not match snapshot provider",
            )
        expected_scope = exchange_calendar_request_scope_hash(
            self.exchange,
            self.coverage_start,
            self.coverage_end,
        )
        if self.raw_reference.request_scope_sha256 != expected_scope:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH",
                "raw request scope does not match snapshot scope",
            )
        if self.source_published_at is not None:
            _require_utc(self.source_published_at, "source_published_at")
        expected_count = (self.coverage_end - self.coverage_start).days + 1
        if len(self.days) != expected_count:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE",
                "calendar snapshot does not cover every requested date",
            )
        previous_open_date = self.days[0].previous_open_date
        for index, item in enumerate(self.days):
            expected_date = self.coverage_start.fromordinal(self.coverage_start.toordinal() + index)
            if item.calendar_date != expected_date:
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE",
                    "calendar dates must be complete, ordered, and unique",
                )
            if item.exchange != self.exchange:
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_EXCHANGE_MISMATCH",
                    "calendar day exchange does not match snapshot exchange",
                )
            if item.previous_open_date != previous_open_date:
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_PREVIOUS_OPEN_MISMATCH",
                    "previous_open_date does not match the prior open day in coverage",
                )
            if item.is_open:
                previous_open_date = item.calendar_date

    @property
    def content_hash(self) -> str:
        """Hash normalized calendar content and its exact source reference."""

        return _sha256_payload(self.to_content_payload())

    def to_content_payload(self) -> dict[str, object]:
        """Return content fields, excluding database-assigned identity/time."""

        return {
            "schema": "exchange-calendar-snapshot-v1",
            "exchange": self.exchange,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "days": [item.to_payload() for item in self.days],
            "provider_name": self.provider_name,
            "raw_reference": self.raw_reference.to_payload(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "source_published_at": (
                self.source_published_at.isoformat()
                if self.source_published_at is not None
                else None
            ),
        }

    def to_payload(self) -> dict[str, object]:
        """Return complete typed candidate content for storage and consumers."""

        return {
            **self.to_content_payload(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSnapshot:
    """Immutable first-recorded calendar fact with exact source and knowledge time."""

    snapshot_id: str
    candidate: ExchangeCalendarSnapshotCandidate
    recorded_at: datetime
    content_hash: str
    record_digest: str

    def __post_init__(self) -> None:
        """Verify database identity, write time, and both distinct hash meanings."""

        try:
            parsed_id = UUID(self.snapshot_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_SNAPSHOT_ID_INVALID",
                "snapshot id must be a UUID",
            ) from exc
        if str(parsed_id) != self.snapshot_id:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_SNAPSHOT_ID_INVALID",
                "snapshot id must be canonical",
            )
        if not isinstance(self.candidate, ExchangeCalendarSnapshotCandidate):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_SNAPSHOT_INVALID",
                "snapshot candidate must be typed",
            )
        _require_utc(self.recorded_at, "recorded_at")
        if self.recorded_at < self.candidate.first_seen_at:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
                "recorded_at cannot precede first_seen_at",
            )
        if self.content_hash != self.candidate.content_hash:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_CONTENT_HASH_MISMATCH",
                "snapshot content hash does not match normalized source content",
            )
        if not _matches_digest(_PREFIXED_SHA256_RE, self.record_digest):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RECORD_DIGEST_INVALID",
                "snapshot record digest is invalid",
            )
        expected_digest = exchange_calendar_snapshot_record_digest(self)
        if self.record_digest != expected_digest:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_RECORD_DIGEST_MISMATCH",
                "snapshot record digest does not match persisted fields",
            )

    @property
    def exchange(self) -> str:
        """Return the exact exchange identity carried by this fact."""

        return self.candidate.exchange

    @property
    def coverage_start(self) -> date:
        """Return the first explicitly covered calendar date."""

        return self.candidate.coverage_start

    @property
    def coverage_end(self) -> date:
        """Return the last explicitly covered calendar date."""

        return self.candidate.coverage_end

    @property
    def days(self) -> tuple[ExchangeCalendarDay, ...]:
        """Return every explicitly observed open/closed day in coverage."""

        return self.candidate.days

    @property
    def provider_name(self) -> str:
        """Return the exact source identity for this response."""

        return self.candidate.provider_name

    @property
    def raw_reference(self) -> ExchangeCalendarRawReference:
        """Return the original provider response reference."""

        return self.candidate.raw_reference

    @property
    def first_seen_at(self) -> datetime:
        """Return local response completion, not upstream observation time."""

        return self.candidate.first_seen_at

    @property
    def source_published_at(self) -> datetime | None:
        """Return source publication time only when the provider supplies it."""

        return self.candidate.source_published_at

    def to_payload(self) -> dict[str, object]:
        """Return exact fact data plus derived reference-only capability markers.

        The capability markers are deliberately outside candidate content and
        both digests. A calendar snapshot has no publication binding in this
        slice, so its payload must remain unusable for decisions or execution.
        """

        return {
            **self.candidate.to_content_payload(),
            "snapshot_id": self.snapshot_id,
            "recorded_at": self.recorded_at.isoformat(),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
            "publication_status": "unpublished",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "blocked_reason": "exchange_calendar_unpublished_reference",
        }

    def reference(self) -> ExchangeCalendarSnapshotReference:
        """Return an exact immutable lookup key, not a publication claim."""

        return ExchangeCalendarSnapshotReference(
            snapshot_id=self.snapshot_id,
            exchange=self.exchange,
            coverage_start=self.coverage_start,
            coverage_end=self.coverage_end,
            content_hash=self.content_hash,
            record_digest=self.record_digest,
            raw_payload_id=self.raw_reference.payload_id,
            raw_payload_hash=self.raw_reference.payload_hash,
            raw_record_digest=self.raw_reference.record_digest,
        )


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSnapshotReference:
    """Exact snapshot identity plus source binding used for point reads."""

    snapshot_id: str
    exchange: str
    coverage_start: date
    coverage_end: date
    content_hash: str
    record_digest: str
    raw_payload_id: str
    raw_payload_hash: str
    raw_record_digest: str

    def __post_init__(self) -> None:
        """Reject references that could select a different source snapshot."""

        try:
            if str(UUID(self.snapshot_id)) != self.snapshot_id:
                raise ValueError
            if str(UUID(self.raw_payload_id)) != self.raw_payload_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_REFERENCE_INVALID",
                "snapshot and raw payload ids must be canonical UUIDs",
            ) from exc
        _require_text(self.exchange, "reference.exchange", 32)
        _require_date(self.coverage_start, "reference.coverage_start")
        _require_date(self.coverage_end, "reference.coverage_end")
        if self.coverage_start > self.coverage_end:
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_REFERENCE_INVALID",
                "reference coverage is inverted",
            )
        for name, value in (
            ("content_hash", self.content_hash),
            ("record_digest", self.record_digest),
            ("raw_record_digest", self.raw_record_digest),
        ):
            if not _matches_digest(_PREFIXED_SHA256_RE, value):
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_REFERENCE_INVALID",
                    f"reference {name} is invalid",
                )
        if not _matches_digest(_PREFIXED_SHA256_RE, self.raw_payload_hash):
            raise ExchangeCalendarError(
                "EXCHANGE_CALENDAR_REFERENCE_INVALID",
                "reference raw_payload_hash is invalid",
            )

    def to_payload(self) -> dict[str, object]:
        """Return the exact snapshot and raw-source identity."""

        return {
            "snapshot_id": self.snapshot_id,
            "exchange": self.exchange,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
            "raw_payload_id": self.raw_payload_id,
            "raw_payload_hash": self.raw_payload_hash,
            "raw_record_digest": self.raw_record_digest,
        }


def make_exchange_calendar_snapshot(
    candidate: ExchangeCalendarSnapshotCandidate,
    *,
    snapshot_id: str,
    recorded_at: datetime,
) -> ExchangeCalendarSnapshot:
    """Build one first-recorded fact after its repository has minted knowledge time."""

    partial = _snapshot_record_material(
        snapshot_id=snapshot_id,
        candidate=candidate,
        recorded_at=recorded_at,
    )
    return ExchangeCalendarSnapshot(
        snapshot_id=snapshot_id,
        candidate=candidate,
        recorded_at=recorded_at,
        content_hash=candidate.content_hash,
        record_digest=_sha256_payload(partial),
    )


def exchange_calendar_snapshot_record_digest(snapshot: ExchangeCalendarSnapshot) -> str:
    """Hash the full persisted record, including ID and DB knowledge time."""

    return _sha256_payload(
        _snapshot_record_material(
            snapshot_id=snapshot.snapshot_id,
            candidate=snapshot.candidate,
            recorded_at=snapshot.recorded_at,
        )
    )


def next_exchange_calendar_session(
    snapshot: ExchangeCalendarSnapshot,
    *,
    after_date: date,
) -> date:
    """Return the next explicitly open day or raise a typed coverage block."""

    _require_date(after_date, "after_date")
    if after_date < snapshot.coverage_start or after_date >= snapshot.coverage_end:
        raise ExchangeCalendarError(
            "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED",
            "snapshot does not cover a date after the requested day",
        )
    for item in snapshot.days:
        if item.calendar_date > after_date and item.is_open:
            return item.calendar_date
    raise ExchangeCalendarError(
        "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED",
        "no explicitly open next session exists in snapshot coverage",
    )


def _snapshot_record_material(
    *,
    snapshot_id: str,
    candidate: ExchangeCalendarSnapshotCandidate,
    recorded_at: datetime,
) -> dict[str, object]:
    """Return all stored fact fields except the digest itself."""

    return {
        "snapshot_id": snapshot_id,
        "candidate": candidate.to_content_payload(),
        "recorded_at": recorded_at.isoformat(),
        "content_hash": candidate.content_hash,
    }


def _sha256_payload(payload: dict[str, object]) -> str:
    """Hash canonical JSON using an explicit algorithm prefix."""

    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "ExchangeCalendarDay",
    "ExchangeCalendarError",
    "ExchangeCalendarRawReference",
    "ExchangeCalendarSnapshot",
    "ExchangeCalendarSnapshotCandidate",
    "ExchangeCalendarSnapshotReference",
    "exchange_calendar_request_scope_hash",
    "exchange_calendar_snapshot_record_digest",
    "make_exchange_calendar_snapshot",
    "next_exchange_calendar_session",
]
