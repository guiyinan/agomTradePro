"""Point-in-time institutional-calendar queries over exact immutable versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    InstitutionalCalendarError,
    InstitutionalEvent,
    KnowledgeMode,
)
from core.exceptions import DataFetchError


@dataclass(frozen=True, slots=True)
class InstitutionalCalendarEntry:
    """One visible current event state on its explicit local calendar date."""

    event_on: date
    event: InstitutionalEvent


class InstitutionalCalendarQueryRepositoryPort(Protocol):
    """Supply every exact version without applying caller-specific visibility."""

    def list_versions(self) -> tuple[InstitutionalEvent, ...]:
        """Return immutable versions for point-in-time selection by the use case."""


class QueryInstitutionalCalendarUseCase:
    """Select visible current revisions before applying calendar filters."""

    def __init__(
        self, repository: InstitutionalCalendarQueryRepositoryPort, *, timezone_name: str
    ) -> None:
        """Bind the read port and the explicit timezone used for scheduled dates."""

        self._repository = repository
        try:
            self._zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise DataFetchError(
                "Institutional-calendar query timezone is unknown",
                code="INSTITUTIONAL_CALENDAR_QUERY_TIMEZONE_INVALID",
            ) from exc

    def execute(
        self,
        date_from: date,
        date_to: date,
        *,
        known_at: datetime,
        mode: KnowledgeMode,
        event_type: str | None = None,
        lifecycle: EventLifecycle | None = None,
    ) -> tuple[InstitutionalCalendarEntry, ...]:
        """Return an inclusive local-date view containing no future or stale revisions."""

        _validate_range(date_from, date_to)
        _validate_cutoff(known_at, mode)
        _validate_filters(event_type, lifecycle)
        events = self._repository.list_versions()
        if not isinstance(events, tuple) or any(
            not isinstance(event, InstitutionalEvent) for event in events
        ):
            raise DataFetchError(
                "Institutional event repository returned an invalid result",
                code="INSTITUTIONAL_EVENT_RESULT_INVALID",
            )

        seen: set[tuple[str, int]] = set()
        visible: dict[str, InstitutionalEvent] = {}
        for event in events:
            identity = (event.event_id, event.revision)
            if identity in seen:
                raise DataFetchError(
                    "Institutional event repository returned a duplicate version",
                    code="INSTITUTIONAL_EVENT_VERSION_DUPLICATE",
                )
            seen.add(identity)
            try:
                is_visible = event.is_visible(known_at, mode)
            except InstitutionalCalendarError as exc:
                raise DataFetchError(str(exc), code=exc.code) from exc
            if not is_visible:
                continue
            current = visible.get(event.event_id)
            if current is None or event.revision > current.revision:
                visible[event.event_id] = event

        entries: list[InstitutionalCalendarEntry] = []
        for event in visible.values():
            event_on = self._event_on(event)
            if not date_from <= event_on <= date_to:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            if lifecycle is not None and event.lifecycle is not lifecycle:
                continue
            entries.append(InstitutionalCalendarEntry(event_on=event_on, event=event))
        return tuple(sorted(entries, key=lambda entry: (entry.event_on, entry.event.event_id)))

    def _event_on(self, event: InstitutionalEvent) -> date:
        """Prefer the effective date, otherwise localize the scheduled timestamp."""

        if event.effective_on is not None:
            return event.effective_on
        if event.scheduled_at is None:
            raise DataFetchError(
                "Institutional event has no effective or scheduled date",
                code="INSTITUTIONAL_EVENT_DATE_MISSING",
            )
        return event.scheduled_at.astimezone(self._zone).date()


def _validate_range(date_from: date, date_to: date) -> None:
    """Require exact dates in an inclusive, non-inverted range."""

    if type(date_from) is not date or type(date_to) is not date or date_from > date_to:
        raise DataFetchError(
            "Institutional-calendar query requires a valid inclusive date range",
            code="INSTITUTIONAL_CALENDAR_QUERY_RANGE_INVALID",
        )


def _validate_cutoff(known_at: datetime, mode: KnowledgeMode) -> None:
    """Validate the cutoff even when the repository has no visible events."""

    if not isinstance(known_at, datetime) or known_at.tzinfo is None:
        raise DataFetchError(
            "known_at must be timezone-aware UTC",
            code="INSTITUTIONAL_EVENT_TIME_INVALID",
        )
    offset = known_at.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataFetchError(
            "known_at must be timezone-aware UTC",
            code="INSTITUTIONAL_EVENT_TIME_INVALID",
        )
    if not isinstance(mode, KnowledgeMode):
        raise DataFetchError(
            "Institutional-calendar knowledge mode must be typed",
            code="INSTITUTIONAL_EVENT_KNOWLEDGE_MODE_INVALID",
        )


def _validate_filters(event_type: str | None, lifecycle: EventLifecycle | None) -> None:
    """Reject ambiguous filter values instead of silently returning an empty view."""

    if event_type is not None and (
        not isinstance(event_type, str)
        or not event_type
        or event_type != event_type.strip()
        or len(event_type) > 240
        or any(character.isspace() for character in event_type)
    ):
        raise DataFetchError(
            "Institutional-calendar event type must be canonical identity text",
            code="INSTITUTIONAL_CALENDAR_QUERY_FILTER_INVALID",
        )
    if lifecycle is not None and not isinstance(lifecycle, EventLifecycle):
        raise DataFetchError(
            "Institutional-calendar lifecycle must be typed",
            code="INSTITUTIONAL_CALENDAR_QUERY_FILTER_INVALID",
        )


__all__ = [
    "InstitutionalCalendarEntry",
    "InstitutionalCalendarQueryRepositoryPort",
    "QueryInstitutionalCalendarUseCase",
]
