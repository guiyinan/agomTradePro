"""Institutional calendar rules preserve evidence, lifecycle, and knowledge time."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from apps.data_center.application.institutional_calendar import (
    NbsActualReleaseInput,
    NbsScheduleInput,
    ReadInstitutionalEventUseCase,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarDay
from apps.data_center.domain.institutional_calendar import (
    DateOnlyAvailabilityRule,
    EventLifecycle,
    EvidenceGrade,
    InstitutionalCalendarError,
    InstitutionalEvent,
    KnowledgeMode,
    SixPeriod,
    conservative_date_only_available_at,
    iter_six_period_windows,
    six_period_for,
    trading_days_for_window,
)
from core.exceptions import DataFetchError

RULE_VERSION = "six-natural-day-periods-v1"


def _calendar(start: date, end: date, *, exchange: str = "SSE") -> tuple[ExchangeCalendarDay, ...]:
    """Build explicit daily states with weekends closed."""

    days: list[ExchangeCalendarDay] = []
    current = start
    previous_open = start - timedelta(days=1)
    while current <= end:
        days.append(
            ExchangeCalendarDay(
                exchange=exchange,
                calendar_date=current,
                is_open=current.weekday() < 5,
                previous_open_date=previous_open,
            )
        )
        if current.weekday() < 5:
            previous_open = current
        current += timedelta(days=1)
    return tuple(days)


def _event(**overrides: object) -> InstitutionalEvent:
    """Return a valid official schedule with independently mutable evidence fields."""

    values: dict[str, object] = {
        "event_id": "nbs-cpi-2026-10",
        "source_id": "nbs_official",
        "source_event_id": "1965795",
        "event_type": "macro_release",
        "title": "2026年10月份居民消费价格",
        "evidence": EvidenceGrade.TENTATIVE,
        "lifecycle": EventLifecycle.SCHEDULED,
        "revision": 1,
        "scheduled_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "effective_on": None,
        "source_published_at": datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
        "source_published_on": None,
        "available_at": datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
        "first_seen_at": datetime(2026, 1, 2, tzinfo=UTC),
        "recorded_at": datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
        "original_sha256": "a" * 64,
        "supersedes_event_id": None,
    }
    values.update(overrides)
    return InstitutionalEvent(**values)  # type: ignore[arg-type]


def _schedule_input() -> NbsScheduleInput:
    """Return the retained NBS schedule shape as already normalized input."""

    return NbsScheduleInput(
        event_id="nbs-cpi-2026-10",
        source_id="nbs_official",
        source_event_id="2026-schedule-cpi-october",
        event_type="macro_release",
        title="2026年10月份居民消费价格",
        scheduled_at=datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        source_published_at=datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
        original_sha256="b" * 64,
    )


@pytest.mark.parametrize(
    ("day", "category", "start", "end"),
    [
        (date(2026, 1, 1), SixPeriod.DAYS_01_05, date(2026, 1, 1), date(2026, 1, 5)),
        (date(2026, 1, 5), SixPeriod.DAYS_01_05, date(2026, 1, 1), date(2026, 1, 5)),
        (date(2026, 1, 6), SixPeriod.DAYS_06_10, date(2026, 1, 6), date(2026, 1, 10)),
        (date(2026, 1, 15), SixPeriod.DAYS_11_15, date(2026, 1, 11), date(2026, 1, 15)),
        (date(2026, 1, 20), SixPeriod.DAYS_16_20, date(2026, 1, 16), date(2026, 1, 20)),
        (date(2026, 1, 25), SixPeriod.DAYS_21_25, date(2026, 1, 21), date(2026, 1, 25)),
        (date(2026, 1, 31), SixPeriod.DAYS_26_END, date(2026, 1, 26), date(2026, 1, 31)),
        (date(2024, 2, 29), SixPeriod.DAYS_26_END, date(2024, 2, 26), date(2024, 2, 29)),
        (date(2026, 2, 28), SixPeriod.DAYS_26_END, date(2026, 2, 26), date(2026, 2, 28)),
    ],
)
def test_six_periods_cover_boundaries_and_leap_year(
    day: date, category: SixPeriod, start: date, end: date
) -> None:
    window = six_period_for(day, rule_version=RULE_VERSION)

    assert window.category is category
    assert window.start_date == start
    assert window.end_date == end
    assert window.rule_version == RULE_VERSION


def test_window_iteration_preserves_full_windows_across_months() -> None:
    windows = iter_six_period_windows(
        date(2026, 1, 31), date(2026, 2, 1), rule_version=RULE_VERSION
    )

    assert [(item.start_date, item.end_date) for item in windows] == [
        (date(2026, 1, 26), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 5)),
    ]


def test_trading_alignment_requires_complete_explicit_calendar_coverage() -> None:
    window = six_period_for(date(2026, 1, 31), rule_version=RULE_VERSION)
    calendar = _calendar(window.start_date, window.end_date)

    assert trading_days_for_window(window, calendar) == (
        date(2026, 1, 26),
        date(2026, 1, 27),
        date(2026, 1, 28),
        date(2026, 1, 29),
        date(2026, 1, 30),
    )
    with pytest.raises(InstitutionalCalendarError) as caught:
        trading_days_for_window(window, calendar[:-1])
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE"

    mixed_exchange_calendar = (replace(calendar[0], exchange="SZSE"), *calendar[1:])
    with pytest.raises(InstitutionalCalendarError) as caught:
        trading_days_for_window(window, mixed_exchange_calendar)
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_EXCHANGE_MISMATCH"


def test_date_only_source_waits_for_next_open_day_cutoff() -> None:
    rule = DateOnlyAvailabilityRule(
        rule_version="date-only-next-session-18-v1",
        timezone_name="Asia/Shanghai",
        local_cutoff=time(18, 0),
    )
    calendar = _calendar(date(2026, 11, 6), date(2026, 11, 10))

    available_at = conservative_date_only_available_at(date(2026, 11, 6), rule, calendar)

    assert available_at == datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    assert available_at != datetime(2026, 11, 6, 0, 0, tzinfo=UTC)


def test_event_separates_evidence_grade_from_lifecycle() -> None:
    occurred = _event(
        evidence=EvidenceGrade.CONFIRMED,
        lifecycle=EventLifecycle.OCCURRED,
        revision=2,
        supersedes_event_id="nbs-cpi-2026-10",
    )
    cancelled = _event(
        evidence=EvidenceGrade.CONFIRMED,
        lifecycle=EventLifecycle.CANCELLED,
        revision=2,
        supersedes_event_id="nbs-cpi-2026-10",
    )
    superseded = _event(lifecycle=EventLifecycle.SUPERSEDED)

    assert occurred.evidence is EvidenceGrade.CONFIRMED
    assert occurred.lifecycle is EventLifecycle.OCCURRED
    assert cancelled.lifecycle is EventLifecycle.CANCELLED
    assert superseded.evidence is EvidenceGrade.TENTATIVE

    with pytest.raises(InstitutionalCalendarError) as caught:
        _event(lifecycle=EventLifecycle.OCCURRED)
    assert caught.value.code == "INSTITUTIONAL_EVENT_OCCURRENCE_UNPROVED"


def test_backfilled_event_does_not_rewrite_system_known_history() -> None:
    event = _event(
        evidence=EvidenceGrade.CONFIRMED,
        lifecycle=EventLifecycle.OCCURRED,
        source_published_at=datetime(2020, 1, 2, 1, 30, tzinfo=UTC),
        available_at=datetime(2020, 1, 2, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
    )

    assert event.is_visible(datetime(2020, 1, 2, 2, 0, tzinfo=UTC), KnowledgeMode.MARKET_AVAILABLE)
    assert not event.is_visible(datetime(2020, 1, 2, 2, 0, tzinfo=UTC), KnowledgeMode.SYSTEM_KNOWN)
    assert event.is_visible(datetime(2026, 11, 10, 2, 1, tzinfo=UTC), KnowledgeMode.SYSTEM_KNOWN)


def test_future_versions_and_naive_or_inconsistent_clocks_fail_closed() -> None:
    event = _event()

    assert not event.is_visible(
        event.first_seen_at - timedelta(microseconds=1), KnowledgeMode.SYSTEM_KNOWN
    )
    assert not event.is_visible(
        event.available_at - timedelta(microseconds=1), KnowledgeMode.MARKET_AVAILABLE
    )

    for field in (
        "scheduled_at",
        "source_published_at",
        "available_at",
        "first_seen_at",
        "recorded_at",
    ):
        with pytest.raises(InstitutionalCalendarError) as caught:
            _event(**{field: datetime(2026, 1, 1)})
        assert caught.value.code == "INSTITUTIONAL_EVENT_TIME_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        _event(recorded_at=datetime(2025, 12, 31, tzinfo=UTC))
    assert caught.value.code == "INSTITUTIONAL_EVENT_KNOWLEDGE_TIME_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        _event(original_sha256="not-a-sha")
    assert caught.value.code == "INSTITUTIONAL_EVENT_ORIGINAL_INVALID"


def test_nbs_actual_release_creates_revision_without_mutating_schedule() -> None:
    schedule = _schedule_input().to_event()
    actual = NbsActualReleaseInput(
        source_id=schedule.source_id,
        source_event_id=schedule.source_event_id,
        event_type=schedule.event_type,
        title=schedule.title,
        scheduled_at=schedule.scheduled_at,
        source_published_at=datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
        original_sha256="c" * 64,
    ).to_event(schedule)

    assert schedule.evidence is EvidenceGrade.TENTATIVE
    assert schedule.lifecycle is EventLifecycle.SCHEDULED
    assert schedule.revision == 1
    assert actual.event_id == schedule.event_id
    assert actual.evidence is EvidenceGrade.CONFIRMED
    assert actual.lifecycle is EventLifecycle.OCCURRED
    assert actual.revision == 2
    assert actual.supersedes_event_id == schedule.event_id
    assert actual.original_sha256 != schedule.original_sha256


def test_nbs_actual_release_rejects_schedule_identity_or_time_mismatch() -> None:
    schedule = _schedule_input().to_event()
    actual = NbsActualReleaseInput(
        source_id=schedule.source_id,
        source_event_id="another-source-event",
        event_type=schedule.event_type,
        title=schedule.title,
        scheduled_at=schedule.scheduled_at,
        source_published_at=datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
        original_sha256="c" * 64,
    )

    with pytest.raises(DataFetchError) as caught:
        actual.to_event(schedule)
    assert caught.value.code == "NBS_ACTUAL_SCHEDULE_MISMATCH"


class _EventRepository:
    """Return one exact event version without applying visibility rules."""

    def __init__(self, event: InstitutionalEvent | None) -> None:
        self.event = event

    def get_version(self, event_id: str, revision: int) -> InstitutionalEvent | None:
        """Return the fixture when its exact identity matches."""

        if self.event is None:
            return None
        if self.event.event_id != event_id or self.event.revision != revision:
            return None
        return self.event


def test_application_read_enforces_exact_version_and_selected_knowledge_mode() -> None:
    event = _event()
    use_case = ReadInstitutionalEventUseCase(_EventRepository(event))

    assert (
        use_case.execute(
            event.event_id,
            event.revision,
            known_at=event.recorded_at,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
        == event
    )

    with pytest.raises(DataFetchError) as caught:
        use_case.execute(
            event.event_id,
            event.revision,
            known_at=event.recorded_at - timedelta(microseconds=1),
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_NOT_KNOWN"

    with pytest.raises(DataFetchError) as caught:
        use_case.execute(
            event.event_id,
            2,
            known_at=event.recorded_at,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_VERSION_NOT_FOUND"


def test_window_rule_and_range_validation_reject_ambiguous_inputs() -> None:
    window = six_period_for(date(2026, 12, 31), rule_version=RULE_VERSION)

    with pytest.raises(InstitutionalCalendarError) as caught:
        replace(window, category="01-05")
    assert caught.value.code == "SIX_PERIOD_CATEGORY_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        replace(window, end_date=date(2026, 12, 30))
    assert caught.value.code == "SIX_PERIOD_WINDOW_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        iter_six_period_windows(date(2026, 2, 1), date(2026, 1, 1), rule_version=RULE_VERSION)
    assert caught.value.code == "SIX_PERIOD_RANGE_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        six_period_for(datetime(2026, 1, 1, tzinfo=UTC), rule_version=RULE_VERSION)
    assert caught.value.code == "INSTITUTIONAL_EVENT_DATE_INVALID"


def test_date_only_rule_rejects_bad_timezones_cutoffs_and_calendar_gaps() -> None:
    rule = DateOnlyAvailabilityRule(RULE_VERSION, "Asia/Shanghai", time(18, 0))

    with pytest.raises(InstitutionalCalendarError) as caught:
        DateOnlyAvailabilityRule(RULE_VERSION, "Not/A_Real_Zone", time(18, 0))
    assert caught.value.code == "DATE_ONLY_AVAILABILITY_TIMEZONE_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        DateOnlyAvailabilityRule(RULE_VERSION, "Asia/Shanghai", time(18, 0, tzinfo=UTC))
    assert caught.value.code == "DATE_ONLY_AVAILABILITY_CUTOFF_INVALID"

    with pytest.raises(InstitutionalCalendarError) as caught:
        conservative_date_only_available_at(date(2026, 11, 6), rule, ())
    assert caught.value.code == "DATE_ONLY_AVAILABILITY_UNCOVERED"

    friday_to_monday = _calendar(date(2026, 11, 6), date(2026, 11, 9))
    with pytest.raises(InstitutionalCalendarError) as caught:
        conservative_date_only_available_at(
            date(2026, 11, 6), rule, (friday_to_monday[0], friday_to_monday[-1])
        )
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE"

    with pytest.raises(InstitutionalCalendarError) as caught:
        conservative_date_only_available_at(
            date(2026, 11, 6),
            rule,
            (friday_to_monday[0], friday_to_monday[0], *friday_to_monday[1:]),
        )
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE"

    mixed = (replace(friday_to_monday[0], exchange="SZSE"), *friday_to_monday[1:])
    with pytest.raises(InstitutionalCalendarError) as caught:
        conservative_date_only_available_at(date(2026, 11, 6), rule, mixed)
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_EXCHANGE_MISMATCH"


def test_event_revision_source_and_availability_invariants() -> None:
    for overrides in (
        {"evidence": "tentative"},
        {"revision": 0},
        {"supersedes_event_id": "prior"},
        {"revision": 2},
        {"source_published_at": None},
        {"available_at": datetime(2025, 12, 24, tzinfo=UTC)},
        {"source_published_at": datetime(2025, 12, 25, 1, 30, tzinfo=timezone(timedelta(hours=8)))},
        {"event_id": "bad identity"},
        {"effective_on": datetime(2026, 11, 9, tzinfo=UTC)},
        {"title": ""},
    ):
        with pytest.raises(InstitutionalCalendarError):
            _event(**overrides)

    with pytest.raises(InstitutionalCalendarError) as caught:
        _event().is_visible(datetime(2026, 1, 2, tzinfo=UTC), "system_known")
    assert caught.value.code == "INSTITUTIONAL_EVENT_KNOWLEDGE_MODE_INVALID"


def test_application_wraps_invalid_nbs_and_repository_results() -> None:
    with pytest.raises(DataFetchError) as caught:
        replace(_schedule_input(), original_sha256="bad").to_event()
    assert caught.value.code == "INSTITUTIONAL_EVENT_ORIGINAL_INVALID"

    schedule = _schedule_input().to_event()
    actual = NbsActualReleaseInput(
        source_id=schedule.source_id,
        source_event_id=schedule.source_event_id,
        event_type=schedule.event_type,
        title=schedule.title,
        scheduled_at=schedule.scheduled_at,
        source_published_at=datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
        original_sha256="c" * 64,
    )
    with pytest.raises(DataFetchError) as caught:
        actual.to_event(object())
    assert caught.value.code == "NBS_ACTUAL_SCHEDULE_MISMATCH"

    with pytest.raises(DataFetchError) as caught:
        replace(actual, original_sha256="bad").to_event(schedule)
    assert caught.value.code == "INSTITUTIONAL_EVENT_ORIGINAL_INVALID"

    class InvalidRepository:
        def get_version(self, event_id: str, revision: int) -> InstitutionalEvent | None:
            return object()  # type: ignore[return-value]

    use_case = ReadInstitutionalEventUseCase(InvalidRepository())
    with pytest.raises(DataFetchError) as caught:
        use_case.execute(
            schedule.event_id, 1, known_at=schedule.recorded_at, mode=KnowledgeMode.SYSTEM_KNOWN
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_RESULT_INVALID"

    class MismatchRepository:
        def get_version(self, event_id: str, revision: int) -> InstitutionalEvent | None:
            return schedule

    with pytest.raises(DataFetchError) as caught:
        ReadInstitutionalEventUseCase(MismatchRepository()).execute(
            "another-event", 1, known_at=schedule.recorded_at, mode=KnowledgeMode.SYSTEM_KNOWN
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_VERSION_MISMATCH"

    with pytest.raises(DataFetchError) as caught:
        ReadInstitutionalEventUseCase(_EventRepository(schedule)).execute(
            schedule.event_id,
            1,
            known_at=datetime(2026, 1, 2),
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_TIME_INVALID"


def test_date_only_availability_selects_chronological_session_not_row_order() -> None:
    rule = DateOnlyAvailabilityRule(RULE_VERSION, "Asia/Shanghai", time(18, 0))
    calendar = _calendar(date(2026, 11, 6), date(2026, 11, 10))

    assert conservative_date_only_available_at(
        date(2026, 11, 6), rule, tuple(reversed(calendar))
    ) == datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
