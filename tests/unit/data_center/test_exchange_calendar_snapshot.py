"""Source-bound exchange calendar snapshots must not accept another venue."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest

from apps.data_center.application.exchange_calendar import (
    IngestExchangeCalendarSnapshotUseCase,
    ReadExchangeCalendarSnapshotUseCase,
    ReadNextExchangeCalendarSessionUseCase,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarError,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    ExchangeCalendarSnapshotReference,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
    next_exchange_calendar_session,
)
from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource
from core.exceptions import DataFetchError


class TushareCalendarClient:
    """Return a controlled Tushare calendar response and retain request scope."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def trade_cal(self, **kwargs: object) -> pd.DataFrame:
        """Record the explicit request and return its configured rows."""

        self.calls.append(kwargs)
        return pd.DataFrame(self.rows)


def test_tushare_calendar_rejects_rows_for_another_exchange() -> None:
    """A valid-looking calendar cannot cross venue identity at the source edge."""

    client = TushareCalendarClient(
        [
            {"exchange": "SZSE", "cal_date": "20260923", "is_open": "1"},
            {"exchange": "SZSE", "cal_date": "20260924", "is_open": "0"},
        ]
    )
    source = TushareModelMarketSource(client)

    with pytest.raises(DataFetchError) as caught:
        source.trading_calendar_evidence(date(2026, 9, 23), date(2026, 9, 24))

    assert caught.value.code == "MODEL_MARKET_CALENDAR_EXCHANGE_MISMATCH"
    assert client.calls[0]["exchange"] == "SSE"


FIRST_SEEN_AT = datetime(2026, 10, 16, 4, 0, 1, tzinfo=UTC)
EXCHANGE = "SSE"
START = date(2026, 10, 15)
END = date(2026, 10, 18)


def _day(
    day: date, is_open: bool, previous_open: date, *, exchange: str = EXCHANGE
) -> ExchangeCalendarDay:
    return ExchangeCalendarDay(
        exchange=exchange,
        calendar_date=day,
        is_open=is_open,
        previous_open_date=previous_open,
    )


def _raw_reference(
    *,
    exchange: str = EXCHANGE,
    start: date = START,
    end: date = END,
    original_body_retained: bool = True,
    first_seen_at: datetime = FIRST_SEEN_AT,
) -> ExchangeCalendarRawReference:
    return ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(exchange, start, end),
        original_body_retained=original_body_retained,
        response_completed_at=first_seen_at,
        provider_name="tushare",
        dataset_key="tushare.exchange_calendar.raw",
        transport="direct",
    )


def _candidate(
    *,
    days: tuple[ExchangeCalendarDay, ...] | None = None,
    exchange: str = EXCHANGE,
    start: date = START,
    end: date = END,
    raw_reference: ExchangeCalendarRawReference | None = None,
    first_seen_at: datetime = FIRST_SEEN_AT,
    source_published_at: datetime | None = None,
) -> ExchangeCalendarSnapshotCandidate:
    selected_days = days or (
        _day(date(2026, 10, 15), True, date(2026, 10, 14)),
        _day(date(2026, 10, 16), True, date(2026, 10, 15)),
        _day(date(2026, 10, 17), False, date(2026, 10, 16)),
        _day(date(2026, 10, 18), False, date(2026, 10, 16)),
    )
    return ExchangeCalendarSnapshotCandidate(
        exchange=exchange,
        coverage_start=start,
        coverage_end=end,
        days=selected_days,
        provider_name="tushare",
        raw_reference=raw_reference or _raw_reference(exchange=exchange, start=start, end=end),
        first_seen_at=first_seen_at,
        source_published_at=source_published_at,
    )


def _snapshot(
    candidate: ExchangeCalendarSnapshotCandidate | None = None,
    *,
    recorded_at: datetime = FIRST_SEEN_AT + timedelta(seconds=1),
) -> ExchangeCalendarSnapshot:
    selected = candidate or _candidate()
    return make_exchange_calendar_snapshot(
        selected,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at,
    )


def test_candidate_requires_complete_explicit_daily_states_and_previous_open_chain() -> None:
    candidate = _candidate()

    assert len(candidate.days) == 4
    assert candidate.days[2].is_open is False
    assert candidate.source_published_at is None
    assert candidate.content_hash.startswith("sha256:")
    assert candidate.to_payload()["raw_reference"]["response_time_semantics"] == (
        "local_response_body_completion"
    )

    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(days=candidate.days[:-1])
    assert caught.value.code == "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE"

    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(
            days=(candidate.days[0], candidate.days[2], candidate.days[1], candidate.days[3])
        )
    assert caught.value.code == "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE"

    wrong_previous = (
        candidate.days[0],
        candidate.days[1],
        candidate.days[2],
        _day(date(2026, 10, 18), False, date(2026, 10, 15)),
    )
    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(days=wrong_previous)
    assert caught.value.code == "EXCHANGE_CALENDAR_PREVIOUS_OPEN_MISMATCH"


def test_candidate_rejects_wrong_exchange_state_types_and_request_scope() -> None:
    candidate = _candidate()

    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(
            days=(
                candidate.days[0],
                _day(date(2026, 10, 16), True, date(2026, 10, 15), exchange="SZSE"),
                *candidate.days[2:],
            )
        )
    assert caught.value.code == "EXCHANGE_CALENDAR_EXCHANGE_MISMATCH"

    with pytest.raises(ExchangeCalendarError) as caught:
        ExchangeCalendarDay(EXCHANGE, START, 1, date(2026, 10, 14))  # type: ignore[arg-type]
    assert caught.value.code == "EXCHANGE_CALENDAR_STATE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        ExchangeCalendarDay(EXCHANGE, START, True, START)
    assert caught.value.code == "EXCHANGE_CALENDAR_PREVIOUS_OPEN_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(raw_reference=_raw_reference(exchange="SZSE"))
    assert caught.value.code == "EXCHANGE_CALENDAR_REQUEST_SCOPE_MISMATCH"

    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(first_seen_at=FIRST_SEEN_AT + timedelta(seconds=1))
    assert caught.value.code == "EXCHANGE_CALENDAR_FIRST_SEEN_MISMATCH"


def test_raw_reference_requires_exact_original_body_and_valid_identity() -> None:
    with pytest.raises(ExchangeCalendarError) as caught:
        _raw_reference(original_body_retained=False)
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_BODY_NOT_RETAINED"

    raw_reference = _raw_reference()
    with pytest.raises(ExchangeCalendarError) as caught:
        replace(raw_reference, retained_content_sha256="4" * 64)
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(raw_reference, transport="sdk")
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(raw_reference, transport=[])
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(raw_reference, payload_hash=object())
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(raw_reference, response_completed_at=FIRST_SEEN_AT.replace(tzinfo=None))
    assert caught.value.code == "EXCHANGE_CALENDAR_TIME_INVALID"


def test_snapshot_separates_content_hash_from_first_record_digest_and_exact_reference() -> None:
    snapshot = _snapshot()
    reference = snapshot.reference()

    assert snapshot.content_hash == snapshot.candidate.content_hash
    assert snapshot.record_digest.startswith("sha256:")
    assert reference.snapshot_id == snapshot.snapshot_id
    assert reference.raw_payload_id == snapshot.raw_reference.payload_id
    payload = snapshot.to_payload()
    assert payload["source_published_at"] is None
    assert payload["publication_status"] == "unpublished"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True
    assert payload["blocked_reason"] == "exchange_calendar_unpublished_reference"
    assert payload["content_hash"] == snapshot.content_hash
    assert payload["record_digest"] == snapshot.record_digest

    with pytest.raises(ExchangeCalendarError) as caught:
        make_exchange_calendar_snapshot(
            snapshot.candidate,
            snapshot_id=str(uuid4()),
            recorded_at=FIRST_SEEN_AT - timedelta(seconds=1),
        )
    assert caught.value.code == "EXCHANGE_CALENDAR_KNOWLEDGE_TIME_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot, content_hash="sha256:" + "a" * 64)
    assert caught.value.code == "EXCHANGE_CALENDAR_CONTENT_HASH_MISMATCH"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot, record_digest="sha256:" + "a" * 64)
    assert caught.value.code == "EXCHANGE_CALENDAR_RECORD_DIGEST_MISMATCH"


def test_exact_reference_and_next_session_fail_closed_outside_explicit_coverage() -> None:
    snapshot = _snapshot()

    assert next_exchange_calendar_session(snapshot, after_date=date(2026, 10, 15)) == date(
        2026, 10, 16
    )
    with pytest.raises(ExchangeCalendarError) as caught:
        next_exchange_calendar_session(snapshot, after_date=date(2026, 10, 18))
    assert caught.value.code == "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED"
    with pytest.raises(ExchangeCalendarError) as caught:
        next_exchange_calendar_session(snapshot, after_date=date(2026, 10, 14))
    assert caught.value.code == "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot.reference(), content_hash="invalid")
    assert caught.value.code == "EXCHANGE_CALENDAR_REFERENCE_INVALID"


class _Source:
    def __init__(self, candidate: ExchangeCalendarSnapshotCandidate) -> None:
        self.candidate = candidate
        self.calls: list[tuple[str, date, date]] = []

    def fetch_candidate(
        self, exchange: str, coverage_start: date, coverage_end: date
    ) -> ExchangeCalendarSnapshotCandidate:
        self.calls.append((exchange, coverage_start, coverage_end))
        return self.candidate


class _Repository:
    def __init__(self, snapshot: ExchangeCalendarSnapshot | None) -> None:
        self.snapshot = snapshot
        self.saved: list[ExchangeCalendarSnapshotCandidate] = []

    def save(self, candidate: ExchangeCalendarSnapshotCandidate) -> ExchangeCalendarSnapshot:
        self.saved.append(candidate)
        assert self.snapshot is not None
        return self.snapshot

    def get_exact(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> ExchangeCalendarSnapshot | None:
        if self.snapshot is None or self.snapshot.reference() != reference:
            return None
        if self.snapshot.recorded_at > known_at or self.snapshot.first_seen_at > known_at:
            return None
        return self.snapshot


def test_ingest_and_exact_read_preserve_scope_and_knowledge_cutoff() -> None:
    candidate = _candidate()
    snapshot = _snapshot(candidate)
    source = _Source(candidate)
    repository = _Repository(snapshot)

    stored = IngestExchangeCalendarSnapshotUseCase(source, repository).execute(EXCHANGE, START, END)
    reread = ReadExchangeCalendarSnapshotUseCase(repository).execute(
        snapshot.reference(), known_at=snapshot.recorded_at
    )

    assert stored == snapshot
    assert reread == snapshot
    assert source.calls == [(EXCHANGE, START, END)]
    assert repository.saved == [candidate]

    with pytest.raises(DataFetchError) as caught:
        ReadExchangeCalendarSnapshotUseCase(repository).execute(
            snapshot.reference(), known_at=FIRST_SEEN_AT - timedelta(microseconds=1)
        )
    assert caught.value.code == "EXCHANGE_CALENDAR_SNAPSHOT_NOT_KNOWN"

    with pytest.raises(DataFetchError) as caught:
        ReadNextExchangeCalendarSessionUseCase(
            ReadExchangeCalendarSnapshotUseCase(repository)
        ).execute(
            snapshot.reference(),
            after_date=date(2026, 10, 18),
            known_at=snapshot.recorded_at,
        )
    assert caught.value.code == "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED"


def test_ingest_rejects_a_source_that_changes_the_requested_scope() -> None:
    candidate = _candidate()
    repository = _Repository(_snapshot(candidate))

    with pytest.raises(DataFetchError) as caught:
        IngestExchangeCalendarSnapshotUseCase(_Source(candidate), repository).execute(
            "SZSE", START, END
        )

    assert caught.value.code == "EXCHANGE_CALENDAR_SOURCE_SCOPE_MISMATCH"


def test_domain_rejects_malformed_calendar_dates_and_identity_tokens() -> None:
    with pytest.raises(ExchangeCalendarError) as caught:
        exchange_calendar_request_scope_hash(EXCHANGE, END, START)
    assert caught.value.code == "EXCHANGE_CALENDAR_COVERAGE_INVALID"

    for exchange in ("", " SSE", "SSE ", "SSE\n", "S" * 33):
        with pytest.raises(ExchangeCalendarError) as caught:
            ExchangeCalendarDay(exchange, START, True, date(2026, 10, 14))
        assert caught.value.code == "EXCHANGE_CALENDAR_IDENTITY_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        ExchangeCalendarDay(EXCHANGE, datetime(2026, 10, 15, tzinfo=UTC), True, date(2026, 10, 14))  # type: ignore[arg-type]
    assert caught.value.code == "EXCHANGE_CALENDAR_DATE_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_id", "not-a-uuid"),
        ("payload_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("payload_hash", "1" * 64),
        ("record_digest", "sha256:bad"),
        ("body_sha256", "z" * 64),
        ("request_scope_sha256", "short"),
    ],
)
def test_raw_reference_rejects_malformed_ids_and_digests(field: str, value: str) -> None:
    with pytest.raises(ExchangeCalendarError) as caught:
        replace(_raw_reference(), **{field: value})
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"


def test_candidate_rejects_invalid_dates_rows_provider_and_publication_time() -> None:
    candidate = _candidate()
    with pytest.raises(ExchangeCalendarError) as caught:
        _candidate(start=END, end=START)
    assert caught.value.code == "EXCHANGE_CALENDAR_COVERAGE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(candidate, days=())
    assert caught.value.code == "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE"

    for rows in (
        [candidate.days[0]],
        (object(), *candidate.days[1:]),
        (candidate.days[0], object(), *candidate.days[2:]),
    ):
        with pytest.raises(ExchangeCalendarError) as caught:
            _candidate(days=tuple(rows))
        assert caught.value.code in {
            "EXCHANGE_CALENDAR_COVERAGE_INCOMPLETE",
            "EXCHANGE_CALENDAR_DAY_INVALID",
        }

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(candidate, raw_reference=object())
    assert caught.value.code == "EXCHANGE_CALENDAR_RAW_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(candidate, provider_name="other-provider")
    assert caught.value.code == "EXCHANGE_CALENDAR_PROVIDER_MISMATCH"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(candidate, source_published_at=FIRST_SEEN_AT.replace(tzinfo=None))
    assert caught.value.code == "EXCHANGE_CALENDAR_TIME_INVALID"


def test_snapshot_reference_and_next_session_reject_noncanonical_values() -> None:
    snapshot = _snapshot()
    for snapshot_id in ("not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"):
        with pytest.raises(ExchangeCalendarError) as caught:
            replace(snapshot, snapshot_id=snapshot_id)
        assert caught.value.code == "EXCHANGE_CALENDAR_SNAPSHOT_ID_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot, candidate=object())
    assert caught.value.code == "EXCHANGE_CALENDAR_SNAPSHOT_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot, record_digest="invalid")
    assert caught.value.code == "EXCHANGE_CALENDAR_RECORD_DIGEST_INVALID"

    assert snapshot.provider_name == "tushare"
    assert snapshot.source_published_at is None

    for reference_field, value in (
        ("snapshot_id", "not-a-uuid"),
        ("raw_payload_id", "not-a-uuid"),
        ("raw_payload_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("content_hash", "invalid"),
        ("record_digest", "invalid"),
        ("raw_record_digest", "invalid"),
        ("raw_payload_hash", "invalid"),
    ):
        reference = snapshot.reference()
        with pytest.raises(ExchangeCalendarError) as caught:
            replace(reference, **{reference_field: value})
        assert caught.value.code == "EXCHANGE_CALENDAR_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        replace(snapshot.reference(), coverage_start=END, coverage_end=START)
    assert caught.value.code == "EXCHANGE_CALENDAR_REFERENCE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        next_exchange_calendar_session(snapshot, after_date=datetime(2026, 10, 15, tzinfo=UTC))  # type: ignore[arg-type]
    assert caught.value.code == "EXCHANGE_CALENDAR_DATE_INVALID"

    with pytest.raises(ExchangeCalendarError) as caught:
        next_exchange_calendar_session(snapshot, after_date=date(2026, 10, 16))
    assert caught.value.code == "EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED"
