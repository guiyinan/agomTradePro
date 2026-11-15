"""Reference-only resolution of date-only financial availability to a session open.

The resolver consumes already-typed, exact formal calendar and opening-rule
evidence. It does not load those records, prove a database approval, discover
rule exceptions, update a financial fact, or authorize decision use.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    next_exchange_calendar_session,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
    CalendarPublicationPointerExpectation,
    exchange_calendar_publication_key,
    validate_current_calendar_publication,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RULE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RULE_HASH_DOMAIN = b"agomtradepro:exchange-session-opening-rule:v1\0"
_RULE_PAYLOAD_KEYS = frozenset(
    {
        "exchange",
        "phase",
        "rule_version",
        "source_uri",
        "source_body_sha256",
        "effective_start",
        "effective_end",
        "timezone_name",
        "local_open_time",
        "first_seen_at",
        "recorded_at",
        "approved_at",
    }
)


class FinancialNextSessionAvailabilityError(ValueError):
    """A source date, calendar publication, or opening rule cannot be resolved."""

    def __init__(self, code: str, message: str) -> None:
        """Retain a stable machine reason for each fail-closed condition."""

        self.code = code
        super().__init__(message)


class ExchangeSessionOpeningPhase(StrEnum):
    """An explicitly selected exchange session phase; neither phase is default."""

    OPENING_CALL_AUCTION = "opening_call_auction"
    CONTINUOUS_AUCTION = "continuous_auction"


@dataclass(frozen=True, slots=True)
class ExchangeSessionOpeningRule:
    """One immutable, source-bound session-opening rule value.

    ``approved_at`` is a supplied knowledge timestamp, not proof of a database
    approval event. A composition root must reload and verify the authoritative
    rule record and any date-specific adjustment before decision use.
    """

    exchange: str
    phase: ExchangeSessionOpeningPhase
    rule_version: str
    source_uri: str
    source_body_sha256: str
    effective_start: date
    effective_end: date
    timezone_name: str
    local_open_time: time
    first_seen_at: datetime
    recorded_at: datetime
    approved_at: datetime
    rule_sha256: str

    def __post_init__(self) -> None:
        """Validate explicit source, scope, clock, and content identity."""

        if type(self.exchange) is not str:
            raise ValueError("opening rule exchange must be text")
        try:
            expected_publication_key = exchange_calendar_publication_key(self.exchange)
        except (CalendarFormalPublicationError, TypeError, ValueError) as error:
            raise ValueError("opening rule exchange is invalid") from error
        if not expected_publication_key:
            raise ValueError("opening rule exchange is invalid")
        if type(self.phase) is not ExchangeSessionOpeningPhase:
            raise ValueError("opening rule phase must be explicit and typed")
        if (
            type(self.rule_version) is not str
            or _RULE_VERSION_RE.fullmatch(self.rule_version) is None
        ):
            raise ValueError("opening rule version is invalid")
        _validate_source_uri(self.source_uri)
        _require_sha256(self.source_body_sha256, "source_body_sha256")
        _require_date(self.effective_start, "effective_start")
        _require_date(self.effective_end, "effective_end")
        if self.effective_start > self.effective_end:
            raise ValueError("opening rule effective date range is inverted")
        if (
            type(self.timezone_name) is not str
            or not self.timezone_name
            or len(self.timezone_name) > 128
        ):
            raise ValueError("opening rule timezone must be explicit")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("opening rule timezone is unknown") from error
        if (
            type(self.local_open_time) is not time
            or self.local_open_time.tzinfo is not None
            or self.local_open_time.fold != 0
        ):
            raise ValueError("opening rule local clock must be an unambiguous naive wall time")
        _require_utc(self.first_seen_at, "first_seen_at")
        _require_utc(self.recorded_at, "recorded_at")
        _require_utc(self.approved_at, "approved_at")
        if not self.first_seen_at <= self.recorded_at <= self.approved_at:
            raise ValueError("opening rule knowledge times are not ordered")
        _require_sha256(self.rule_sha256, "rule_sha256")
        if self.rule_sha256 != exchange_session_opening_rule_sha256(self._payload()):
            raise ValueError("opening rule hash does not match its exact content")

    @property
    def identity(self) -> str:
        """Return the version and digest needed to re-read this exact rule."""

        self.__post_init__()
        return f"exchange-session-opening-rule-v1:{self.rule_version}:{self.rule_sha256}"

    def is_known_at(self, known_at: datetime) -> bool:
        """Return whether all supplied rule knowledge clocks precede a UTC cutoff."""

        _require_utc(known_at, "known_at")
        self.__post_init__()
        return max(self.first_seen_at, self.recorded_at, self.approved_at) <= known_at

    def to_dict(self) -> dict[str, str]:
        """Return the exact source-bound fields and their identity hash."""

        self.__post_init__()
        return {**self._payload(), "rule_sha256": self.rule_sha256, "identity": self.identity}

    def _payload(self) -> dict[str, str]:
        """Return the closed canonical hash payload for this rule."""

        return {
            "exchange": self.exchange,
            "phase": self.phase.value,
            "rule_version": self.rule_version,
            "source_uri": self.source_uri,
            "source_body_sha256": self.source_body_sha256,
            "effective_start": self.effective_start.isoformat(),
            "effective_end": self.effective_end.isoformat(),
            "timezone_name": self.timezone_name,
            "local_open_time": self.local_open_time.isoformat(),
            "first_seen_at": self.first_seen_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "approved_at": self.approved_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FinancialNextSessionAvailability:
    """A non-authorizing source-date to next-session opening calculation."""

    source_date: date
    next_session: date
    available_at: datetime
    known_at: datetime
    calendar_record: CalendarFormalPublicationRecord
    calendar_pointer: CalendarPublicationPointerExpectation
    opening_rule: ExchangeSessionOpeningRule

    def __post_init__(self) -> None:
        """Keep the returned instant bound to the exact calendar and rule."""

        _require_date(self.source_date, "source_date")
        _require_date(self.next_session, "next_session")
        if self.next_session <= self.source_date:
            raise ValueError("availability session must strictly follow source date")
        _require_utc(self.available_at, "available_at")
        _require_utc(self.known_at, "known_at")
        if type(self.calendar_record) is not CalendarFormalPublicationRecord:
            raise TypeError("availability requires an exact formal calendar record")
        if type(self.calendar_pointer) is not CalendarPublicationPointerExpectation:
            raise TypeError("availability requires an exact current calendar pointer")
        if type(self.opening_rule) is not ExchangeSessionOpeningRule:
            raise TypeError("availability requires an exact typed opening rule")
        validate_current_calendar_publication(
            self.calendar_record,
            self.calendar_pointer,
            as_of=self.known_at,
        )
        self.opening_rule.__post_init__()
        if self.calendar_record.seal.exchange != self.opening_rule.exchange:
            raise ValueError("availability calendar and opening rule exchanges differ")
        try:
            expected_session = next_exchange_calendar_session(
                self.calendar_record.seal.snapshot,
                after_date=self.source_date,
            )
        except (ExchangeCalendarError, TypeError, ValueError) as error:
            raise ValueError("calendar cannot prove a strictly later open session") from error
        if expected_session != self.next_session:
            raise ValueError("availability session differs from exact next calendar session")
        if (
            not self.opening_rule.effective_start
            <= self.next_session
            <= self.opening_rule.effective_end
        ):
            raise ValueError("availability session falls outside opening rule dates")
        if not self.opening_rule.is_known_at(self.known_at):
            raise ValueError("opening rule was not known at the resolution cutoff")
        expected_available_at = _opening_clock_utc(self.next_session, self.opening_rule)
        if self.available_at != expected_available_at:
            raise ValueError("available_at does not match the exact governed opening rule")

    @property
    def opening_rule_identity(self) -> str:
        """Return the exact opening rule identity bound to this calculation."""

        self.__post_init__()
        return self.opening_rule.identity

    @property
    def calendar_publication_hash(self) -> str:
        """Return the exact calendar content identity retained in this result."""

        self.__post_init__()
        return self.calendar_record.seal.publication_hash

    @property
    def reference_only(self) -> bool:
        """This in-memory result does not prove database registration or Audit."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Decision consumers must independently re-read authoritative sources."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """A source-time resolution has no execution capability."""

        return True

    def to_dict(self) -> dict[str, object]:
        """Return a closed, explicit reference-only projection for review."""

        self.__post_init__()
        return {
            "schema": "financial-next-session-availability.reference.v1",
            "source_date": self.source_date.isoformat(),
            "next_session": self.next_session.isoformat(),
            "available_at": self.available_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "calendar": _calendar_reference_payload(
                self.calendar_record,
                self.calendar_pointer,
                as_of=self.known_at,
            ),
            "opening_rule": self.opening_rule.to_dict(),
            "reference_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }


def exchange_session_opening_rule_sha256(payload: Mapping[str, object]) -> str:
    """Hash the exact closed opening-rule payload using a domain-separated digest."""

    if not isinstance(payload, Mapping) or frozenset(payload) != _RULE_PAYLOAD_KEYS:
        raise ValueError("opening rule payload keys are invalid")
    if any(type(value) is not str for value in payload.values()):
        raise ValueError("opening rule payload values must be canonical text")
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_RULE_HASH_DOMAIN + encoded).hexdigest()


def resolve_financial_next_session_availability(
    *,
    source_date: date,
    known_at: datetime,
    calendar_record: CalendarFormalPublicationRecord,
    calendar_pointer: CalendarPublicationPointerExpectation,
    opening_rule: ExchangeSessionOpeningRule,
) -> FinancialNextSessionAvailability:
    """Resolve a strict next-open instant from exact typed, fresh references.

    The formal calendar must be the exact current Publication at ``known_at``;
    its formal domain validation binds pointer, Publication, source snapshot,
    catalog knowledge, and response-age window. This Domain check does not
    verify the persisted Audit event or prove the source is owner-approved.
    The opening rule must be explicitly supplied, hashed, in force for the next
    session, and known by the same cutoff. Missing date coverage, a stale or
    mismatched reference, or an ambiguous local clock fails closed.

    The returned value is reference-only. Callers must re-read authoritative
    database records and revalidate their current/effective identities before
    using it for a financial write or decision.
    """

    if type(source_date) is not date:
        raise FinancialNextSessionAvailabilityError(
            "SOURCE_DATE_INVALID", "source_date must be a date without a time component"
        )
    try:
        _require_utc(known_at, "known_at")
    except ValueError as error:
        raise FinancialNextSessionAvailabilityError(
            "KNOWLEDGE_TIME_INVALID", "known_at must be an aware UTC instant"
        ) from error
    if (
        type(calendar_record) is not CalendarFormalPublicationRecord
        or type(calendar_pointer) is not CalendarPublicationPointerExpectation
    ):
        raise FinancialNextSessionAvailabilityError(
            "CALENDAR_REFERENCE_INVALID", "an exact formal calendar record and pointer are required"
        )
    if type(opening_rule) is not ExchangeSessionOpeningRule:
        raise FinancialNextSessionAvailabilityError(
            "RULE_REFERENCE_INVALID", "an exact typed opening rule is required"
        )
    try:
        opening_rule.__post_init__()
    except (TypeError, ValueError) as error:
        raise FinancialNextSessionAvailabilityError(
            "RULE_REFERENCE_INVALID", "opening rule identity is invalid"
        ) from error
    if calendar_record.seal.exchange != opening_rule.exchange:
        raise FinancialNextSessionAvailabilityError(
            "EXCHANGE_MISMATCH", "calendar and opening rule exchanges differ"
        )
    if not opening_rule.is_known_at(known_at):
        raise FinancialNextSessionAvailabilityError(
            "RULE_NOT_KNOWN", "opening rule knowledge clocks are after known_at"
        )
    try:
        validate_current_calendar_publication(calendar_record, calendar_pointer, as_of=known_at)
    except (CalendarFormalPublicationError, TypeError, ValueError) as error:
        raise FinancialNextSessionAvailabilityError(
            "CALENDAR_NOT_CURRENT_OR_FRESH",
            "formal calendar is missing, mismatched, unknown, or expired at known_at",
        ) from error
    try:
        next_session = next_exchange_calendar_session(
            calendar_record.seal.snapshot,
            after_date=source_date,
        )
    except (ExchangeCalendarError, TypeError, ValueError) as error:
        raise FinancialNextSessionAvailabilityError(
            "CALENDAR_COVERAGE_INCOMPLETE",
            "calendar has no explicitly covered next open session",
        ) from error
    if not opening_rule.effective_start <= next_session <= opening_rule.effective_end:
        raise FinancialNextSessionAvailabilityError(
            "RULE_NOT_EFFECTIVE", "opening rule is not effective on the next open session"
        )
    try:
        available_at = _opening_clock_utc(next_session, opening_rule)
    except FinancialNextSessionAvailabilityError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise FinancialNextSessionAvailabilityError(
            "OPENING_CLOCK_INVALID", "opening clock cannot be resolved to UTC"
        ) from error
    try:
        return FinancialNextSessionAvailability(
            source_date=source_date,
            next_session=next_session,
            available_at=available_at,
            known_at=known_at,
            calendar_record=calendar_record,
            calendar_pointer=calendar_pointer,
            opening_rule=opening_rule,
        )
    except (TypeError, ValueError) as error:
        raise FinancialNextSessionAvailabilityError(
            "AVAILABILITY_BINDING_INVALID", "resolved availability binding is inconsistent"
        ) from error


def _calendar_reference_payload(
    record: CalendarFormalPublicationRecord,
    pointer: CalendarPublicationPointerExpectation,
    *,
    as_of: datetime,
) -> dict[str, object]:
    """Project the exact Domain identity and clocks for a later repository read."""

    validate_current_calendar_publication(
        record,
        pointer,
        as_of=as_of,
    )
    seal = record.seal
    return {
        "dataset_key": seal.dataset.value,
        "publication_key": seal.publication_key,
        "exchange": seal.exchange,
        "publication_id": record.publication_id,
        "publication_hash": seal.publication_hash,
        "activation_id": record.activation_id,
        "pointer_id": pointer.pointer_id,
        "pointer_updated_at": pointer.updated_at.isoformat() if pointer.updated_at else None,
        "contract_recorded_at": seal.contract_recorded_at.isoformat(),
        "policy_version": seal.policy_version,
        "policy_identity": seal.policy_identity,
        "policy_recorded_at": seal.policy_recorded_at.isoformat(),
        "snapshot_reference": seal.snapshot_reference.to_payload(),
        "snapshot_first_seen_at": seal.snapshot_first_seen_at.isoformat(),
        "snapshot_recorded_at": seal.snapshot_recorded_at.isoformat(),
        "published_at": record.published_at.isoformat(),
        "valid_until": record.window.valid_until.isoformat(),
        "response_max_age_seconds": seal.calendar_response_max_age_seconds,
    }


def _opening_clock_utc(
    session_date: date,
    rule: ExchangeSessionOpeningRule,
) -> datetime:
    """Convert an explicit local clock and reject DST gaps or duplicate instants."""

    _require_date(session_date, "session_date")
    rule.__post_init__()
    local_naive = datetime.combine(session_date, rule.local_open_time)
    zone = ZoneInfo(rule.timezone_name)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        local_candidate = local_naive.replace(tzinfo=zone, fold=fold)
        utc_candidate = local_candidate.astimezone(UTC)
        round_trip = utc_candidate.astimezone(zone).replace(tzinfo=None)
        if round_trip == local_naive:
            candidates.add(utc_candidate)
    if not candidates:
        raise FinancialNextSessionAvailabilityError(
            "OPENING_CLOCK_NONEXISTENT", "local opening clock falls in a timezone gap"
        )
    if len(candidates) != 1:
        raise FinancialNextSessionAvailabilityError(
            "OPENING_CLOCK_AMBIGUOUS", "local opening clock maps to multiple UTC instants"
        )
    return next(iter(candidates))


def _validate_source_uri(value: str) -> None:
    """Require one absolute HTTPS source URI without credentials or fragments."""

    if type(value) is not str or not value or value != value.strip() or len(value) > 2048:
        raise ValueError("opening rule source URI is invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("opening rule source URI contains whitespace or controls")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("opening rule source URI must be absolute HTTPS without credentials")


def _require_date(value: date, field_name: str) -> None:
    """Require a date and reject datetime subclasses at date-only boundaries."""

    if type(value) is not date:
        raise ValueError(f"{field_name} must be a date")


def _require_utc(value: datetime, field_name: str) -> None:
    """Require an aware zero-offset instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be an aware UTC datetime")


def _require_sha256(value: str, field_name: str) -> None:
    """Require exactly one lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


__all__ = [
    "ExchangeSessionOpeningPhase",
    "ExchangeSessionOpeningRule",
    "FinancialNextSessionAvailability",
    "FinancialNextSessionAvailabilityError",
    "exchange_session_opening_rule_sha256",
    "resolve_financial_next_session_availability",
]
