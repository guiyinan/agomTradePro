"""Institutional-calendar queries expose only the state known at the cutoff."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from apps.data_center.application.institutional_calendar_query import (
    QueryInstitutionalCalendarUseCase,
)
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    InstitutionalEvent,
    KnowledgeMode,
)
from core.exceptions import DataFetchError

KNOWN_AT = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)


def _event(**overrides: object) -> InstitutionalEvent:
    """Return a valid scheduled event with independently mutable revisions."""

    values: dict[str, object] = {
        "event_id": "nbs-cpi-2026-10",
        "source_id": "nbs_official",
        "source_event_id": "2026-schedule-cpi-october",
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


def _occurred(**overrides: object) -> InstitutionalEvent:
    """Return a confirmed successor with explicit source and system clocks."""

    values: dict[str, object] = {
        "evidence": EvidenceGrade.CONFIRMED,
        "lifecycle": EventLifecycle.OCCURRED,
        "revision": 2,
        "effective_on": date(2026, 11, 9),
        "source_published_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "available_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "first_seen_at": datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 11, 9, 2, 1, tzinfo=UTC),
        "original_sha256": "b" * 64,
        "supersedes_event_id": "nbs-cpi-2026-10",
    }
    values.update(overrides)
    return _event(**values)


class _Repository:
    """Return immutable fixture versions without applying query semantics."""

    def __init__(self, events: tuple[InstitutionalEvent, ...]) -> None:
        self.events = events

    def list_versions(self) -> tuple[InstitutionalEvent, ...]:
        """Return every stored version, including versions future to the caller."""

        return self.events


def _query(
    events: tuple[InstitutionalEvent, ...], *, timezone_name: str = "Asia/Shanghai"
) -> QueryInstitutionalCalendarUseCase:
    """Build the pure use case with an in-memory exact-version port."""

    return QueryInstitutionalCalendarUseCase(_Repository(events), timezone_name=timezone_name)


def test_query_selects_latest_visible_revision_before_applying_lifecycle_filter() -> None:
    use_case = _query((_event(), _occurred()))

    occurred = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        lifecycle=EventLifecycle.OCCURRED,
    )
    scheduled = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        lifecycle=EventLifecycle.SCHEDULED,
    )

    assert len(occurred) == 1
    assert occurred[0].event.revision == 2
    assert occurred[0].event.lifecycle is EventLifecycle.OCCURRED
    assert occurred[0].event_on == date(2026, 11, 9)
    assert scheduled == ()


def test_future_revision_neither_leaks_nor_hides_the_known_schedule() -> None:
    future = _occurred(
        first_seen_at=datetime(2026, 12, 1, tzinfo=UTC),
        recorded_at=datetime(2026, 12, 1, 0, 1, tzinfo=UTC),
    )
    use_case = _query((_event(), future))

    before = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    after = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=future.recorded_at,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )

    assert [entry.event.revision for entry in before] == [1]
    assert [entry.event.revision for entry in after] == [2]


def test_cancelled_successor_cannot_be_resurrected_by_an_occurred_filter() -> None:
    cancelled = _occurred(lifecycle=EventLifecycle.CANCELLED, effective_on=None)
    use_case = _query((_event(), cancelled))

    occurred = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        lifecycle=EventLifecycle.OCCURRED,
    )
    all_states = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )

    assert occurred == ()
    assert [entry.event.lifecycle for entry in all_states] == [EventLifecycle.CANCELLED]


def test_revision_date_and_type_are_resolved_before_filtering() -> None:
    moved = _event(
        revision=2,
        supersedes_event_id="nbs-cpi-2026-10",
        event_type="policy_release",
        scheduled_at=datetime(2026, 12, 10, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 8, 0, 1, tzinfo=UTC),
    )
    use_case = _query((_event(), moved))

    old_identity = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        event_type="macro_release",
    )
    new_identity = use_case.execute(
        date(2026, 12, 10),
        date(2026, 12, 10),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        event_type="policy_release",
    )

    assert old_identity == ()
    assert [entry.event.revision for entry in new_identity] == [2]


def test_query_uses_inclusive_local_dates_and_stable_order() -> None:
    crosses_midnight = _event(
        event_id="event-b", scheduled_at=datetime(2026, 11, 9, 16, 0, tzinfo=UTC)
    )
    same_local_day = _event(
        event_id="event-a", scheduled_at=datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
    )
    use_case = _query((crosses_midnight, same_local_day))

    previous_utc_day = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    local_day = use_case.execute(
        date(2026, 11, 10),
        date(2026, 11, 10),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )

    assert previous_utc_day == ()
    assert [entry.event.event_id for entry in local_day] == ["event-a", "event-b"]
    assert all(entry.event_on == date(2026, 11, 10) for entry in local_day)


def test_query_distinguishes_market_availability_from_system_knowledge() -> None:
    backfilled = _occurred(
        source_published_at=datetime(2020, 1, 2, 1, 30, tzinfo=UTC),
        available_at=datetime(2020, 1, 2, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
    )
    use_case = _query((backfilled,))
    cutoff = datetime(2020, 1, 2, 2, 0, tzinfo=UTC)

    market = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=cutoff,
        mode=KnowledgeMode.MARKET_AVAILABLE,
    )
    system = use_case.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=cutoff,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )

    assert len(market) == 1
    assert system == ()


def test_empty_and_non_matching_results_are_stable_empty_tuples() -> None:
    assert (
        _query(()).execute(
            date(2026, 11, 1),
            date(2026, 11, 30),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
        == ()
    )
    assert (
        _query((_event(),)).execute(
            date(2026, 11, 1),
            date(2026, 11, 30),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
            event_type="policy_release",
        )
        == ()
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 11, 10), date(2026, 11, 9)),
        (datetime(2026, 11, 9, tzinfo=UTC), date(2026, 11, 9)),
        (date(2026, 11, 9), datetime(2026, 11, 9, tzinfo=UTC)),
    ],
)
def test_query_rejects_invalid_date_ranges(start: object, end: object) -> None:
    with pytest.raises(DataFetchError) as caught:
        _query(()).execute(
            start,  # type: ignore[arg-type]
            end,  # type: ignore[arg-type]
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_QUERY_RANGE_INVALID"


@pytest.mark.parametrize(
    ("known_at", "mode", "event_type", "lifecycle", "code"),
    [
        (
            datetime(2026, 11, 10),
            KnowledgeMode.SYSTEM_KNOWN,
            None,
            None,
            "INSTITUTIONAL_EVENT_TIME_INVALID",
        ),
        (
            KNOWN_AT.replace(tzinfo=timezone(timedelta(hours=8))),
            KnowledgeMode.SYSTEM_KNOWN,
            None,
            None,
            "INSTITUTIONAL_EVENT_TIME_INVALID",
        ),
        (
            KNOWN_AT,
            "system_known",
            None,
            None,
            "INSTITUTIONAL_EVENT_KNOWLEDGE_MODE_INVALID",
        ),
        (
            KNOWN_AT,
            KnowledgeMode.SYSTEM_KNOWN,
            "bad identity",
            None,
            "INSTITUTIONAL_CALENDAR_QUERY_FILTER_INVALID",
        ),
        (
            KNOWN_AT,
            KnowledgeMode.SYSTEM_KNOWN,
            None,
            "occurred",
            "INSTITUTIONAL_CALENDAR_QUERY_FILTER_INVALID",
        ),
    ],
)
def test_query_validates_cutoff_and_filters_even_for_empty_repositories(
    known_at: object, mode: object, event_type: object, lifecycle: object, code: str
) -> None:
    with pytest.raises(DataFetchError) as caught:
        _query(()).execute(
            date(2026, 11, 9),
            date(2026, 11, 9),
            known_at=known_at,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            lifecycle=lifecycle,  # type: ignore[arg-type]
        )
    assert caught.value.code == code


def test_query_rejects_unknown_timezone() -> None:
    with pytest.raises(DataFetchError) as caught:
        _query((), timezone_name="Not/A_Real_Zone")
    assert caught.value.code == "INSTITUTIONAL_CALENDAR_QUERY_TIMEZONE_INVALID"


def test_query_rejects_duplicate_versions_even_when_they_are_not_visible() -> None:
    duplicate = _event(
        first_seen_at=datetime(2027, 1, 1, tzinfo=UTC),
        recorded_at=datetime(2027, 1, 1, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(DataFetchError) as caught:
        _query((_event(), duplicate)).execute(
            date(2026, 11, 9),
            date(2026, 11, 9),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_VERSION_DUPLICATE"


def test_query_rejects_invalid_repository_results_and_missing_event_dates() -> None:
    class ListRepository:
        def list_versions(self) -> tuple[InstitutionalEvent, ...]:
            return [_event()]  # type: ignore[return-value]

    with pytest.raises(DataFetchError) as caught:
        QueryInstitutionalCalendarUseCase(ListRepository(), timezone_name="Asia/Shanghai").execute(
            date(2026, 11, 9),
            date(2026, 11, 9),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_RESULT_INVALID"

    class ObjectRepository:
        def list_versions(self) -> tuple[InstitutionalEvent, ...]:
            return (object(),)  # type: ignore[return-value]

    with pytest.raises(DataFetchError) as caught:
        QueryInstitutionalCalendarUseCase(
            ObjectRepository(), timezone_name="Asia/Shanghai"
        ).execute(
            date(2026, 11, 9),
            date(2026, 11, 9),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_RESULT_INVALID"

    undated = _event(scheduled_at=None, effective_on=None)
    with pytest.raises(DataFetchError) as caught:
        _query((undated,)).execute(
            date(2026, 11, 9),
            date(2026, 11, 9),
            known_at=KNOWN_AT,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_DATE_MISSING"
