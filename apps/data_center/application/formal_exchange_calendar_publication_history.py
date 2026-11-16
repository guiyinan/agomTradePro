"""Application contract for exact immutable calendar history reads.

The history result describes only the sealed publication identity, its
published/superseded half-open interval, response-age TTL, and exact Audit
event/outbox receipt. It deliberately contains no current pointer or
activation identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarPublicationAuditPair,
)
from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
    CalendarPublicationWindow,
    CalendarPublicationWindowError,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationSeal,
    exchange_calendar_publication_key,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ReadExchangeCalendarPublicationAsOfQuery:
    """Request one immutable calendar publication by exact identity and cutoff."""

    publication_id: str
    publication_hash: str
    dataset_key: str
    exchange: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate all query identity fields before repository access."""

        if type(self.publication_id) is not str:
            raise CalendarFormalPublicationApplicationError(
                "publication_id must be canonical UUID text",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        try:
            parsed_publication_id = UUID(self.publication_id)
        except (TypeError, ValueError) as error:
            raise CalendarFormalPublicationApplicationError(
                "publication_id must be canonical UUID text",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            ) from error
        if str(parsed_publication_id) != self.publication_id:
            raise CalendarFormalPublicationApplicationError(
                "publication_id must be canonical UUID text",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        if (
            type(self.publication_hash) is not str
            or _SHA256_RE.fullmatch(self.publication_hash) is None
        ):
            raise CalendarFormalPublicationApplicationError(
                "publication_hash must be lowercase SHA-256 text",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        if (
            type(self.dataset_key) is not str
            or not self.dataset_key
            or self.dataset_key.strip() != self.dataset_key
            or len(self.dataset_key) > 160
            or any(character.isspace() for character in self.dataset_key)
        ):
            raise CalendarFormalPublicationApplicationError(
                "dataset_key must be explicit",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        try:
            exchange_calendar_publication_key(self.exchange)
        except CalendarFormalPublicationError as error:
            raise CalendarFormalPublicationApplicationError(str(error), code=error.code) from error
        _require_utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class HistoricalCalendarPublicationRecord:
    """Immutable publication seal and its observed forward-only lifecycle interval."""

    seal: CalendarFormalPublicationSeal
    publication_id: str
    lifecycle: CalendarPublicationLifecycle
    published_at: datetime
    superseded_at: datetime | None

    def __post_init__(self) -> None:
        """Reject unsupported lifecycle states and invalid source-age windows."""

        if type(self.seal) is not CalendarFormalPublicationSeal:
            raise CalendarFormalPublicationApplicationError(
                "historical record requires an exact publication seal",
                code="CALENDAR_HISTORY_RECORD_INVALID",
            )
        if type(self.publication_id) is not str:
            raise CalendarFormalPublicationApplicationError(
                "historical record publication_id must be canonical UUID text",
                code="CALENDAR_HISTORY_RECORD_INVALID",
            )
        try:
            self.seal.validate()
            publication_uuid = UUID(self.publication_id)
        except (CalendarFormalPublicationError, TypeError, ValueError) as error:
            raise CalendarFormalPublicationApplicationError(
                "historical record identity or seal is invalid",
                code="CALENDAR_HISTORY_RECORD_INVALID",
            ) from error
        if str(publication_uuid) != self.publication_id:
            raise CalendarFormalPublicationApplicationError(
                "historical record publication_id is not canonical",
                code="CALENDAR_HISTORY_RECORD_INVALID",
            )
        if type(self.lifecycle) is not CalendarPublicationLifecycle or self.lifecycle not in {
            CalendarPublicationLifecycle.PUBLISHED,
            CalendarPublicationLifecycle.SUPERSEDED,
        }:
            raise CalendarFormalPublicationApplicationError(
                "historical record lifecycle is unsupported",
                code="CALENDAR_HISTORY_LIFECYCLE_UNSUPPORTED",
            )
        _require_utc(self.published_at, "published_at")
        if self.superseded_at is not None:
            _require_utc(self.superseded_at, "superseded_at")
        if self.published_at < max(
            self.seal.contract_recorded_at,
            self.seal.policy_recorded_at,
            self.seal.snapshot_recorded_at,
        ):
            raise CalendarFormalPublicationApplicationError(
                "historical publication predates its source or catalog knowledge",
                code="CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
            )
        try:
            self.window.__post_init__()
        except CalendarPublicationWindowError as error:
            raise CalendarFormalPublicationApplicationError(str(error), code=error.code) from error

    @property
    def window(self) -> CalendarPublicationWindow:
        """Return the exact half-open published/superseded and response-age window."""

        return CalendarPublicationWindow(
            snapshot=self.seal.snapshot,
            calendar_response_max_age_seconds=self.seal.calendar_response_max_age_seconds,
            published_at=self.published_at,
            lifecycle=self.lifecycle,
            superseded_at=self.superseded_at,
        )

    def is_effective_at(self, as_of: datetime) -> bool:
        """Return whether immutable source/config knowledge was effective at cutoff."""

        _require_utc(as_of, "as_of")
        if as_of < max(
            self.seal.contract_recorded_at,
            self.seal.policy_recorded_at,
            self.seal.snapshot_recorded_at,
        ):
            raise CalendarFormalPublicationApplicationError(
                "calendar source or configuration postdates historical cutoff",
                code="CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
            )
        try:
            return self.window.is_effective_at(as_of)
        except CalendarPublicationWindowError as error:
            raise CalendarFormalPublicationApplicationError(str(error), code=error.code) from error


@dataclass(frozen=True, slots=True)
class HistoricalPublishedExchangeCalendar:
    """Exact historical calendar and Audit receipt, without pointer/activation claims."""

    record: HistoricalCalendarPublicationRecord
    audit_pair: CalendarPublicationAuditPair
    as_of: datetime

    def __post_init__(self) -> None:
        """Bind the exact Audit pair to an effective historical publication."""

        if type(self.record) is not HistoricalCalendarPublicationRecord:
            raise CalendarFormalPublicationApplicationError(
                "historical read requires a typed publication record",
                code="CALENDAR_HISTORY_RESULT_INVALID",
            )
        self.record.__post_init__()
        if type(self.audit_pair) is not CalendarPublicationAuditPair:
            raise CalendarFormalPublicationApplicationError(
                "historical read requires an exact Audit event/outbox receipt",
                code="CALENDAR_HISTORY_AUDIT_INVALID",
            )
        self.audit_pair.__post_init__()
        _require_utc(self.as_of, "as_of")
        if not self.record.is_effective_at(self.as_of):
            raise CalendarFormalPublicationApplicationError(
                "calendar publication is outside its historical half-open window",
                code="CALENDAR_HISTORY_NOT_EFFECTIVE",
            )
        seal = self.record.seal
        if (
            self.audit_pair.dataset_key != seal.dataset.value
            or self.audit_pair.exchange != seal.exchange
            or self.audit_pair.publication_id != self.record.publication_id
            or self.audit_pair.publication_hash != seal.publication_hash
            or self.audit_pair.recorded_at != self.record.published_at
            or self.audit_pair.recorded_at > self.as_of
        ):
            raise CalendarFormalPublicationApplicationError(
                "historical Audit receipt differs from the immutable publication",
                code="CALENDAR_HISTORY_AUDIT_INVALID",
            )

    @property
    def must_not_execute(self) -> bool:
        """Return the fixed reference-only capability boundary of history reads."""

        return True

    @property
    def reference_only(self) -> bool:
        """Return that this result proves neither activation nor financial eligibility."""

        return True


class CalendarHistoricalPublicationReaderPort(Protocol):
    """Exact publication-id reader for one historical knowledge cutoff."""

    def read_publication_as_of(
        self,
        query: ReadExchangeCalendarPublicationAsOfQuery,
    ) -> HistoricalPublishedExchangeCalendar:
        """Rebuild one exact sealed record and verify its lifecycle/Audit pair."""


class ReadExchangeCalendarPublicationAsOfUseCase:
    """Read and verify one exact immutable publication at a past UTC instant."""

    def __init__(
        self,
        reader: CalendarHistoricalPublicationReaderPort,
        *,
        clock: CalendarHistoryClock,
    ) -> None:
        """Bind the use case to an exact historical reader and server clock."""

        self._reader = reader
        self._clock = clock

    def execute(
        self,
        query: ReadExchangeCalendarPublicationAsOfQuery,
    ) -> HistoricalPublishedExchangeCalendar:
        """Reject future cutoffs and bind every returned field to the request."""

        if type(query) is not ReadExchangeCalendarPublicationAsOfQuery:
            raise CalendarFormalPublicationApplicationError(
                "historical read requires a typed exact-publication query",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        query.__post_init__()
        now = self._clock.now()
        _require_utc(now, "server_now")
        if query.as_of > now:
            raise CalendarFormalPublicationApplicationError(
                "historical cutoff cannot be in the future",
                code="CALENDAR_HISTORY_FUTURE_CUTOFF",
            )
        result = self._reader.read_publication_as_of(query)
        if type(result) is not HistoricalPublishedExchangeCalendar:
            raise CalendarFormalPublicationApplicationError(
                "historical reader returned an invalid typed result",
                code="CALENDAR_HISTORY_RESULT_INVALID",
            )
        result.__post_init__()
        seal = result.record.seal
        if (
            result.record.publication_id != query.publication_id
            or seal.publication_hash != query.publication_hash
            or seal.dataset.value != query.dataset_key
            or seal.exchange != query.exchange
            or result.as_of != query.as_of
        ):
            raise CalendarFormalPublicationApplicationError(
                "historical reader returned a different publication identity or cutoff",
                code="CALENDAR_HISTORY_SCOPE_MISMATCH",
            )
        return result


class CalendarHistoryClock(Protocol):
    """Server UTC clock used only to reject caller-supplied future cutoffs."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


def _require_utc(value: object, field_name: str) -> None:
    """Require an exact aware zero-offset datetime without normalization."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be an aware UTC instant",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )


__all__ = [
    "CalendarHistoricalPublicationReaderPort",
    "HistoricalCalendarPublicationRecord",
    "HistoricalPublishedExchangeCalendar",
    "ReadExchangeCalendarPublicationAsOfQuery",
    "ReadExchangeCalendarPublicationAsOfUseCase",
]
