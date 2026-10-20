from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
    simulated_order_fill_trade_key,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
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
    coverage_end: date = date(2026, 10, 23),
    publication: bool = True,
    published_at: datetime = AS_OF - timedelta(minutes=5),
    publication_recorded_at: datetime = AS_OF - timedelta(minutes=4),
    reference_valid_from: datetime = AS_OF - timedelta(days=1),
    reference_valid_until: datetime = AS_OF + timedelta(days=20),
    snapshot_recorded_at: datetime = AS_OF - timedelta(minutes=10),
    source_published_at: datetime | None = AS_OF - timedelta(minutes=30),
) -> ExecutionCalendarEvidence:
    """Build explicit synthetic calendar facts with no weekday inference."""

    coverage_start = date(2026, 10, 15)
    day_rows: list[ExchangeCalendarDay] = []
    previous_open = date(2026, 10, 14)
    current = coverage_start
    while current <= coverage_end:
        is_open = current in _OPEN_DATES
        day_rows.append(
            ExchangeCalendarDay(
                exchange="SH",
                calendar_date=current,
                is_open=is_open,
                previous_open_date=previous_open,
            )
        )
        if is_open:
            previous_open = current
        current += timedelta(days=1)

    response_completed_at = AS_OF - timedelta(minutes=20)
    rows = tuple(day_rows)
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SH", coverage_start, coverage_end
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange="SH",
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
    published_reference = (
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
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=published_reference)


def _proof(
    *,
    event_at: datetime = AS_OF,
    read_cutoff: datetime = AS_OF,
    lag: int = 1,
    evidence: ExecutionCalendarEvidence | None = None,
    fill_session: date = date(2026, 10, 16),
    expected_release: date = date(2026, 10, 19),
) -> OrderFillSettlementProof:
    """Build a proof using fixed claims, without pre-running the subject methods."""

    calendar = evidence or _calendar()
    return OrderFillSettlementProof(
        calendar_evidence=calendar,
        calendar_read_cutoff=read_cutoff,
        fill_occurred_at=event_at,
        settlement_exchange="SH",
        fill_market_session=fill_session,
        settlement_lag_sessions=lag,
        expected_release_session=expected_release,
    )


def test_timezone_boundary_uses_fill_instant_local_date_and_preserves_source_clocks() -> None:
    event_at = datetime(2026, 10, 18, 16, 30, tzinfo=UTC)
    read_cutoff = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)

    proof = build_order_fill_settlement_proof(
        calendar_evidence=_calendar(),
        calendar_read_cutoff=read_cutoff,
        fill_occurred_at=event_at,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )

    assert proof.fill_market_session == date(2026, 10, 19)
    assert proof.expected_release_session == date(2026, 10, 20)
    payload = proof.to_payload()
    calendar_payload = payload["calendar_evidence"]
    assert isinstance(calendar_payload, dict)
    snapshot_payload = calendar_payload["snapshot"]
    assert isinstance(snapshot_payload, dict)
    raw_payload = snapshot_payload["raw_reference"]
    assert isinstance(raw_payload, dict)
    publication_payload = calendar_payload["publication"]
    assert isinstance(publication_payload, dict)
    assert snapshot_payload["source_published_at"] == "2026-10-16T01:30:00.000000Z"
    assert snapshot_payload["first_seen_at"] == "2026-10-16T01:40:00.000000Z"
    assert snapshot_payload["recorded_at"] == "2026-10-16T01:50:00.000000Z"
    assert raw_payload["response_completed_at"] == "2026-10-16T01:40:00.000000Z"
    assert publication_payload["published_at"] == "2026-10-16T01:55:00.000000Z"
    assert publication_payload["recorded_at"] == "2026-10-16T01:56:00.000000Z"
    assert publication_payload["reference_valid_from"] == "2026-10-15T02:00:00.000000Z"
    assert publication_payload["reference_valid_until"] == "2026-11-05T02:00:00.000000Z"
    assert payload["fill_occurred_at"] == "2026-10-18T16:30:00.000000Z"
    assert payload["calendar_read_cutoff"] == "2026-10-18T17:00:00.000000Z"
    assert len(proof.proof_hash) == 64


def test_two_fill_instants_get_independent_open_sessions_and_t_plus_one_release_dates() -> None:
    evidence = _calendar()

    first = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=AS_OF,
        fill_occurred_at=AS_OF,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )
    second_at = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    second = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=second_at,
        fill_occurred_at=second_at,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )

    assert (first.fill_market_session, first.expected_release_session) == (
        date(2026, 10, 16),
        date(2026, 10, 19),
    )
    assert (second.fill_market_session, second.expected_release_session) == (
        date(2026, 10, 19),
        date(2026, 10, 20),
    )
    assert first.proof_hash != second.proof_hash


def test_explicit_zero_lag_releases_on_the_fill_session() -> None:
    proof = build_order_fill_settlement_proof(
        calendar_evidence=_calendar(),
        calendar_read_cutoff=AS_OF,
        fill_occurred_at=AS_OF,
        settlement_exchange="SH",
        settlement_lag_sessions=0,
    )

    assert proof.fill_market_session == date(2026, 10, 16)
    assert proof.expected_release_session == date(2026, 10, 16)


@pytest.mark.parametrize(
    ("event_at", "read_cutoff", "evidence", "expected_error"),
    (
        (
            datetime(2026, 10, 17, 2, 0, tzinfo=UTC),
            datetime(2026, 10, 17, 3, 0, tzinfo=UTC),
            None,
            CalendarEvidenceValidationError,
        ),
        (
            datetime(2026, 10, 24, 2, 0, tzinfo=UTC),
            datetime(2026, 10, 24, 3, 0, tzinfo=UTC),
            None,
            CalendarEvidenceValidationError,
        ),
        (
            datetime(2026, 10, 23, 2, 0, tzinfo=UTC),
            datetime(2026, 10, 23, 3, 0, tzinfo=UTC),
            None,
            CalendarEvidenceValidationError,
        ),
    ),
)
def test_closed_uncovered_or_insufficient_future_calendar_is_rejected(
    event_at: datetime,
    read_cutoff: datetime,
    evidence: ExecutionCalendarEvidence | None,
    expected_error: type[Exception],
) -> None:
    if event_at.date() == date(2026, 10, 23):
        calendar = _calendar(coverage_end=date(2026, 10, 23))
    elif event_at.date() == date(2026, 10, 24):
        calendar = _calendar(coverage_end=date(2026, 10, 23))
    else:
        calendar = evidence or _calendar()

    with pytest.raises(expected_error):
        build_order_fill_settlement_proof(
            calendar_evidence=calendar,
            calendar_read_cutoff=read_cutoff,
            fill_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


def test_missing_publication_cannot_authorize_a_new_fill() -> None:
    evidence = _calendar(publication=False)

    with pytest.raises(CalendarEvidenceValidationError):
        build_order_fill_settlement_proof(
            calendar_evidence=evidence,
            calendar_read_cutoff=AS_OF,
            fill_occurred_at=AS_OF,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


@pytest.mark.parametrize(
    ("published_at", "publication_recorded_at", "event_at", "read_cutoff"),
    (
        (
            AS_OF + timedelta(minutes=30),
            AS_OF + timedelta(minutes=35),
            AS_OF,
            AS_OF + timedelta(hours=1),
        ),
        (
            AS_OF + timedelta(minutes=30),
            AS_OF + timedelta(minutes=35),
            AS_OF,
            AS_OF + timedelta(minutes=20),
        ),
    ),
)
def test_publication_not_known_at_fill_or_read_cutoff_is_rejected(
    published_at: datetime,
    publication_recorded_at: datetime,
    event_at: datetime,
    read_cutoff: datetime,
) -> None:
    evidence = _calendar(
        published_at=published_at,
        publication_recorded_at=publication_recorded_at,
    )

    with pytest.raises(CalendarEvidenceValidationError):
        build_order_fill_settlement_proof(
            calendar_evidence=evidence,
            calendar_read_cutoff=read_cutoff,
            fill_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


@pytest.mark.parametrize(
    ("event_at", "read_cutoff"),
    (
        (
            datetime(2026, 10, 16, 13, 0, tzinfo=UTC),
            datetime(2026, 10, 17, 2, 0, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 16, 3, 0, tzinfo=UTC),
            datetime(2026, 10, 17, 2, 0, tzinfo=UTC),
        ),
    ),
)
def test_publication_expired_at_event_or_read_cutoff_is_rejected(
    event_at: datetime,
    read_cutoff: datetime,
) -> None:
    evidence = _calendar(reference_valid_until=datetime(2026, 10, 16, 12, 0, tzinfo=UTC))

    with pytest.raises(CalendarEvidenceValidationError):
        build_order_fill_settlement_proof(
            calendar_evidence=evidence,
            calendar_read_cutoff=read_cutoff,
            fill_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


def test_fill_event_before_reference_window_is_rejected_after_cutoff_validation() -> None:
    event_at = AS_OF
    read_cutoff = AS_OF + timedelta(minutes=10)
    evidence = _calendar(
        reference_valid_from=AS_OF + timedelta(minutes=5),
        reference_valid_until=AS_OF + timedelta(minutes=20),
    )

    evidence.validate_for(read_cutoff)

    with pytest.raises(CalendarEvidenceValidationError):
        build_order_fill_settlement_proof(
            calendar_evidence=evidence,
            calendar_read_cutoff=read_cutoff,
            fill_occurred_at=event_at,
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


def test_event_must_not_follow_read_cutoff() -> None:
    with pytest.raises(SimulatedSettlementContractError):
        build_order_fill_settlement_proof(
            calendar_evidence=_calendar(),
            calendar_read_cutoff=AS_OF,
            fill_occurred_at=AS_OF + timedelta(seconds=1),
            settlement_exchange="SH",
            settlement_lag_sessions=1,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("calendar_read_cutoff", datetime(2026, 10, 16, 2, 0)),
        ("fill_occurred_at", datetime(2026, 10, 16, 2, 0)),
        ("calendar_read_cutoff", "2026-10-16T02:00:00Z"),
        ("fill_occurred_at", "2026-10-16T02:00:00Z"),
    ),
)
def test_naive_or_wrong_clock_types_are_rejected(field_name: str, value: object) -> None:
    with pytest.raises(SimulatedSettlementContractError):
        replace(_proof(), **{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("settlement_lag_sessions", True),
        ("settlement_lag_sessions", -1),
        ("settlement_exchange", ""),
        ("fill_market_session", datetime(2026, 10, 16, 0, 0, tzinfo=UTC)),
        ("expected_release_session", datetime(2026, 10, 19, 0, 0, tzinfo=UTC)),
    ),
)
def test_exact_field_types_and_claimed_values_are_revalidated(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(SimulatedSettlementContractError):
        replace(_proof(), **{field_name: value})


def test_wrong_claimed_session_release_lag_and_exchange_are_rejected() -> None:
    proof = _proof()
    invalid_claims = (
        {"fill_market_session": date(2026, 10, 19)},
        {"expected_release_session": date(2026, 10, 20)},
        {"settlement_lag_sessions": 0},
        {"settlement_exchange": "SZ"},
    )

    for fields in invalid_claims:
        with pytest.raises(CalendarEvidenceValidationError):
            replace(proof, **fields)


def test_proof_hash_binds_read_cutoff_and_complete_source_clock_evidence() -> None:
    original = _proof()
    later_cutoff = _proof(read_cutoff=AS_OF + timedelta(minutes=1))
    changed_source_clock = _calendar(source_published_at=AS_OF - timedelta(minutes=31))
    changed_evidence = _proof(evidence=changed_source_clock)

    assert len(original.proof_hash) == 64
    assert original.proof_hash != later_cutoff.proof_hash
    assert original.proof_hash != changed_evidence.proof_hash
    assert original.to_payload()["schema"] == "simulated-order-fill-settlement-proof.v1"


def test_offset_equivalent_cutoff_and_event_instants_have_the_same_proof_hash() -> None:
    offset_instant = datetime(2026, 10, 16, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    evidence = _calendar()

    utc_proof = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=AS_OF,
        fill_occurred_at=AS_OF,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )
    offset_proof = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=offset_instant,
        fill_occurred_at=offset_instant,
        settlement_exchange="SH",
        settlement_lag_sessions=1,
    )

    assert utc_proof.to_payload() == offset_proof.to_payload()
    assert utc_proof.proof_hash == offset_proof.proof_hash


def test_trade_key_is_stable_and_scoped_only_by_reservation_namespace_and_event() -> None:
    first = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local.matcher.v1",
        fill_event_id="event-100",
    )
    repeated = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local.matcher.v1",
        fill_event_id="event-100",
    )
    other_namespace = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local.matcher.v2",
        fill_event_id="event-100",
    )
    other_event = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local.matcher.v1",
        fill_event_id="event-101",
    )
    other_reservation = simulated_order_fill_trade_key(
        reservation_id=42,
        source_namespace="local.matcher.v1",
        fill_event_id="event-100",
    )
    delimiter_left = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local:a",
        fill_event_id="b:c",
    )
    delimiter_right = simulated_order_fill_trade_key(
        reservation_id=41,
        source_namespace="local",
        fill_event_id="a:b:c",
    )

    assert first == repeated
    assert first.startswith("simfill:") and len(first) == len("simfill:") + 64
    assert first != other_namespace
    assert first != other_event
    assert first != other_reservation
    assert delimiter_left != delimiter_right


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("calendar_evidence", None),
        ("calendar_read_cutoff", None),
        ("fill_occurred_at", None),
        ("settlement_exchange", None),
        ("fill_market_session", None),
        ("settlement_lag_sessions", None),
        ("expected_release_session", None),
    ),
)
def test_proof_rejects_none_for_each_required_field(field_name: str, value: object) -> None:
    with pytest.raises(SimulatedSettlementContractError):
        replace(_proof(), **{field_name: value})


def test_trade_key_rejects_none_for_each_required_identity_part() -> None:
    with pytest.raises(SimulatedSettlementContractError):
        simulated_order_fill_trade_key(
            reservation_id=cast(int, None),
            source_namespace="local.matcher.v1",
            fill_event_id="event-100",
        )
    with pytest.raises(SimulatedSettlementContractError):
        simulated_order_fill_trade_key(
            reservation_id=41,
            source_namespace=cast(str, None),
            fill_event_id="event-100",
        )
    with pytest.raises(SimulatedSettlementContractError):
        simulated_order_fill_trade_key(
            reservation_id=41,
            source_namespace="local.matcher.v1",
            fill_event_id=cast(str, None),
        )


@pytest.mark.parametrize(
    ("reservation_id", "namespace", "event_id"),
    (
        (0, "local.matcher.v1", "event-100"),
        (True, "local.matcher.v1", "event-100"),
        (41, "", "event-100"),
        (41, "local matcher", "event-100"),
        (41, "local.matcher.v1", ""),
        (41, "local.matcher.v1", "event id"),
        (41, "n" * 129, "event-100"),
        (41, "local.matcher.v1", "e" * 129),
    ),
)
def test_trade_key_rejects_invalid_or_oversized_identity_parts(
    reservation_id: int,
    namespace: str,
    event_id: str,
) -> None:
    with pytest.raises(SimulatedSettlementContractError):
        simulated_order_fill_trade_key(
            reservation_id=reservation_id,
            source_namespace=namespace,
            fill_event_id=event_id,
        )
