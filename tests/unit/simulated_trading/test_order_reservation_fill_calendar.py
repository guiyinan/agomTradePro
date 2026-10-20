from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)

AS_OF = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
_OPEN_DATES = frozenset(
    {
        date(2026, 10, 15),
        date(2026, 10, 16),
        date(2026, 10, 19),
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    }
)


def _calendar(
    *,
    exchange: str = "SH",
    coverage_end: date = date(2026, 10, 23),
    publication: bool = True,
    published_at: datetime = datetime(2026, 10, 16, 1, 55, tzinfo=UTC),
    publication_recorded_at: datetime = datetime(2026, 10, 16, 1, 56, tzinfo=UTC),
    reference_valid_from: datetime = datetime(2026, 10, 15, 2, 0, tzinfo=UTC),
    reference_valid_until: datetime = datetime(2026, 11, 5, 2, 0, tzinfo=UTC),
    snapshot_recorded_at: datetime = datetime(2026, 10, 16, 1, 50, tzinfo=UTC),
    source_published_at: datetime | None = datetime(2026, 10, 16, 1, 30, tzinfo=UTC),
) -> ExecutionCalendarEvidence:
    """Build full typed calendar facts; dates are explicit, never weekday-inferred."""

    coverage_start = date(2026, 10, 15)
    day_rows: list[ExchangeCalendarDay] = []
    previous_open = date(2026, 10, 14)
    current = coverage_start
    while current <= coverage_end:
        is_open = current in _OPEN_DATES
        day_rows.append(
            ExchangeCalendarDay(
                exchange=exchange,
                calendar_date=current,
                is_open=is_open,
                previous_open_date=previous_open,
            )
        )
        if is_open:
            previous_open = current
        current += timedelta(days=1)

    rows = tuple(day_rows)
    response_completed_at = datetime(2026, 10, 16, 1, 40, tzinfo=UTC)
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            exchange, coverage_start, coverage_end
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=rows,
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=snapshot_recorded_at,
        source_published_at=source_published_at,
    )
    reference = (
        CalendarPublicationReference(
            publication_id="calendar-publication-202610",
            member_id=snapshot.snapshot_id,
            publication_hash="2" * 64,
            fact_content_hash="4" * 64,
            policy_hash="3" * 64,
            published_at=published_at,
            recorded_at=publication_recorded_at,
            reference_valid_from=reference_valid_from,
            reference_valid_until=reference_valid_until,
            timezone_name="Asia/Shanghai",
        )
        if publication
        else None
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=reference)


class _Clock:
    """Return one exact injected read cutoff and record clock access."""

    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _CalendarReader:
    """Capture the public published-calendar query boundary for one test."""

    def __init__(
        self,
        evidence: ExecutionCalendarEvidence | None,
        error: ExecutionCalendarUnavailable | SimulatedTradeExecutionBlocked | None = None,
    ) -> None:
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[str, datetime, date | None]] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        self.calls.append((exchange, as_of, coverage_start))
        if self.error is not None:
            raise self.error
        return self.evidence


def _resolver(
    evidence: ExecutionCalendarEvidence | None,
    *,
    clock: _Clock | None = None,
    error: ExecutionCalendarUnavailable | SimulatedTradeExecutionBlocked | None = None,
) -> tuple[OrderFillSettlementCalendarResolver, _CalendarReader, _Clock]:
    selected_clock = clock or _Clock(AS_OF)
    reader = _CalendarReader(evidence, error=error)
    return (
        OrderFillSettlementCalendarResolver(calendar_reader=reader, clock=selected_clock),
        reader,
        selected_clock,
    )


def test_resolver_uses_clock_cutoff_and_requests_only_a_conservative_lower_bound() -> None:
    evidence = _calendar()
    event_at = datetime(2026, 10, 19, 0, 30, tzinfo=timezone(timedelta(hours=8)))
    clock = _Clock(AS_OF)
    resolver, reader, _ = _resolver(evidence, clock=clock)

    proof = resolver.resolve(
        event_occurred_at=event_at,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )

    assert type(proof) is OrderFillSettlementProof
    assert proof.fill_occurred_at == event_at
    assert proof.calendar_read_cutoff == AS_OF
    assert proof.fill_market_session == date(2026, 10, 19)
    assert proof.expected_release_session == date(2026, 10, 20)
    assert reader.calls == [("SH", AS_OF, date(2026, 10, 17))]
    assert clock.calls == 1
    # The UTC-day-minus-one value is only the reader's coverage lower bound;
    # the actual session was derived from the local fill instant above.
    assert reader.calls[0][2] != proof.fill_market_session


def test_resolver_preserves_calendar_source_and_publication_clocks() -> None:
    evidence = _calendar()
    event_at = datetime(2026, 10, 18, 16, 30, tzinfo=UTC)
    resolver, _, _ = _resolver(evidence)

    proof = resolver.resolve(
        event_occurred_at=event_at,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )

    assert (
        proof.calendar_evidence.snapshot.source_published_at
        == evidence.snapshot.source_published_at
    )
    assert proof.calendar_evidence.snapshot.first_seen_at == evidence.snapshot.first_seen_at
    assert proof.calendar_evidence.snapshot.recorded_at == evidence.snapshot.recorded_at
    assert proof.calendar_evidence.snapshot.raw_reference.response_completed_at == (
        evidence.snapshot.raw_reference.response_completed_at
    )
    assert proof.calendar_evidence.publication == evidence.publication
    assert proof.calendar_read_cutoff == AS_OF


@pytest.mark.parametrize(
    ("event_at", "lag", "evidence", "exchange"),
    (
        (datetime(2026, 10, 17, 2, 0, tzinfo=UTC), 1, None, "SH"),
        (datetime(2026, 10, 24, 2, 0, tzinfo=UTC), 1, None, "SH"),
        (datetime(2026, 10, 23, 2, 0, tzinfo=UTC), 1, None, "SH"),
        (datetime(2026, 10, 18, 16, 30, tzinfo=UTC), 1, None, "SZ"),
    ),
)
def test_closed_uncovered_lag_or_exchange_mismatch_blocks_with_stable_code(
    event_at: datetime,
    lag: int,
    evidence: ExecutionCalendarEvidence | None,
    exchange: str,
) -> None:
    calendar = evidence or _calendar()
    cutoff = max(AS_OF, event_at + timedelta(minutes=1))
    resolver, reader, _ = _resolver(calendar, clock=_Clock(cutoff))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=event_at,
            settlement_exchange=exchange,
            settlement_lag_sessions=lag,
        )

    assert raised.value.code == "FILL_SETTLEMENT_EVIDENCE_INVALID"
    assert reader.calls == [(exchange, cutoff, event_at.astimezone(UTC).date() - timedelta(days=1))]


def test_publication_that_was_not_known_at_fill_time_is_rejected() -> None:
    event_at = datetime(2026, 10, 18, 16, 30, tzinfo=UTC)
    evidence = _calendar(
        published_at=event_at + timedelta(minutes=1),
        publication_recorded_at=event_at + timedelta(minutes=2),
    )
    resolver, _, _ = _resolver(evidence, clock=_Clock(AS_OF))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value.code == "FILL_SETTLEMENT_EVIDENCE_INVALID"
    assert isinstance(raised.value.__cause__, CalendarEvidenceValidationError)


@pytest.mark.parametrize("expire_at_event", (True, False))
def test_expired_publication_is_rejected_at_fill_or_read_cutoff(expire_at_event: bool) -> None:
    event_at = datetime(2026, 10, 18, 16, 30, tzinfo=UTC)
    cutoff = AS_OF
    expiry = event_at - timedelta(seconds=1) if expire_at_event else cutoff - timedelta(seconds=1)
    evidence = _calendar(reference_valid_until=expiry)
    resolver, _, _ = _resolver(evidence, clock=_Clock(cutoff))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value.code == "FILL_SETTLEMENT_EVIDENCE_INVALID"
    assert isinstance(raised.value.__cause__, CalendarEvidenceValidationError)


def test_unpublished_calendar_is_rejected_by_domain_evidence_check() -> None:
    resolver, reader, _ = _resolver(_calendar(publication=False))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=datetime(2026, 10, 18, 16, 30, tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value.code == "FILL_SETTLEMENT_EVIDENCE_INVALID"
    assert isinstance(raised.value.__cause__, CalendarEvidenceValidationError)
    assert len(reader.calls) == 1


def test_reader_none_maps_to_existing_stable_calendar_unavailable_code() -> None:
    resolver, reader, clock = _resolver(None)

    with pytest.raises(ExecutionCalendarUnavailable) as raised:
        resolver.resolve(
            event_occurred_at=datetime(2026, 10, 18, 16, 30, tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value.code == "EXECUTION_CALENDAR_UNAVAILABLE"
    assert reader.calls == [("SH", AS_OF, date(2026, 10, 17))]
    assert clock.calls == 1


def test_reader_typed_block_preserves_its_stable_code_and_object() -> None:
    upstream = SimulatedTradeExecutionBlocked(
        "calendar publication is not current", code="CURRENT_CALENDAR_POINTER_UNVERIFIED"
    )
    resolver, reader, clock = _resolver(_calendar(), error=upstream)

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=datetime(2026, 10, 18, 16, 30, tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value is upstream
    assert raised.value.code == "CURRENT_CALENDAR_POINTER_UNVERIFIED"
    assert len(reader.calls) == 1
    assert clock.calls == 1


@pytest.mark.parametrize(
    ("event_at", "exchange", "lag"),
    (
        (datetime(2026, 10, 18, 16, 30), "SH", 1),
        (datetime(2026, 10, 18, 16, 30, tzinfo=UTC), " SH ", 1),
        (datetime(2026, 10, 18, 16, 30, tzinfo=UTC), "SH", True),
        (datetime(2026, 10, 18, 16, 30, tzinfo=UTC), "SH", -1),
        (datetime(2026, 10, 18, 16, 30, tzinfo=UTC), "SH", 1.0),
    ),
)
def test_invalid_event_time_exchange_or_lag_is_rejected_before_calendar_read(
    event_at: datetime,
    exchange: str,
    lag: int,
) -> None:
    resolver, reader, clock = _resolver(_calendar())

    with pytest.raises(SimulatedTradeExecutionInputError):
        resolver.resolve(
            event_occurred_at=event_at,
            settlement_exchange=exchange,
            settlement_lag_sessions=lag,
        )

    assert reader.calls == []
    assert clock.calls == 0


def test_future_event_is_rejected_after_clock_read_without_calendar_read() -> None:
    event_at = AS_OF + timedelta(seconds=1)
    resolver, reader, clock = _resolver(_calendar(), clock=_Clock(AS_OF))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        resolver.resolve(
            event_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert raised.value.code == "FILL_SETTLEMENT_EVENT_AFTER_READ_CUTOFF"
    assert reader.calls == []
    assert clock.calls == 1


def test_naive_injected_cutoff_is_rejected_without_calendar_read() -> None:
    resolver, reader, clock = _resolver(_calendar(), clock=_Clock(AS_OF.replace(tzinfo=None)))

    with pytest.raises(SimulatedTradeExecutionInputError):
        resolver.resolve(
            event_occurred_at=datetime(2026, 10, 18, 16, 30, tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert reader.calls == []
    assert clock.calls == 1


def test_utc_day_minus_one_underflow_is_a_typed_input_error() -> None:
    resolver, reader, clock = _resolver(_calendar())

    with pytest.raises(SimulatedTradeExecutionInputError):
        resolver.resolve(
            event_occurred_at=datetime.min.replace(tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=0,
        )

    assert reader.calls == []
    assert clock.calls == 0


def test_non_utc_injected_cutoff_is_rejected_for_existing_public_reader_contract() -> None:
    non_utc = datetime(2026, 10, 19, 1, 0, tzinfo=timezone(timedelta(hours=8)))
    resolver, reader, clock = _resolver(_calendar(), clock=_Clock(non_utc))

    with pytest.raises(SimulatedTradeExecutionInputError):
        resolver.resolve(
            event_occurred_at=datetime(2026, 10, 18, 16, 30, tzinfo=UTC),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )

    assert reader.calls == []
    assert clock.calls == 1
