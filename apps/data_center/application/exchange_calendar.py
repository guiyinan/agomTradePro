"""Application ports and use cases for exact source-backed calendar snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    ExchangeCalendarSnapshotReference,
    next_exchange_calendar_session,
)
from core.exceptions import DataFetchError


class ExchangeCalendarSnapshotSourcePort(Protocol):
    """Fetch one complete exchange snapshot and its exact source binding."""

    def fetch_candidate(
        self,
        exchange: str,
        coverage_start: date,
        coverage_end: date,
    ) -> ExchangeCalendarSnapshotCandidate:
        """Return a verified candidate without claiming publication authority."""


class ExchangeCalendarSnapshotRepositoryPort(Protocol):
    """Persist immutable snapshots and perform knowledge-time exact reads."""

    def save(self, candidate: ExchangeCalendarSnapshotCandidate) -> ExchangeCalendarSnapshot:
        """Persist first-recorded knowledge or return an exact existing replay."""

    def get_exact(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> ExchangeCalendarSnapshot | None:
        """Read only the exact reference if both local evidence times are known."""


@dataclass(frozen=True, slots=True)
class ExchangeCalendarNextSession:
    """Typed next-session answer bound to one exact unpublished snapshot."""

    exchange: str
    after_date: date
    session_date: date
    known_at: datetime
    snapshot_reference: ExchangeCalendarSnapshotReference

    def __post_init__(self) -> None:
        """Require a strictly later date and aware knowledge cutoff."""

        if (
            not isinstance(self.exchange, str)
            or not self.exchange
            or self.exchange.strip() != self.exchange
            or any(character.isspace() for character in self.exchange)
        ):
            raise DataFetchError(
                "Exchange calendar result has a non-canonical exchange",
                code="EXCHANGE_CALENDAR_EXCHANGE_INVALID",
            )
        if (
            type(self.after_date) is not date
            or type(self.session_date) is not date
            or self.session_date <= self.after_date
        ):
            raise DataFetchError(
                "Exchange calendar result must use a later date",
                code="EXCHANGE_CALENDAR_NEXT_SESSION_INVALID",
            )
        if not _is_utc(self.known_at):
            raise DataFetchError(
                "Exchange calendar result knowledge time must be UTC",
                code="EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
            )
        if not isinstance(self.snapshot_reference, ExchangeCalendarSnapshotReference):
            raise DataFetchError(
                "Exchange calendar result requires an exact snapshot reference",
                code="EXCHANGE_CALENDAR_REFERENCE_INVALID",
            )
        if self.snapshot_reference.exchange != self.exchange:
            raise DataFetchError(
                "Exchange calendar result does not match its snapshot exchange",
                code="EXCHANGE_CALENDAR_EXCHANGE_MISMATCH",
            )


class IngestExchangeCalendarSnapshotUseCase:
    """Capture and store one explicitly scoped complete exchange calendar."""

    def __init__(
        self,
        source: ExchangeCalendarSnapshotSourcePort,
        repository: ExchangeCalendarSnapshotRepositoryPort,
    ) -> None:
        self._source = source
        self._repository = repository

    def execute(
        self,
        exchange: str,
        coverage_start: date,
        coverage_end: date,
    ) -> ExchangeCalendarSnapshot:
        """Persist one exact source response without activating it as current."""

        try:
            candidate = self._source.fetch_candidate(exchange, coverage_start, coverage_end)
            if not isinstance(candidate, ExchangeCalendarSnapshotCandidate):
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_SOURCE_RESULT_INVALID",
                    "source must return a typed calendar candidate",
                )
            if (
                candidate.exchange != exchange
                or candidate.coverage_start != coverage_start
                or candidate.coverage_end != coverage_end
            ):
                raise ExchangeCalendarError(
                    "EXCHANGE_CALENDAR_SOURCE_SCOPE_MISMATCH",
                    "source returned a different exchange or coverage window",
                )
            return self._repository.save(candidate)
        except ExchangeCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc


class ReadExchangeCalendarSnapshotUseCase:
    """Read an exact calendar snapshot only at or after its knowledge time."""

    def __init__(self, repository: ExchangeCalendarSnapshotRepositoryPort) -> None:
        self._repository = repository

    def execute(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> ExchangeCalendarSnapshot:
        """Resolve exact immutable evidence; never select a latest/current row."""

        if not isinstance(reference, ExchangeCalendarSnapshotReference):
            raise DataFetchError(
                "Calendar snapshot reference must be typed",
                code="EXCHANGE_CALENDAR_REFERENCE_INVALID",
            )
        if not _is_utc(known_at):
            raise DataFetchError(
                "Calendar knowledge cutoff must be timezone-aware",
                code="EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID",
            )
        snapshot = self._repository.get_exact(reference, known_at=known_at)
        if snapshot is None:
            raise DataFetchError(
                "Exact calendar snapshot is unavailable at the requested knowledge time",
                code="EXCHANGE_CALENDAR_SNAPSHOT_NOT_KNOWN",
            )
        if snapshot.reference() != reference:
            raise DataFetchError(
                "Calendar repository returned a different snapshot reference",
                code="EXCHANGE_CALENDAR_SNAPSHOT_REFERENCE_MISMATCH",
            )
        if snapshot.first_seen_at > known_at or snapshot.recorded_at > known_at:
            raise DataFetchError(
                "Calendar snapshot was not known by the requested cutoff",
                code="EXCHANGE_CALENDAR_SNAPSHOT_NOT_KNOWN",
            )
        return snapshot


class ReadNextExchangeCalendarSessionUseCase:
    """Return a next open date only within one exact, known calendar snapshot."""

    def __init__(self, snapshot_reader: ReadExchangeCalendarSnapshotUseCase) -> None:
        self._snapshot_reader = snapshot_reader

    def execute(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        after_date: date,
        known_at: datetime,
    ) -> ExchangeCalendarNextSession:
        """Return explicit next-session evidence or a stable blocked error."""

        snapshot = self._snapshot_reader.execute(reference, known_at=known_at)
        try:
            session_date = next_exchange_calendar_session(snapshot, after_date=after_date)
        except ExchangeCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc
        return ExchangeCalendarNextSession(
            exchange=snapshot.exchange,
            after_date=after_date,
            session_date=session_date,
            known_at=known_at,
            snapshot_reference=reference,
        )


__all__ = [
    "ExchangeCalendarNextSession",
    "ExchangeCalendarSnapshotRepositoryPort",
    "ExchangeCalendarSnapshotSourcePort",
    "IngestExchangeCalendarSnapshotUseCase",
    "ReadExchangeCalendarSnapshotUseCase",
    "ReadNextExchangeCalendarSessionUseCase",
]


def _is_utc(value: object) -> bool:
    """Accept only timezone-aware UTC instants at the Application boundary."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0
