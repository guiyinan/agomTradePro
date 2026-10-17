"""Immutable exact exchange-calendar evidence for simulated settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
    _hash_calendar_payload,
    _hash_payload,
    _require_aware,
    _require_calendar_fact_hash,
    _require_calendar_hash,
    _require_hash,
    _require_token,
    _require_utc,
    _utc_text,
)


@dataclass(frozen=True, slots=True)
class RawCalendarReference:
    """Exact raw-response identity attached to one parsed calendar snapshot."""

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
        """Validate raw-response identity without treating fetch time as source time."""

        try:
            if str(UUID(self.payload_id)) != self.payload_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "raw calendar payload_id must be a canonical UUID"
            ) from error
        for field_name in ("provider_name", "dataset_key"):
            _require_token(getattr(self, field_name), field_name)
        for field_name in ("payload_hash", "record_digest"):
            _require_calendar_hash(getattr(self, field_name), field_name)
        for field_name in ("body_sha256", "retained_content_sha256", "request_scope_sha256"):
            _require_hash(getattr(self, field_name), field_name)
        if self.retained_content_sha256 != self.body_sha256:
            raise CalendarEvidenceValidationError(
                "calendar response must retain its exact original body"
            )
        if type(self.original_body_retained) is not bool or not self.original_body_retained:
            raise CalendarEvidenceValidationError(
                "execution calendar requires an exact retained original response body"
            )
        _require_utc(self.response_completed_at, "response_completed_at")
        if self.transport not in {"direct", "egress"}:
            raise CalendarEvidenceValidationError("calendar transport is unsupported")

    def to_payload(self) -> dict[str, object]:
        """Return all raw reference fields in their canonical form."""

        self.__post_init__()
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
class ExchangeCalendarDay:
    """One explicit open/closed date from a complete exchange calendar snapshot."""

    exchange: str
    calendar_date: date
    is_open: bool
    previous_open_date: date

    def __post_init__(self) -> None:
        """Validate one date fact without deriving it from weekday arithmetic."""

        _require_token(self.exchange, "exchange")
        if type(self.calendar_date) is not date:
            raise CalendarEvidenceValidationError("calendar_date must be an exact date")
        if type(self.is_open) is not bool:
            raise CalendarEvidenceValidationError("is_open must be an explicit boolean fact")
        if type(self.previous_open_date) is not date:
            raise CalendarEvidenceValidationError("previous_open_date must be a date")
        if self.previous_open_date >= self.calendar_date:
            raise CalendarEvidenceValidationError("previous_open_date must precede calendar_date")

    def to_payload(self) -> dict[str, object]:
        """Return the explicit date fact for canonical hashing."""

        self.__post_init__()
        return {
            "exchange": self.exchange,
            "calendar_date": self.calendar_date.isoformat(),
            "is_open": self.is_open,
            "previous_open_date": self.previous_open_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExchangeCalendarSnapshot:
    """Immutable full-day calendar facts and their local knowledge timestamps."""

    snapshot_id: str
    exchange: str
    coverage_start: date
    coverage_end: date
    days: tuple[ExchangeCalendarDay, ...]
    provider_name: str
    raw_reference: RawCalendarReference
    content_hash: str
    record_digest: str
    first_seen_at: datetime
    recorded_at: datetime
    source_published_at: datetime | None = None

    def __post_init__(self) -> None:
        """Revalidate the published candidate's exact hash and DB record digest."""

        try:
            if str(UUID(self.snapshot_id)) != self.snapshot_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError(
                "calendar snapshot_id must be a canonical UUID"
            ) from error
        _require_token(self.exchange, "exchange")
        _require_token(self.provider_name, "provider_name")
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise CalendarEvidenceValidationError("calendar coverage bounds must be dates")
        if self.coverage_start > self.coverage_end:
            raise CalendarEvidenceValidationError("calendar coverage range is reversed")
        if type(self.days) is not tuple or not self.days:
            raise CalendarEvidenceValidationError("calendar snapshot requires a nonempty day tuple")
        if any(type(day) is not ExchangeCalendarDay for day in self.days):
            raise CalendarEvidenceValidationError(
                "calendar days must contain exact ExchangeCalendarDay values"
            )
        if type(self.raw_reference) is not RawCalendarReference:
            raise CalendarEvidenceValidationError("raw_reference must be RawCalendarReference")
        RawCalendarReference.__post_init__(self.raw_reference)
        _require_utc(self.first_seen_at, "first_seen_at")
        _require_utc(self.recorded_at, "recorded_at")
        if self.source_published_at is not None:
            _require_utc(self.source_published_at, "source_published_at")
        if self.first_seen_at != self.raw_reference.response_completed_at:
            raise CalendarEvidenceValidationError(
                "first_seen_at must equal the raw response completion time"
            )
        if self.raw_reference.provider_name != self.provider_name:
            raise CalendarEvidenceValidationError(
                "calendar raw provider differs from the snapshot provider"
            )
        if self.recorded_at < self.first_seen_at:
            raise CalendarEvidenceValidationError(
                "calendar recorded_at cannot precede first_seen_at"
            )
        if self.days[0].calendar_date != self.coverage_start:
            raise CalendarEvidenceValidationError(
                "calendar coverage_start must equal the first explicit day"
            )
        if self.days[-1].calendar_date != self.coverage_end:
            raise CalendarEvidenceValidationError(
                "calendar coverage_end must equal the last explicit day"
            )
        previous_day: date | None = None
        last_open_day: date = self.days[0].previous_open_date
        expected_days = (self.coverage_end - self.coverage_start).days + 1
        if len(self.days) != expected_days:
            raise CalendarEvidenceValidationError(
                "calendar snapshot must explicitly cover every requested date"
            )
        for index, day in enumerate(self.days):
            try:
                ExchangeCalendarDay.__post_init__(day)
            except SimulatedSettlementContractError as error:
                raise CalendarEvidenceValidationError(str(error)) from error
            if day.exchange != self.exchange:
                raise CalendarEvidenceValidationError(
                    "calendar day exchange differs from its snapshot scope"
                )
            expected_date = self.coverage_start.fromordinal(self.coverage_start.toordinal() + index)
            if day.calendar_date != expected_date:
                raise CalendarEvidenceValidationError(
                    "calendar snapshot must explicitly cover every date in its range"
                )
            if day.previous_open_date != last_open_day:
                raise CalendarEvidenceValidationError(
                    "previous_open_date does not match the prior explicit open date"
                )
            previous_day = day.calendar_date
            if day.is_open:
                last_open_day = day.calendar_date
        if previous_day != self.coverage_end:
            raise CalendarEvidenceValidationError("calendar coverage_end does not match its days")
        expected_content_hash = _hash_calendar_payload(self._candidate_payload())
        if self.content_hash and self.content_hash != expected_content_hash:
            raise CalendarEvidenceValidationError(
                "calendar content_hash does not match the normalized source content"
            )
        object.__setattr__(self, "content_hash", expected_content_hash)
        expected_record_digest = _hash_calendar_payload(
            {
                "snapshot_id": self.snapshot_id,
                "candidate": self._candidate_payload(),
                "recorded_at": self.recorded_at.isoformat(),
                "content_hash": expected_content_hash,
            }
        )
        if self.record_digest and self.record_digest != expected_record_digest:
            raise CalendarEvidenceValidationError(
                "calendar record_digest does not match its persisted identity"
            )
        object.__setattr__(self, "record_digest", expected_record_digest)

    def _candidate_payload(self) -> dict[str, object]:
        """Return the exact content-only schema used by the calendar owner."""

        return {
            "schema": "exchange-calendar-snapshot-v1",
            "exchange": self.exchange,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "days": [day.to_payload() for day in self.days],
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
        """Return the exact persisted calendar fact and both hashes."""

        self.__post_init__()
        return {
            **self._candidate_payload(),
            "snapshot_id": self.snapshot_id,
            "recorded_at": self.recorded_at.isoformat(),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
        }


@dataclass(frozen=True, slots=True)
class CalendarPublicationReference:
    """Explicit publication member, policy, and reference-validity binding."""

    publication_id: str
    member_id: str
    publication_hash: str
    fact_content_hash: str
    policy_hash: str
    published_at: datetime
    recorded_at: datetime
    reference_valid_from: datetime
    reference_valid_until: datetime
    timezone_name: str

    def __post_init__(self) -> None:
        """Validate publication identity, policy window, and exchange timezone."""

        _require_token(self.publication_id, "publication_id")
        _require_token(self.member_id, "member_id")
        _require_calendar_fact_hash(self.publication_hash, "publication_hash")
        _require_calendar_fact_hash(self.fact_content_hash, "fact_content_hash")
        _require_calendar_fact_hash(self.policy_hash, "policy_hash")
        for field_name in (
            "published_at",
            "recorded_at",
            "reference_valid_from",
            "reference_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if self.published_at > self.recorded_at:
            raise CalendarEvidenceValidationError(
                "publication recorded_at cannot precede published_at"
            )
        if self.reference_valid_from >= self.reference_valid_until:
            raise CalendarEvidenceValidationError("calendar reference validity window is invalid")
        _require_token(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise CalendarEvidenceValidationError(
                "calendar publication timezone is unknown"
            ) from error

    def to_payload(self) -> dict[str, object]:
        """Return all publication fields used to bind the calendar evidence."""

        self.__post_init__()
        return {
            "publication_id": self.publication_id,
            "member_id": self.member_id,
            "publication_hash": self.publication_hash,
            "fact_content_hash": self.fact_content_hash,
            "policy_hash": self.policy_hash,
            "published_at": _utc_text(self.published_at),
            "recorded_at": _utc_text(self.recorded_at),
            "reference_valid_from": _utc_text(self.reference_valid_from),
            "reference_valid_until": _utc_text(self.reference_valid_until),
            "timezone_name": self.timezone_name,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCalendarEvidence:
    """Bind a complete calendar snapshot to an exact published reference."""

    snapshot: ExchangeCalendarSnapshot
    publication: CalendarPublicationReference | None

    def __post_init__(self) -> None:
        """Revalidate the snapshot and require exact publication-member binding."""

        if type(self.snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarEvidenceValidationError("snapshot must be ExchangeCalendarSnapshot")
        try:
            ExchangeCalendarSnapshot.__post_init__(self.snapshot)
        except CalendarEvidenceValidationError:
            raise
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise CalendarEvidenceValidationError("calendar snapshot failed validation") from error
        if self.publication is not None:
            if type(self.publication) is not CalendarPublicationReference:
                raise CalendarEvidenceValidationError(
                    "publication must be CalendarPublicationReference or None"
                )
            try:
                CalendarPublicationReference.__post_init__(self.publication)
            except CalendarEvidenceValidationError:
                raise
            except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
                raise CalendarEvidenceValidationError(
                    "publication reference failed validation"
                ) from error
            if self.publication.member_id != self.snapshot.snapshot_id:
                raise CalendarEvidenceValidationError(
                    "publication member ID must bind the exact calendar snapshot"
                )

    @property
    def evidence_hash(self) -> str:
        """Return a digest binding snapshot, publication, policy, and knowledge clocks."""

        self.__post_init__()
        return _hash_payload(
            {
                "snapshot": self.snapshot.to_payload(),
                "publication": (
                    self.publication.to_payload() if self.publication is not None else None
                ),
            }
        )

    @property
    def publication_reference(self) -> str:
        """Return the exact publication/member reference persisted on a pending trade."""

        self.__post_init__()
        if self.publication is None:
            raise CalendarEvidenceValidationError(
                "calendar snapshot has no formal publication reference"
            )
        return f"{self.publication.publication_id}/{self.snapshot.snapshot_id}"

    def validate_for(self, as_of: datetime) -> None:
        """Require a known, published, in-window reference at the requested cutoff."""

        self.__post_init__()
        _require_aware(as_of, "as_of")
        publication = self.publication
        if publication is None:
            raise CalendarEvidenceValidationError(
                "reference-only calendar snapshots cannot authorize settlement"
            )
        if (
            self.snapshot.first_seen_at > as_of
            or self.snapshot.recorded_at > as_of
            or publication.published_at > as_of
            or publication.recorded_at > as_of
        ):
            raise CalendarEvidenceValidationError(
                "calendar snapshot or publication was not known at the cutoff"
            )
        for source_time in (self.snapshot.source_published_at,):
            if source_time is not None and source_time > as_of:
                raise CalendarEvidenceValidationError(
                    "calendar source timestamp is later than the knowledge cutoff"
                )
        if not publication.reference_valid_from <= as_of < publication.reference_valid_until:
            raise CalendarEvidenceValidationError(
                "calendar publication reference is outside its validity window"
            )

    def current_open_session(self, as_of: datetime) -> date:
        """Resolve the explicit open session for the cutoff's published exchange timezone."""

        self.validate_for(as_of)
        publication = self.publication
        if publication is None:
            raise CalendarEvidenceValidationError("calendar publication is unavailable")
        try:
            local_date = as_of.astimezone(ZoneInfo(publication.timezone_name)).date()
        except (OverflowError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise CalendarEvidenceValidationError(
                "cutoff cannot be mapped to the published exchange timezone"
            ) from error
        day = next(
            (row for row in self.snapshot.days if row.calendar_date == local_date),
            None,
        )
        if day is None:
            raise CalendarEvidenceValidationError(
                "calendar snapshot does not cover the cutoff's exchange-local date"
            )
        if not day.is_open:
            raise CalendarEvidenceValidationError(
                "settlement-bound simulated trades require an explicit open session"
            )
        return local_date

    def release_session(self, trade_session: date, lag_sessions: int) -> date:
        """Advance by an explicit number of open sessions without weekday inference."""

        self.__post_init__()
        if type(trade_session) is not date:
            raise CalendarEvidenceValidationError("trade_session must be an exact date")
        if type(lag_sessions) is not int or lag_sessions < 0:
            raise CalendarEvidenceValidationError(
                "lag_sessions must be an explicit nonnegative integer"
            )
        dates = {row.calendar_date: row for row in self.snapshot.days}
        trade_day = dates.get(trade_session)
        if trade_day is None or not trade_day.is_open:
            raise CalendarEvidenceValidationError(
                "settlement trade date is not an explicitly open covered session"
            )
        if lag_sessions == 0:
            return trade_session
        elapsed = 0
        for row in self.snapshot.days:
            if row.calendar_date <= trade_session or not row.is_open:
                continue
            elapsed += 1
            if elapsed == lag_sessions:
                return row.calendar_date
        raise CalendarEvidenceValidationError(
            "calendar snapshot does not cover enough future open sessions"
        )

    def elapsed_open_sessions(self, trade_session: date, through_session: date) -> int:
        """Count actual current-calendar open sessions after the stored trade date."""

        self.__post_init__()
        if type(trade_session) is not date or type(through_session) is not date:
            raise CalendarEvidenceValidationError("settlement boundaries must be exact dates")
        if trade_session > through_session:
            raise CalendarEvidenceValidationError("settlement through-date precedes trade date")
        if (
            trade_session < self.snapshot.coverage_start
            or through_session > self.snapshot.coverage_end
        ):
            raise CalendarEvidenceValidationError(
                "current calendar does not cover the complete settlement interval"
            )
        days = {row.calendar_date: row for row in self.snapshot.days}
        trade_day = days.get(trade_session)
        through_day = days.get(through_session)
        if trade_day is None or not trade_day.is_open:
            raise CalendarEvidenceValidationError(
                "stored trade date is not an explicitly open calendar session"
            )
        if through_day is None or not through_day.is_open:
            raise CalendarEvidenceValidationError(
                "current date is not an explicitly open calendar session"
            )
        return sum(
            1
            for row in self.snapshot.days
            if trade_session < row.calendar_date <= through_session and row.is_open
        )
