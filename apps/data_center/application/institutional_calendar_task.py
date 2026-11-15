"""Ordinary-user read task over exact events, retained sources and six periods."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol

from apps.data_center.application.institutional_calendar_query import (
    QueryInstitutionalCalendarUseCase,
)
from apps.data_center.application.institutional_calendar_sources import (
    InstitutionalOriginalRepositoryPort,
    InstitutionalSourcePolicy,
    RetainedInstitutionalOriginal,
)
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    InstitutionalEvent,
    KnowledgeMode,
    SixNaturalDayWindow,
    iter_six_period_windows,
)
from core.exceptions import DataValidationError


class InstitutionalCalendarPolicyReaderPort(Protocol):
    """Supply an explicitly configured qualified source; missing is a visible gap."""

    def read_policy(self) -> InstitutionalSourcePolicy | None:
        """Read the unique configured source without manufacturing defaults."""


@dataclass(frozen=True, slots=True)
class InstitutionalCalendarTaskEvent:
    """Preserve the recorded event separately from its independently checked source."""

    event_on: date
    event: InstitutionalEvent
    original: RetainedInstitutionalOriginal | None
    source_gap: str | None


@dataclass(frozen=True, slots=True)
class InstitutionalCalendarTaskResult:
    """A read-only reference view that never claims a completed event study."""

    known_at: datetime
    checked_at: datetime
    mode: KnowledgeMode
    policy: InstitutionalSourcePolicy | None
    windows: tuple[SixNaturalDayWindow, ...]
    events: tuple[InstitutionalCalendarTaskEvent, ...]
    gaps: tuple[str, ...]


class ReadInstitutionalCalendarTask:
    """Expose source gaps, time modes and future scheduled dates to ordinary users."""

    def __init__(
        self,
        query: QueryInstitutionalCalendarUseCase,
        originals: InstitutionalOriginalRepositoryPort,
        policies: InstitutionalCalendarPolicyReaderPort,
        *,
        policy: InstitutionalSourcePolicy | None,
        clock: Callable[[], datetime],
    ) -> None:
        """Inject exact reads, original verification and explicit source configuration."""
        self._query = query
        self._originals = originals
        self._policies = policies
        self._policy = policy
        self._clock = clock

    def execute(
        self,
        date_from: date,
        date_to: date,
        *,
        known_at: datetime,
        checked_at: datetime,
        mode: KnowledgeMode,
        event_type: str | None = None,
        lifecycle: EventLifecycle | None = None,
    ) -> InstitutionalCalendarTaskResult:
        """Validate the bounded requested view and verify each visible original."""
        if (
            type(date_from) is not date
            or type(date_to) is not date
            or date_from > date_to
            or (date_to - date_from).days > 366
        ):
            raise DataValidationError(
                "Calendar range must be at most 367 inclusive days.",
                code="INSTITUTIONAL_CALENDAR_QUERY_RANGE_INVALID",
            )
        checked_offset = checked_at.utcoffset() if isinstance(checked_at, datetime) else None
        known_offset = known_at.utcoffset() if isinstance(known_at, datetime) else None
        if (
            checked_offset is None
            or checked_offset.total_seconds() != 0
            or known_offset is None
            or known_offset.total_seconds() != 0
            or known_at > checked_at
        ):
            raise DataValidationError(
                "Knowledge cutoff must be UTC and cannot be in the future.",
                code="INSTITUTIONAL_EVENT_TIME_INVALID",
            )
        policy = self._policy
        entries = self._query.execute(
            date_from,
            date_to,
            known_at=known_at,
            mode=mode,
            event_type=event_type,
            lifecycle=lifecycle,
        )
        gaps: set[str] = {"EVENT_STUDY_NOT_COMPLETED", "UNQUALIFIED_EVENT_CLASSES_NOT_COVERED"}
        if policy is None:
            gaps.add("SOURCE_POLICY_UNAVAILABLE")
        events: list[InstitutionalCalendarTaskEvent] = []
        for entry in entries:
            original: RetainedInstitutionalOriginal | None = None
            gap: str | None = None
            try:
                original = self._originals.read(entry.event.original_sha256)
                if original is None:
                    gap = "ORIGINAL_UNAVAILABLE"
                else:
                    original.validate_event(entry.event)
                    if not self._originals.verify_event(entry.event, original):
                        raise DataValidationError(
                            "Original does not prove the recorded event.",
                            code="INSTITUTIONAL_ORIGINAL_INVALID",
                        )
                    if policy is None or original.policy != policy:
                        gap = "SOURCE_POLICY_UNAVAILABLE"
            except DataValidationError:
                gap = "ORIGINAL_INVALID"
                original = None
            if gap is not None:
                gaps.add(gap)
            events.append(
                InstitutionalCalendarTaskEvent(entry.event_on, entry.event, original, gap)
            )
        windows = (
            ()
            if policy is None
            else iter_six_period_windows(date_from, date_to, rule_version=policy.rule_version)
        )
        # Finish all original and configuration reads before sampling the real clock.
        current_policy = self._policies.read_policy()
        finished_at = self._clock()
        finished_offset = finished_at.utcoffset() if isinstance(finished_at, datetime) else None
        if (
            finished_offset is None
            or finished_offset.total_seconds() != 0
            or finished_at < checked_at
        ):
            raise DataValidationError(
                "Calendar completion clock is invalid.", code="INSTITUTIONAL_EVENT_TIME_INVALID"
            )
        final_gap: str | None = None
        if current_policy != policy:
            final_gap = "SOURCE_POLICY_CHANGED"
        elif policy is not None and finished_at >= policy.valid_until:
            final_gap = "SOURCE_POLICY_EXPIRED"
        if final_gap is not None:
            gaps.add(final_gap)
            events = [
                replace(item, source_gap=final_gap) if item.source_gap is None else item
                for item in events
            ]
        return InstitutionalCalendarTaskResult(
            known_at, finished_at, mode, policy, windows, tuple(events), tuple(sorted(gaps))
        )


__all__ = [
    "InstitutionalCalendarPolicyReaderPort",
    "InstitutionalCalendarTaskEvent",
    "InstitutionalCalendarTaskResult",
    "ReadInstitutionalCalendarTask",
]
