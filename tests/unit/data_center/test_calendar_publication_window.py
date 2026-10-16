"""Published calendar response-age windows retain their separate clock semantics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from uuid import uuid4

import pytest

from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
    CalendarPublicationWindow,
    CalendarPublicationWindowError,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)

FIRST_SEEN_AT = datetime(2026, 10, 16, 4, 0, 0, tzinfo=UTC)
CALENDAR_DATE = date(2026, 10, 16)


class _NoOffset(tzinfo):
    """Provide a malformed aware-clock adapter for UTC validation coverage."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None


def _snapshot(
    *,
    first_seen_at: datetime = FIRST_SEEN_AT,
    recorded_at: datetime | None = None,
) -> ExchangeCalendarSnapshot:
    """Build one source-bound calendar snapshot without changing its evidence."""

    raw_reference = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", CALENDAR_DATE, CALENDAR_DATE
        ),
        original_body_retained=True,
        response_completed_at=first_seen_at,
        provider_name="tushare",
        dataset_key="tushare.exchange_calendar.raw",
        transport="direct",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SSE",
        coverage_start=CALENDAR_DATE,
        coverage_end=CALENDAR_DATE,
        days=(
            ExchangeCalendarDay(
                exchange="SSE",
                calendar_date=CALENDAR_DATE,
                is_open=True,
                previous_open_date=date(2026, 10, 15),
            ),
        ),
        provider_name="tushare",
        raw_reference=raw_reference,
        first_seen_at=first_seen_at,
    )
    return make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at or first_seen_at + timedelta(seconds=1),
    )


def _window(
    *,
    snapshot: ExchangeCalendarSnapshot | None = None,
    ttl: int = 30,
    published_at: datetime | None = None,
    lifecycle: CalendarPublicationLifecycle = CalendarPublicationLifecycle.PUBLISHED,
    superseded_at: datetime | None = None,
) -> CalendarPublicationWindow:
    """Build one calendar response-age window with explicit lifecycle evidence."""

    selected = snapshot or _snapshot()
    return CalendarPublicationWindow(
        snapshot=selected,
        calendar_response_max_age_seconds=ttl,
        published_at=published_at or selected.recorded_at + timedelta(seconds=1),
        lifecycle=lifecycle,
        superseded_at=superseded_at,
    )


def test_window_anchors_first_seen_and_uses_a_half_open_response_age_window() -> None:
    snapshot = _snapshot()
    content_hash = snapshot.content_hash
    record_digest = snapshot.record_digest
    published_at = snapshot.recorded_at + timedelta(seconds=1)
    window = _window(snapshot=snapshot, ttl=30, published_at=published_at)

    assert window.response_expires_at == FIRST_SEEN_AT + timedelta(seconds=30)
    assert window.valid_from == published_at
    assert window.valid_until == FIRST_SEEN_AT + timedelta(seconds=30)
    assert window.is_effective_at(published_at)
    assert not window.is_effective_at(published_at - timedelta(microseconds=1))
    assert not window.is_effective_at(window.valid_until)
    assert snapshot.first_seen_at == FIRST_SEEN_AT
    assert snapshot.content_hash == content_hash
    assert snapshot.record_digest == record_digest


def test_window_ends_at_earlier_forward_supersede_time() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)
    superseded_at = published_at + timedelta(seconds=5)
    window = _window(
        snapshot=snapshot,
        ttl=30,
        published_at=published_at,
        lifecycle=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at=superseded_at,
    )

    assert window.valid_until == superseded_at
    assert window.is_effective_at(superseded_at - timedelta(microseconds=1))
    assert not window.is_effective_at(superseded_at)


def test_window_ends_at_response_expiry_when_supersede_is_later() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)
    window = _window(
        snapshot=snapshot,
        ttl=10,
        published_at=published_at,
        lifecycle=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at=published_at + timedelta(seconds=20),
    )

    assert window.valid_until == FIRST_SEEN_AT + timedelta(seconds=10)


@pytest.mark.parametrize(
    ("lifecycle", "superseded_at"),
    [
        (CalendarPublicationLifecycle.ROLLED_BACK, None),
        (CalendarPublicationLifecycle.REINSTATED, None),
        (CalendarPublicationLifecycle.UNSUPPORTED, None),
    ],
)
def test_window_rejects_unsupported_publication_lifecycle(
    lifecycle: CalendarPublicationLifecycle,
    superseded_at: datetime | None,
) -> None:
    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(lifecycle=lifecycle, superseded_at=superseded_at)

    assert caught.value.code == "CALENDAR_WINDOW_LIFECYCLE_UNSUPPORTED"


def test_window_rejects_published_time_before_snapshot_knowledge() -> None:
    snapshot = _snapshot()

    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(snapshot=snapshot, published_at=snapshot.recorded_at - timedelta(seconds=1))

    assert caught.value.code == "CALENDAR_WINDOW_KNOWLEDGE_TIME_INVALID"


def test_window_rejects_non_snapshot_and_corrupted_snapshot_evidence() -> None:
    valid = _snapshot()
    published_at = valid.recorded_at + timedelta(seconds=1)

    with pytest.raises(CalendarPublicationWindowError) as wrong_type:
        CalendarPublicationWindow(
            snapshot=object(),  # type: ignore[arg-type]
            calendar_response_max_age_seconds=30,
            published_at=published_at,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            superseded_at=None,
        )
    assert wrong_type.value.code == "CALENDAR_WINDOW_SNAPSHOT_INVALID"

    object.__setattr__(valid, "content_hash", "sha256:corrupt")
    with pytest.raises(CalendarPublicationWindowError) as corrupted:
        _window(snapshot=valid, published_at=published_at)
    assert corrupted.value.code == "CALENDAR_WINDOW_SNAPSHOT_INVALID"


def test_window_rejects_untyped_lifecycle_and_missing_supersede_time() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)

    with pytest.raises(CalendarPublicationWindowError) as untyped:
        _window(
            snapshot=snapshot,
            published_at=published_at,
            lifecycle="published",  # type: ignore[arg-type]
        )
    assert untyped.value.code == "CALENDAR_WINDOW_LIFECYCLE_INVALID"

    with pytest.raises(CalendarPublicationWindowError) as missing_time:
        _window(
            snapshot=snapshot,
            published_at=published_at,
            lifecycle=CalendarPublicationLifecycle.SUPERSEDED,
        )
    assert missing_time.value.code == "CALENDAR_WINDOW_LIFECYCLE_INVALID"


def test_window_rejects_supersede_before_publication_knowledge() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)

    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(
            snapshot=snapshot,
            published_at=published_at,
            lifecycle=CalendarPublicationLifecycle.SUPERSEDED,
            superseded_at=published_at - timedelta(microseconds=1),
        )

    assert caught.value.code == "CALENDAR_WINDOW_KNOWLEDGE_TIME_INVALID"


@pytest.mark.parametrize("ttl", [True, 0, -1, 2**63, 1.5, "30"])
def test_window_rejects_noncanonical_or_out_of_range_ttl(ttl: object) -> None:
    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(ttl=ttl)  # type: ignore[arg-type]

    assert caught.value.code == "CALENDAR_WINDOW_TTL_INVALID"


def test_window_rejects_datetime_overflow_without_clamping() -> None:
    latest = datetime.max.replace(tzinfo=UTC)
    snapshot = _snapshot(first_seen_at=latest, recorded_at=latest)

    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(snapshot=snapshot, ttl=1, published_at=latest)

    assert caught.value.code == "CALENDAR_WINDOW_EXPIRY_OVERFLOW"


def test_window_rejects_response_already_expired_at_publication() -> None:
    published_at = FIRST_SEEN_AT + timedelta(seconds=5)
    snapshot = _snapshot(
        first_seen_at=FIRST_SEEN_AT,
        recorded_at=published_at,
    )

    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(snapshot=snapshot, ttl=5, published_at=published_at)

    assert caught.value.code == "CALENDAR_WINDOW_EXPIRED_AT_PUBLICATION"


def test_window_rejects_zero_length_superseded_window() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)

    with pytest.raises(CalendarPublicationWindowError) as caught:
        _window(
            snapshot=snapshot,
            published_at=published_at,
            lifecycle=CalendarPublicationLifecycle.SUPERSEDED,
            superseded_at=published_at,
        )

    assert caught.value.code == "CALENDAR_WINDOW_EXPIRED_AT_PUBLICATION"


def test_window_rejects_inconsistent_lifecycle_and_non_utc_query_time() -> None:
    snapshot = _snapshot()
    published_at = snapshot.recorded_at + timedelta(seconds=1)

    with pytest.raises(CalendarPublicationWindowError) as bad_state:
        _window(
            snapshot=snapshot,
            published_at=published_at,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            superseded_at=published_at + timedelta(seconds=2),
        )
    assert bad_state.value.code == "CALENDAR_WINDOW_LIFECYCLE_INVALID"

    window = _window(snapshot=snapshot, published_at=published_at)
    with pytest.raises(CalendarPublicationWindowError) as bad_clock:
        window.is_effective_at(datetime(2026, 10, 16, 12, 0))
    assert bad_clock.value.code == "CALENDAR_WINDOW_TIME_INVALID"

    with pytest.raises(CalendarPublicationWindowError) as missing_offset:
        window.is_effective_at(datetime(2026, 10, 16, 12, 0, tzinfo=_NoOffset()))
    assert missing_offset.value.code == "CALENDAR_WINDOW_TIME_INVALID"
