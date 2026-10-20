"""Strict V4 fill/calendar binding codec boundary tests (not a writer test)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
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
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationBook,
    OrderReservationRequest,
    reserve_order,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_binding_codec import (
    OrderReservationFillBindingV4,
    decode_order_reservation_fill_binding,
    encode_order_reservation_fill_binding,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_calendar_codec import (
    decode_order_fill_settlement_proof,
    encode_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    EncodedOrderReservationFillSnapshot,
    encode_order_reservation_fill_snapshot,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
ZERO_MONEY = Decimal("0.00")
ZERO_SHARES = Decimal("0.000000")
ZERO_FEES = TradeFeeBreakdown(ZERO_MONEY, ZERO_MONEY, ZERO_MONEY, ZERO_MONEY, ZERO_MONEY)
SOURCE_NAMESPACE = "fixture-local-matcher"
SOURCE_VERSION = "event-schema-v1"
EVENT_HASH = "b" * 64
SOURCE_SNAPSHOT_HASH = "c" * 64
PLAN_HASH = "d" * 64
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


@dataclass(frozen=True, slots=True)
class _FillFixture:
    """Keep the independent typed source, economics, and receipt snapshot together."""

    event: LocalSimulatedFillEventV1
    encoded_snapshot: EncodedOrderReservationFillSnapshot
    fee_policy: SimulatedFeePolicyV2
    intent: SimulatedTradeIntent


def _fee_policy() -> SimulatedFeePolicyV2:
    """Build the exact existing FeeV2 fixture used by the snapshot codec tests."""

    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        min_commission=Decimal("5"),
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=FeeApplicability.APPLIES,
            slippage=FeeApplicability.APPLIES,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="codec-test-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=AS_OF - timedelta(days=1),
        transaction_cases=cases,
    )


def _fill_fixture() -> _FillFixture:
    """Build one valid fill snapshot using the frozen 667 Domain and codec contracts."""

    intent = SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key="codec-order-001",
        side=SimulatedTradeSide.BUY,
        security_id="SH.CODEC.SECURITY",
        asset_code="600000.SH",
        asset_name="codec fixture",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        reason="V4 binding codec test",
        signal_id=None,
    )
    fee_policy = _fee_policy()
    request = OrderReservationRequest(
        account_id=intent.account_id,
        security_id=intent.security_id,
        idempotency_key=intent.idempotency_key,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.price,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        fee_budget=Decimal("20.00"),
    )
    book = OrderReservationBook(
        account_id=intent.account_id,
        security_id=intent.security_id,
        book_cash=Decimal("100000.00"),
        withdrawable_cash=None,
        sellable_shares=Decimal("1000.000000"),
        reservations=(),
    )
    reservation = reserve_order(book, request, fee_policy, reserved_at=AS_OF).reservation
    prior = OrderReservationFillAccrual(
        fill_count=0,
        cumulative_quantity=ZERO_SHARES,
        cumulative_gross=ZERO_MONEY,
        cumulative_fees=ZERO_FEES,
    )
    event = LocalSimulatedFillEventV1(
        source_namespace=SOURCE_NAMESPACE,
        source_version=SOURCE_VERSION,
        source_event_id="matcher-event-0001",
        event_payload_hash=EVENT_HASH,
        source_snapshot_id="matcher-snapshot-001",
        source_snapshot_hash=SOURCE_SNAPSHOT_HASH,
        reservation_id=41,
        account_id=intent.account_id,
        user_id=intent.user_id,
        order_idempotency_key=intent.idempotency_key,
        intent_payload_hash=intent.request_payload_hash,
        reservation_request_hash=reservation.identity.request_payload_hash,
        plan_snapshot_hash=PLAN_HASH,
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        side=intent.side,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        occurred_at=AS_OF,
        source_observed_at=AS_OF,
        source_available_at=AS_OF,
        recorded_at=AS_OF,
    )
    economics = prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=event.source_event_id,
            intent=intent,
            stored_intent_payload_hash=intent.request_payload_hash,
            reservation=reservation,
            fee_policy=fee_policy,
            fill_occurred_at=event.occurred_at,
            quantity=event.quantity,
            price=event.price,
            prior=prior,
            close_order=False,
        )
    )
    encoded = encode_order_reservation_fill_snapshot(
        event=event,
        economics=economics,
        reservation_id=event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
    )
    return _FillFixture(event, encoded, fee_policy, intent)


def _calendar(
    *,
    published_at: datetime = AS_OF - timedelta(minutes=5),
    publication_recorded_at: datetime = AS_OF - timedelta(minutes=4),
    reference_valid_from: datetime = AS_OF - timedelta(days=1),
    reference_valid_until: datetime = AS_OF + timedelta(days=20),
    source_published_at: datetime | None = AS_OF - timedelta(minutes=30),
) -> ExecutionCalendarEvidence:
    """Build exact explicit days and source clocks without weekday inference."""

    coverage_start = date(2026, 10, 15)
    coverage_end = date(2026, 10, 23)
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
        days=tuple(day_rows),
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=AS_OF - timedelta(minutes=10),
        source_published_at=source_published_at,
    )
    publication = CalendarPublicationReference(
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
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _proof(
    *,
    event_at: datetime = AS_OF,
    read_cutoff: datetime = AS_OF,
    evidence: ExecutionCalendarEvidence | None = None,
    lag: int = 1,
) -> OrderFillSettlementProof:
    """Derive the claims through the same explicit calendar algorithms as 688."""

    calendar = evidence or _calendar()
    session = calendar.current_open_session(event_at)
    return OrderFillSettlementProof(
        calendar_evidence=calendar,
        calendar_read_cutoff=read_cutoff,
        fill_occurred_at=event_at,
        settlement_exchange="SH",
        fill_market_session=session,
        settlement_lag_sessions=lag,
        expected_release_session=calendar.release_session(session, lag),
    )


def _json_object(value: object) -> dict[str, object]:
    """Narrow one generated JSON object for a precise tampering scenario."""

    if type(value) is not dict:
        raise AssertionError("expected a JSON object")
    return cast(dict[str, object], value)


def _clone_payload(value: dict[str, object]) -> dict[str, object]:
    """Copy a JSON payload without changing its scalar representations."""

    return cast(dict[str, object], json.loads(json.dumps(value, ensure_ascii=False)))


def _canonical_hash(value: dict[str, object]) -> str:
    """Apply the Domain V4 envelope canonical JSON hash recipe."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _wire_utc(value: datetime) -> str:
    """Serialize one aware fixture instant in the proof's UTC microsecond form."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _reseal(payload: dict[str, object]) -> str:
    """Recompute inner proof and outer plan seals for adversarial revalidation."""

    proof_payload = _json_object(payload["fill_settlement_proof"])
    payload["fill_settlement_proof_hash"] = _canonical_hash(proof_payload)
    return _canonical_hash(payload)


def _replace_publication_payload(
    binding_payload: dict[str, object],
    publication: CalendarPublicationReference | None,
) -> None:
    """Replace formal publication data while recomputing its typed evidence hash."""

    proof_payload = _json_object(binding_payload["fill_settlement_proof"])
    calendar_payload = _json_object(proof_payload["calendar_evidence"])
    original_evidence = _calendar()
    replacement_evidence = ExecutionCalendarEvidence(
        snapshot=original_evidence.snapshot,
        publication=publication,
    )
    calendar_payload["evidence_hash"] = replacement_evidence.evidence_hash
    if publication is None:
        calendar_payload["publication"] = None
    else:
        publication_payload = publication.to_payload()
        for field_name in (
            "published_at",
            "recorded_at",
            "reference_valid_from",
            "reference_valid_until",
        ):
            publication_payload[field_name] = _wire_utc(
                cast(datetime, getattr(publication, field_name))
            )
        calendar_payload["publication"] = publication_payload


def test_calendar_proof_codec_round_trip_recomputes_complete_evidence() -> None:
    """Round-trip retains every raw/source clock and validates the proof hash."""

    proof = _proof()

    encoded = encode_order_fill_settlement_proof(proof)
    decoded = decode_order_fill_settlement_proof(encoded.to_payload())

    assert decoded == proof
    assert encoded.proof_hash == proof.proof_hash
    payload = decoded.to_payload()
    evidence_payload = _json_object(payload["calendar_evidence"])
    snapshot_payload = _json_object(evidence_payload["snapshot"])
    raw_payload = _json_object(snapshot_payload["raw_reference"])
    publication_payload = _json_object(evidence_payload["publication"])
    assert raw_payload["body_sha256"] == raw_payload["retained_content_sha256"]
    assert raw_payload["response_time_semantics"] == "local_response_body_completion"
    assert raw_payload["response_completed_at"] == _wire_utc(AS_OF - timedelta(minutes=20))
    assert snapshot_payload["first_seen_at"] == _wire_utc(AS_OF - timedelta(minutes=20))
    assert snapshot_payload["recorded_at"] == _wire_utc(AS_OF - timedelta(minutes=10))
    assert publication_payload["published_at"] == _wire_utc(AS_OF - timedelta(minutes=5))


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("calendar_read_cutoff",), "2026-10-16T02:00:00+00:00"),
        (("calendar_read_cutoff",), "2026-10-16T02:00:00.000000+00:00"),
        (("settlement_lag_sessions",), True),
        (("fill_market_session",), "2026-10-17"),
        (("expected_release_session",), "2026-10-20"),
    ),
)
def test_calendar_codec_rejects_noncanonical_or_invalid_claims(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    """The decoder requires exact wire forms and revalidates all settlement claims."""

    payload = _proof().to_payload()
    target = payload
    for key in path[:-1]:
        target = _json_object(target[key])
    target[path[-1]] = replacement

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_proof(payload)


def test_calendar_codec_rejects_missing_and_unknown_nested_evidence_fields() -> None:
    """Raw response identity and exact nested key sets are mandatory."""

    missing = _clone_payload(_proof().to_payload())
    calendar_payload = _json_object(missing["calendar_evidence"])
    snapshot_payload = _json_object(calendar_payload["snapshot"])
    snapshot_payload.pop("raw_reference")
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_proof(missing)

    extra = _clone_payload(_proof().to_payload())
    calendar_payload = _json_object(extra["calendar_evidence"])
    calendar_payload["unrecognized_clock"] = _wire_utc(AS_OF)
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_proof(extra)


def test_binding_round_trip_preserves_distinct_receipt_and_calendar_seals() -> None:
    """V4 binds a verified 667 receipt snapshot and a separate calendar proof."""

    fixture = _fill_fixture()
    proof = _proof(event_at=fixture.event.occurred_at)

    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=proof,
    )
    payload = encoded.to_payload()
    decoded = decode_order_reservation_fill_binding(
        payload=payload,
        settlement_plan_binding_hash=encoded.settlement_plan_binding_hash,
        snapshot=fixture.encoded_snapshot,
    )

    assert type(decoded) is OrderReservationFillBindingV4
    assert decoded.to_payload() == payload
    assert payload["schema"] == "simulated-order-fill-binding.v4"
    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    assert (
        payload["source_event_payload_hash"] == fixture.encoded_snapshot.source_event_payload_hash
    )
    assert (
        payload["source_event_snapshot_hash"] == fixture.encoded_snapshot.source_event_snapshot_hash
    )
    assert payload["economic_request_hash"] == fixture.encoded_snapshot.economic_request_hash
    assert payload["economics_snapshot_hash"] == fixture.encoded_snapshot.economics_snapshot_hash
    assert encoded.settlement_plan_binding_hash != fixture.encoded_snapshot.receipt_hash
    proof_payload = _json_object(payload["fill_settlement_proof"])
    assert payload["fill_settlement_proof_hash"] == _canonical_hash(proof_payload)


def test_same_receipt_with_a_different_valid_calendar_proof_changes_binding_only() -> None:
    """The outer V4 seal changes with read evidence while receipt identity remains exact."""

    fixture = _fill_fixture()
    first_proof = _proof(event_at=fixture.event.occurred_at)
    second_proof = _proof(
        event_at=fixture.event.occurred_at,
        read_cutoff=AS_OF + timedelta(minutes=1),
    )

    first = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=first_proof,
    )
    second = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=second_proof,
    )

    assert fixture.encoded_snapshot.receipt_hash == first.to_payload()["receipt_hash"]
    assert first.to_payload()["receipt_hash"] == second.to_payload()["receipt_hash"]
    assert (
        first.to_payload()["source_event_snapshot_hash"]
        == second.to_payload()["source_event_snapshot_hash"]
    )
    assert (
        first.to_payload()["economics_snapshot_hash"]
        == second.to_payload()["economics_snapshot_hash"]
    )
    assert first.settlement_plan_binding_hash != second.settlement_plan_binding_hash


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("reservation_id", 42),
        ("intent_payload_hash", "a" * 64),
        ("reservation_request_hash", "b" * 64),
        ("plan_snapshot_hash", "c" * 64),
        ("fee_policy_hash", "e" * 64),
        ("source_namespace", "other-local-matcher"),
        ("source_version", "event-schema-v2"),
        ("source_event_id", "matcher-event-0002"),
        ("fill_sequence", 2),
        ("side", "sell"),
        ("source_event_payload_hash", "f" * 64),
        ("source_event_snapshot_hash", "0" * 64),
        ("economic_request_hash", "1" * 64),
        ("economics_snapshot_hash", "2" * 64),
        ("receipt_hash", "3" * 64),
    ),
)
def test_each_individually_valid_binding_field_must_match_verified_receipt(
    field_name: str,
    value: object,
) -> None:
    """Resealing a changed locator or digest cannot detach it from the 667 receipt."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    payload[field_name] = value
    supplied_hash = _canonical_hash(payload)

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("reservation_id", True),
        ("fill_sequence", True),
        ("side", True),
        ("fill_settlement_proof_hash", None),
    ),
)
def test_binding_rejects_bool_as_integer_and_wrong_json_types(
    field_name: str,
    value: object,
) -> None:
    """JSON booleans and nulls are not accepted as positive IDs, sequence, or digest."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    payload[field_name] = value
    supplied_hash = _canonical_hash(payload)

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


@pytest.mark.parametrize("mutation", ("missing", "unknown"))
def test_binding_requires_exact_complete_schema_even_after_outer_reseal(
    mutation: str,
) -> None:
    """The JSONField boundary rejects partial and future-version envelope keys."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    if mutation == "missing":
        payload.pop("source_event_snapshot_hash")
    else:
        payload["unrecognized_fill_metadata"] = "not-a-v4-field"

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=_canonical_hash(payload),
            snapshot=fixture.encoded_snapshot,
        )


def test_binding_decoder_rejects_stringified_or_noncanonical_json_input() -> None:
    """A JSONField boundary accepts an object, not text or a duplicate-key string."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = encoded.to_payload()
    stringified = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=stringified,
            settlement_plan_binding_hash=encoded.settlement_plan_binding_hash,
            snapshot=fixture.encoded_snapshot,
        )

    duplicate_key_json = '{"schema":"simulated-order-fill-binding.v4","schema":"other"}'
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=duplicate_key_json,
            settlement_plan_binding_hash=encoded.settlement_plan_binding_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_rehashed_proof_for_a_different_fill_instant_cannot_bind_original_receipt() -> None:
    """A self-consistent proof for another event time cannot replace receipt occurred_at."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    proof_payload = _json_object(payload["fill_settlement_proof"])
    proof_payload["fill_occurred_at"] = _wire_utc(AS_OF + timedelta(minutes=1))
    proof_payload["calendar_read_cutoff"] = _wire_utc(AS_OF + timedelta(minutes=2))
    supplied_hash = _reseal(payload)

    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


@pytest.mark.parametrize(
    ("changed_field", "value"),
    (
        ("calendar_read_cutoff", "2026-10-16T02:00:00+00:00"),
        ("calendar_read_cutoff", "2026-10-16T02:00:00.000000+00:00"),
        ("settlement_lag_sessions", True),
        ("fill_market_session", "2026-10-17"),
        ("expected_release_session", "2026-10-20"),
    ),
)
def test_binding_rejects_noncanonical_or_invalid_inner_proof_after_resealing(
    changed_field: str,
    value: object,
) -> None:
    """Both inner proof and outer binding hashes are recomputed before strict checks."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    proof_payload = _json_object(payload["fill_settlement_proof"])
    proof_payload[changed_field] = value
    supplied_hash = _reseal(payload)

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_future_publication_at_fill_time_is_rejected_after_consistent_evidence_reseal() -> None:
    """Recomputing local hashes cannot make a publication known before it was published."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(
            event_at=fixture.event.occurred_at,
            read_cutoff=AS_OF + timedelta(hours=1),
        ),
    )
    payload = _clone_payload(encoded.to_payload())
    publication = _calendar().publication
    assert publication is not None
    future_publication = replace(
        publication,
        published_at=AS_OF + timedelta(minutes=5),
        recorded_at=AS_OF + timedelta(minutes=6),
    )
    _replace_publication_payload(payload, future_publication)
    supplied_hash = _reseal(payload)

    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    with pytest.raises(CalendarEvidenceValidationError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_missing_formal_publication_is_rejected_even_with_recomputed_evidence_hash() -> None:
    """A valid raw snapshot without a formal publication cannot authorize settlement."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    _replace_publication_payload(payload, None)
    supplied_hash = _reseal(payload)

    with pytest.raises(CalendarEvidenceValidationError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_raw_calendar_hash_tampering_is_not_hidden_by_receipt_hash() -> None:
    """Raw source identity damage fails the nested proof while the receipt remains unchanged."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    proof_payload = _json_object(payload["fill_settlement_proof"])
    evidence_payload = _json_object(proof_payload["calendar_evidence"])
    snapshot_payload = _json_object(evidence_payload["snapshot"])
    raw_payload = _json_object(snapshot_payload["raw_reference"])
    raw_payload["body_sha256"] = "f" * 64
    supplied_hash = _reseal(payload)

    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    with pytest.raises(CalendarEvidenceValidationError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_calendar_content_hash_tampering_is_rejected_after_all_outer_seals_are_recomputed() -> None:
    """A locally recomputed V4/proof seal cannot replace the Domain snapshot content hash."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    proof_payload = _json_object(payload["fill_settlement_proof"])
    evidence_payload = _json_object(proof_payload["calendar_evidence"])
    snapshot_payload = _json_object(evidence_payload["snapshot"])
    snapshot_payload["content_hash"] = "a" * 64
    supplied_hash = _reseal(payload)

    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    with pytest.raises(CalendarEvidenceValidationError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_stale_inner_hash_rejects_calendar_tampering_without_changing_receipt_identity() -> None:
    """The proof hash detects calendar edits even if an attacker refreshes only the outer seal."""

    fixture = _fill_fixture()
    encoded = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = _clone_payload(encoded.to_payload())
    proof_payload = _json_object(payload["fill_settlement_proof"])
    proof_payload["calendar_read_cutoff"] = _wire_utc(AS_OF + timedelta(minutes=1))
    supplied_outer_hash = _canonical_hash(payload)

    assert payload["receipt_hash"] == fixture.encoded_snapshot.receipt_hash
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=supplied_outer_hash,
            snapshot=fixture.encoded_snapshot,
        )


def test_calendar_decoder_maps_unpaired_surrogate_to_typed_contract_error() -> None:
    payload = _proof().to_payload()
    payload["settlement_exchange"] = "\ud800"

    with pytest.raises(SimulatedSettlementContractError, match="not canonical JSON"):
        decode_order_fill_settlement_proof(payload)


def test_binding_decoder_maps_unpaired_surrogate_to_typed_contract_error() -> None:
    fixture = _fill_fixture()
    binding = encode_order_reservation_fill_binding(
        snapshot=fixture.encoded_snapshot,
        proof=_proof(event_at=fixture.event.occurred_at),
    )
    payload = binding.to_payload()
    payload["source_namespace"] = "\ud800"

    with pytest.raises(SimulatedSettlementContractError, match="not canonical JSON"):
        decode_order_reservation_fill_binding(
            payload=payload,
            settlement_plan_binding_hash=binding.settlement_plan_binding_hash,
            snapshot=fixture.encoded_snapshot,
        )
