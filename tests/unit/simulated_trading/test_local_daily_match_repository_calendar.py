from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    _build_daily_match_settlement_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    canonical_snapshot,
    snapshot_digest,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_calendar_codec import (
    decode_sealed_order_calendar_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)

_EVENT_AT = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
_SESSION_DATE = date(2026, 10, 19)
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


def _calendar_evidence(
    *,
    published_at: datetime = datetime(2026, 10, 16, 1, 55, tzinfo=UTC),
    publication_recorded_at: datetime = datetime(2026, 10, 16, 1, 56, tzinfo=UTC),
    reference_valid_until: datetime = datetime(2026, 11, 5, 2, 0, tzinfo=UTC),
    publication: bool = True,
) -> ExecutionCalendarEvidence:
    """Build explicit persisted calendar facts for a pure event-time proof."""

    coverage_start = date(2026, 10, 15)
    coverage_end = date(2026, 10, 23)
    days: list[ExchangeCalendarDay] = []
    previous_open = date(2026, 10, 14)
    current = coverage_start
    while current <= coverage_end:
        is_open = current in _OPEN_DATES
        days.append(
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

    completed_at = datetime(2026, 10, 16, 1, 40, tzinfo=UTC)
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
        response_completed_at=completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange="SH",
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=tuple(days),
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=completed_at,
        recorded_at=datetime(2026, 10, 16, 1, 50, tzinfo=UTC),
        source_published_at=datetime(2026, 10, 16, 1, 30, tzinfo=UTC),
    )
    publication_reference = (
        CalendarPublicationReference(
            publication_id="calendar-publication-202610",
            member_id=snapshot.snapshot_id,
            publication_hash="2" * 64,
            fact_content_hash="4" * 64,
            policy_hash="3" * 64,
            published_at=published_at,
            recorded_at=publication_recorded_at,
            reference_valid_from=datetime(2026, 10, 15, 2, 0, tzinfo=UTC),
            reference_valid_until=reference_valid_until,
            timezone_name="Asia/Shanghai",
        )
        if publication
        else None
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication_reference)


def _reservation_row(calendar_payload: object) -> SimulatedOrderReservationModel:
    """Create an unsaved reservation row whose plan snapshot is hash sealed."""

    snapshot = canonical_snapshot(
        {
            "schema": "simulated-order-reservation-plan.v1",
            "settlement_lag_sessions": 2,
            "calendar_evidence": calendar_payload,
        }
    )
    return SimulatedOrderReservationModel(
        plan_snapshot_version=1,
        plan_snapshot=snapshot,
        plan_snapshot_hash=snapshot_digest(snapshot),
        pk=10,
        account_id=20,
        owner_user_id=30,
        idempotency_key="order-1",
        security_id="600000.SH",
        asset_code="600000.SH",
        settlement_lag_sessions=2,
    )


def _evidence_payload(evidence: ExecutionCalendarEvidence) -> dict[str, object]:
    """Serialize evidence in the exact reservation-plan representation."""

    return {
        "snapshot": evidence.snapshot.to_payload(),
        "publication": (
            evidence.publication.to_payload() if evidence.publication is not None else None
        ),
        "evidence_hash": evidence.evidence_hash,
    }


def _event(row: SimulatedOrderReservationModel) -> LocalSimulatedFillEventV1:
    """Build the daily interval event shape consumed by the repository guard."""

    return LocalSimulatedFillEventV1(
        source_namespace="simulated-local-daily-match.v1",
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        source_event_id="match-operation-1",
        event_payload_hash="a" * 64,
        source_snapshot_id="snapshot-1",
        source_snapshot_hash="b" * 64,
        reservation_id=row.pk,
        account_id=row.account_id,
        user_id=row.owner_user_id,
        order_idempotency_key=row.idempotency_key,
        intent_payload_hash="c" * 64,
        reservation_request_hash="d" * 64,
        plan_snapshot_hash=row.plan_snapshot_hash,
        security_id="600000.SH",
        asset_code="600000.SH",
        side=SimulatedTradeSide.BUY,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("100"),
        price=Decimal("11.47"),
        occurred_at=_EVENT_AT,
        source_observed_at=None,
        source_available_at=None,
        recorded_at=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
        observation_basis="daily_interval_end",
        interval_end_at=_EVENT_AT,
        local_known_at=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
    )


def _build(
    row: SimulatedOrderReservationModel,
    *,
    event: LocalSimulatedFillEventV1 | None = None,
    session_date: date = _SESSION_DATE,
    settlement_exchange: str = "SH",
) -> OrderFillSettlementProof:
    """Run the producer's pure event-time calendar proof helper."""

    return _build_daily_match_settlement_proof(
        reservation_row=row,
        event=event or _event(row),
        session_date=session_date,
        settlement_exchange=settlement_exchange,
        settlement_lag_sessions=2,
    )


def test_matched_event_requires_complete_calendar_known_at_event_time() -> None:
    evidence = _calendar_evidence()
    payload = _evidence_payload(evidence)
    row = _reservation_row(payload)

    proof = _build(row)

    assert proof.calendar_evidence == decode_sealed_order_calendar_evidence(payload)
    assert proof.calendar_read_cutoff == _EVENT_AT
    assert proof.fill_occurred_at == _EVENT_AT
    assert proof.fill_market_session == _SESSION_DATE
    assert proof.settlement_exchange == "SH"
    assert proof.settlement_lag_sessions == 2
    assert proof.expected_release_session == date(2026, 10, 21)


def test_event_calendar_rejects_publication_not_known_at_event_time() -> None:
    evidence = _calendar_evidence(
        published_at=_EVENT_AT + timedelta(seconds=1),
        publication_recorded_at=_EVENT_AT + timedelta(seconds=2),
    )
    row = _reservation_row(_evidence_payload(evidence))
    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


def test_event_calendar_rejects_expired_reference_at_event_time() -> None:
    evidence = _calendar_evidence(reference_valid_until=_EVENT_AT)
    row = _reservation_row(_evidence_payload(evidence))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


def test_event_calendar_rejects_reference_only_evidence() -> None:
    row = _reservation_row(_evidence_payload(_calendar_evidence(publication=False)))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


@pytest.mark.parametrize(
    ("session_date", "settlement_exchange"),
    [
        (_SESSION_DATE, "SZSE"),
        (date(2026, 10, 20), "SH"),
    ],
)
def test_event_calendar_rejects_misbound_event_scope(
    session_date: date,
    settlement_exchange: str,
) -> None:
    row = _reservation_row(_evidence_payload(_calendar_evidence()))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(
            row,
            session_date=session_date,
            settlement_exchange=settlement_exchange,
        )

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


def test_event_calendar_rejects_interval_end_that_differs_from_occurrence() -> None:
    row = _reservation_row(_evidence_payload(_calendar_evidence()))
    event = replace(_event(row), interval_end_at=_EVENT_AT + timedelta(seconds=1))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row, event=event)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


@pytest.mark.parametrize("calendar_payload", [None, {"snapshot": {}}])
def test_event_calendar_rejects_missing_or_incomplete_plan_evidence(
    calendar_payload: object,
) -> None:
    row = _reservation_row(calendar_payload)

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"


@pytest.mark.parametrize(
    "mutation",
    ["legacy_basis", "source_observed", "source_available", "recorded_before_event"],
)
def test_event_calendar_requires_daily_basis_and_separate_local_clock(
    mutation: str,
) -> None:
    row = _reservation_row(_evidence_payload(_calendar_evidence()))
    event = _event(row)
    if mutation == "legacy_basis":
        event = replace(event, observation_basis="legacy_source_observed")
    elif mutation == "source_observed":
        event = replace(event, source_observed_at=_EVENT_AT)
    elif mutation == "source_available":
        event = replace(event, source_available_at=_EVENT_AT)
    else:
        event = replace(event, recorded_at=_EVENT_AT - timedelta(seconds=1))

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _build(row, event=event)

    assert raised.value.code == "LOCAL_DAILY_MATCH_EVENT_CALENDAR_INVALID"
