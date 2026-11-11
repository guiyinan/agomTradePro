"""Typed NBS inputs and exact-version institutional-event reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    InstitutionalCalendarError,
    InstitutionalEvent,
    KnowledgeMode,
)
from core.exceptions import DataFetchError


@dataclass(frozen=True, slots=True)
class NbsScheduleInput:
    """Normalized NBS schedule input with retained original and real system clocks."""

    event_id: str
    source_id: str
    source_event_id: str
    event_type: str
    title: str
    scheduled_at: datetime
    source_published_at: datetime
    first_seen_at: datetime
    recorded_at: datetime
    original_sha256: str

    def to_event(self) -> InstitutionalEvent:
        """Create a tentative scheduled fact without claiming actual occurrence."""

        try:
            return InstitutionalEvent(
                event_id=self.event_id,
                source_id=self.source_id,
                source_event_id=self.source_event_id,
                event_type=self.event_type,
                title=self.title,
                evidence=EvidenceGrade.TENTATIVE,
                lifecycle=EventLifecycle.SCHEDULED,
                revision=1,
                scheduled_at=self.scheduled_at,
                effective_on=None,
                source_published_at=self.source_published_at,
                source_published_on=None,
                available_at=self.source_published_at,
                first_seen_at=self.first_seen_at,
                recorded_at=self.recorded_at,
                original_sha256=self.original_sha256,
                supersedes_event_id=None,
            )
        except InstitutionalCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc


@dataclass(frozen=True, slots=True)
class NbsActualReleaseInput:
    """Normalized actual NBS publication that confirms one exact prior schedule."""

    source_id: str
    source_event_id: str
    event_type: str
    title: str
    scheduled_at: datetime
    source_published_at: datetime
    first_seen_at: datetime
    recorded_at: datetime
    original_sha256: str

    def to_event(self, schedule: InstitutionalEvent) -> InstitutionalEvent:
        """Append an occurred successor while preserving the schedule version."""

        if not isinstance(schedule, InstitutionalEvent):
            raise DataFetchError("NBS schedule must be typed", code="NBS_ACTUAL_SCHEDULE_MISMATCH")
        if (
            schedule.source_id != self.source_id
            or schedule.source_event_id != self.source_event_id
            or schedule.event_type != self.event_type
            or schedule.title != self.title
            or schedule.scheduled_at != self.scheduled_at
            or schedule.lifecycle is not EventLifecycle.SCHEDULED
        ):
            raise DataFetchError(
                "Actual NBS release does not match its scheduled event",
                code="NBS_ACTUAL_SCHEDULE_MISMATCH",
            )
        try:
            return InstitutionalEvent(
                event_id=schedule.event_id,
                source_id=self.source_id,
                source_event_id=self.source_event_id,
                event_type=self.event_type,
                title=self.title,
                evidence=EvidenceGrade.CONFIRMED,
                lifecycle=EventLifecycle.OCCURRED,
                revision=schedule.revision + 1,
                scheduled_at=self.scheduled_at,
                effective_on=schedule.scheduled_at.date(),
                source_published_at=self.source_published_at,
                source_published_on=None,
                available_at=self.source_published_at,
                first_seen_at=self.first_seen_at,
                recorded_at=self.recorded_at,
                original_sha256=self.original_sha256,
                supersedes_event_id=schedule.event_id,
            )
        except InstitutionalCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc


class InstitutionalEventRepositoryPort(Protocol):
    """Read exact immutable event versions without selecting a latest row."""

    def get_version(self, event_id: str, revision: int) -> InstitutionalEvent | None:
        """Return one exact event version or no result."""


class ReadInstitutionalEventUseCase:
    """Read an exact event version only when visible under the requested clock mode."""

    def __init__(self, repository: InstitutionalEventRepositoryPort) -> None:
        self._repository = repository

    def execute(
        self,
        event_id: str,
        revision: int,
        *,
        known_at: datetime,
        mode: KnowledgeMode,
    ) -> InstitutionalEvent:
        """Reject absent, future, mismatched, or not-yet-known event versions."""

        event = self._repository.get_version(event_id, revision)
        if event is None:
            raise DataFetchError(
                "Institutional event version is unavailable",
                code="INSTITUTIONAL_EVENT_VERSION_NOT_FOUND",
            )
        if not isinstance(event, InstitutionalEvent):
            raise DataFetchError(
                "Institutional event repository returned an invalid result",
                code="INSTITUTIONAL_EVENT_RESULT_INVALID",
            )
        if event.event_id != event_id or event.revision != revision:
            raise DataFetchError(
                "Institutional event repository returned a different version",
                code="INSTITUTIONAL_EVENT_VERSION_MISMATCH",
            )
        try:
            visible = event.is_visible(known_at, mode)
        except InstitutionalCalendarError as exc:
            raise DataFetchError(str(exc), code=exc.code) from exc
        if not visible:
            raise DataFetchError(
                "Institutional event was not known at the requested cutoff",
                code="INSTITUTIONAL_EVENT_NOT_KNOWN",
            )
        return event


__all__ = [
    "InstitutionalEventRepositoryPort",
    "NbsActualReleaseInput",
    "NbsScheduleInput",
    "ReadInstitutionalEventUseCase",
]
