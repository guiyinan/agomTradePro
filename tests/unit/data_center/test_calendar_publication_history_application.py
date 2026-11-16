"""Pure contract tests for the historical calendar read Application."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarPublicationAuditPair,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalCalendarPublicationRecord as HistoricalRecord,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalPublishedExchangeCalendar as HistoricalResult,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    ReadExchangeCalendarPublicationAsOfQuery as ReadQuery,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    ReadExchangeCalendarPublicationAsOfUseCase as ReadUseCase,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from tests.unit.data_center.test_financial_next_session_availability import (
    KNOWN_AT as CALENDAR_KNOWN_AT,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    _calendar,
)


def _record(
    *,
    lifecycle: CalendarPublicationLifecycle = CalendarPublicationLifecycle.SUPERSEDED,
    superseded_at: datetime | None = None,
) -> object:
    """Reuse the repository's complete calendar fixture and alter only lifecycle."""

    record, _pointer = _calendar()
    selected_superseded_at = (
        superseded_at
        if superseded_at is not None
        else (
            None
            if lifecycle is CalendarPublicationLifecycle.PUBLISHED
            else CALENDAR_KNOWN_AT + timedelta(minutes=3)
        )
    )
    return HistoricalRecord(
        seal=record.seal,
        publication_id=record.publication_id,
        lifecycle=lifecycle,
        published_at=record.published_at,
        superseded_at=selected_superseded_at,
    )


def _audit_pair(record: object) -> CalendarPublicationAuditPair:
    """Build a typed pair bound to one fixture publication."""

    return CalendarPublicationAuditPair(
        database_alias="default",
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        event_id="calendar-published-event-1",
        event_content_hash="a" * 64,
        actor_user_id=1,
        outbox_id=uuid4(),
        idempotency_key="calendar-published-event-1",
        recorded_at=record.published_at,
    )


def _result(
    record: object,
    *,
    as_of: datetime = CALENDAR_KNOWN_AT,
) -> object:
    """Build one valid history result without asserting database authority."""

    return HistoricalResult(record=record, audit_pair=_audit_pair(record), as_of=as_of)


def test_historical_record_uses_half_open_published_and_superseded_window() -> None:
    record = _record()
    assert record.is_effective_at(record.published_at)
    assert record.is_effective_at(record.superseded_at - timedelta(microseconds=1))
    assert not record.is_effective_at(record.superseded_at)
    assert not record.is_effective_at(record.published_at - timedelta(microseconds=1))


def test_historical_record_uses_response_ttl_as_second_exclusive_boundary() -> None:
    record = _record(superseded_at=CALENDAR_KNOWN_AT + timedelta(minutes=10))
    expires_at = record.seal.snapshot_first_seen_at + timedelta(
        seconds=record.seal.calendar_response_max_age_seconds
    )
    assert record.is_effective_at(expires_at - timedelta(microseconds=1))
    assert not record.is_effective_at(expires_at)


@pytest.mark.parametrize("publication_id", [1, True, None, object()])
def test_query_rejects_non_text_publication_identity(publication_id: object) -> None:
    with pytest.raises(CalendarFormalPublicationApplicationError):
        ReadQuery(
            publication_id=publication_id,
            publication_hash="a" * 64,
            dataset_key="data_center.exchange_calendar_snapshot",
            exchange="SZSE",
            as_of=CALENDAR_KNOWN_AT,
        )


@pytest.mark.parametrize("publication_id", [1, True, None, object()])
def test_record_rejects_non_text_publication_identity(publication_id: object) -> None:
    record = _record()
    with pytest.raises(CalendarFormalPublicationApplicationError):
        HistoricalRecord(
            seal=record.seal,
            publication_id=publication_id,
            lifecycle=record.lifecycle,
            published_at=record.published_at,
            superseded_at=record.superseded_at,
        )


def test_result_is_reference_only_and_requires_exact_audit_identity() -> None:
    result = _result(_record())
    assert result.must_not_execute is True
    assert result.reference_only is True
    assert not hasattr(result, "pointer")
    assert not hasattr(result.record, "activation_id")

    record = _record()
    wrong_pair = CalendarPublicationAuditPair(
        database_alias="default",
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        publication_id=record.publication_id,
        publication_hash="b" * 64,
        event_id="calendar-published-event-2",
        event_content_hash="c" * 64,
        actor_user_id=1,
        outbox_id=uuid4(),
        idempotency_key="calendar-published-event-2",
        recorded_at=record.published_at,
    )
    with pytest.raises(CalendarFormalPublicationApplicationError):
        HistoricalResult(record=record, audit_pair=wrong_pair, as_of=CALENDAR_KNOWN_AT)


def test_use_case_rejects_future_cutoff_before_reader_call() -> None:
    record = _record()
    query = ReadQuery(
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        as_of=CALENDAR_KNOWN_AT + timedelta(seconds=1),
    )

    class Reader:
        called = False

        def read_publication_as_of(self, _query: object) -> object:
            self.called = True
            return _result(record, as_of=query.as_of)

    class Clock:
        def now(self) -> datetime:
            return CALENDAR_KNOWN_AT

    reader = Reader()
    use_case = ReadUseCase(reader, clock=Clock())
    with pytest.raises(CalendarFormalPublicationApplicationError):
        use_case.execute(query)
    assert reader.called is False


def test_use_case_rejects_reader_result_from_another_scope() -> None:
    record = _record()
    query = ReadQuery(
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        as_of=CALENDAR_KNOWN_AT,
    )
    other_record = _record(lifecycle=CalendarPublicationLifecycle.PUBLISHED)

    class Reader:
        def read_publication_as_of(self, _query: object) -> object:
            return _result(other_record, as_of=query.as_of)

    class Clock:
        def now(self) -> datetime:
            return CALENDAR_KNOWN_AT

    use_case = ReadUseCase(Reader(), clock=Clock())
    with pytest.raises(CalendarFormalPublicationApplicationError):
        use_case.execute(query)
