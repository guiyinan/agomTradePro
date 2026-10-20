"""Pure canonical snapshot codec contract for a future G2 fill repository.

These tests cover serialization and seals only. They do not authenticate a
matcher, validate a persisted FeeV2 policy, prove an ORM transaction, or create
a Trade/Receipt row.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

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
from apps.simulated_trading.domain.execution_settlement_primitives import (
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
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationRequest,
    reserve_order,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_initial_position_mark_codec import (
    decode_initial_position_mark_evidence,
    encode_initial_position_mark_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    DecodedOrderReservationFillSnapshot,
    EncodedOrderReservationFillSnapshot,
    decode_order_reservation_fill_snapshot,
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


@dataclass(frozen=True, slots=True)
class _Fixture:
    """Bundle exact source and Domain inputs for one codec-only scenario."""

    event: LocalSimulatedFillEventV1
    economics: OrderReservationFillEconomics
    intent: SimulatedTradeIntent
    reservation: OrderReservation
    fee_policy: SimulatedFeePolicyV2


def _fee_policy() -> SimulatedFeePolicyV2:
    """Build one complete frozen FeeV2 policy for the codec fixture."""

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


def _fixture(*, side: SimulatedTradeSide = SimulatedTradeSide.BUY) -> _Fixture:
    """Construct an exact Reservation, event and internally validated economics."""

    intent = SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key="codec-order-001",
        side=side,
        security_id="SH.CODEC.SECURITY",
        asset_code="600000.SH",
        asset_name="codec fixture",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        reason="canonical snapshot codec test",
        signal_id=None,
    )
    policy = _fee_policy()
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
        fee_budget=(Decimal("20.00") if intent.side is SimulatedTradeSide.BUY else None),
    )
    book = OrderReservationBook(
        account_id=intent.account_id,
        security_id=intent.security_id,
        book_cash=Decimal("100000.00"),
        withdrawable_cash=None,
        sellable_shares=Decimal("1000.000000"),
        reservations=(),
    )
    reservation = reserve_order(book, request, policy, reserved_at=AS_OF).reservation
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
            fee_policy=policy,
            fill_occurred_at=event.occurred_at,
            quantity=event.quantity,
            price=event.price,
            prior=prior,
            close_order=False,
        )
    )
    return _Fixture(event, economics, intent, reservation, policy)


def _encode(fixture: _Fixture) -> EncodedOrderReservationFillSnapshot:
    """Encode one fixture using its explicit parent key and cumulative sequence."""

    return encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
    )


def _json_object(value: str) -> dict[str, object]:
    """Decode one JSON object for deliberate boundary-tampering tests."""

    decoded: object = json.loads(value)
    if type(decoded) is not dict:
        raise AssertionError("expected a JSON object")
    return cast(dict[str, object], decoded)


def _canonical_json(value: dict[str, object]) -> str:
    """Serialize a tampered test mapping with the codec's canonical JSON shape."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _nested_object(value: dict[str, object], key: str) -> dict[str, object]:
    """Return one nested object after asserting the JSON value shape."""

    nested: object = value[key]
    if type(nested) is not dict:
        raise AssertionError(f"{key} is not an object")
    return cast(dict[str, object], nested)


def _reseal_noncanonical_zero_economics(
    *,
    fixture: _Fixture,
    encoded: EncodedOrderReservationFillSnapshot,
    path: tuple[str, ...],
    wire_value: str,
) -> tuple[str, str, EncodedOrderReservationFillSnapshot]:
    """Build canonical and alternate wire JSON plus a valid independent receipt seal."""

    canonical_payload = _json_object(encoded.economics_snapshot_json)
    wire_payload = _json_object(encoded.economics_snapshot_json)
    canonical_parent = canonical_payload
    wire_parent = wire_payload
    for part in path[:-1]:
        canonical_parent = _nested_object(canonical_parent, part)
        wire_parent = _nested_object(wire_parent, part)
    canonical_parent[path[-1]] = "0"
    wire_parent[path[-1]] = wire_value
    canonical_json = _canonical_json(canonical_payload)
    wire_json = _canonical_json(wire_payload)

    restored_payload = _json_object(wire_json)
    restored_parent = restored_payload
    for part in path[:-1]:
        restored_parent = _nested_object(restored_parent, part)
    restored_parent[path[-1]] = "0"
    assert restored_payload == canonical_payload
    assert wire_json != canonical_json

    economics_snapshot_hash = hashlib.sha256(wire_json.encode("utf-8")).hexdigest()
    receipt_payload: dict[str, object] = {
        "schema": "simulated-order-reservation-fill-receipt.v1",
        "reservation_id": encoded.reservation_id,
        "fill_sequence": encoded.fill_sequence,
        "source_namespace": fixture.event.source_namespace,
        "source_version": fixture.event.source_version,
        "source_event_id": fixture.event.source_event_id,
        "source_event_payload_hash": fixture.event.event_payload_hash,
        "source_event_snapshot_hash": encoded.source_event_snapshot_hash,
        "economic_request_hash": fixture.economics.payload_hash,
        "economics_snapshot_hash": economics_snapshot_hash,
        "intent_payload_hash": fixture.economics.intent_payload_hash,
        "fee_policy_hash": fixture.economics.fee_policy_hash,
        "plan_snapshot_hash": encoded.plan_snapshot_hash,
        "account_id": fixture.event.account_id,
        "user_id": fixture.event.user_id,
        "order_idempotency_key": fixture.event.order_idempotency_key,
        "security_id": fixture.event.security_id,
        "asset_code": fixture.event.asset_code,
        "side": fixture.event.side.value,
    }
    receipt_json = _canonical_json(receipt_payload)
    receipt_hash = hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
    resealed = replace(
        encoded,
        economics_snapshot_json=wire_json,
        economics_snapshot_hash=economics_snapshot_hash,
        receipt_hash=receipt_hash,
    )
    return canonical_json, wire_json, resealed


def _alternate_accrual(fixture: _Fixture) -> OrderReservationFillEconomics:
    """Make a different but fully self-consistent economics snapshot."""

    intent = fixture.intent
    previous_gross = Decimal("20.00")
    previous_fees = fixture.fee_policy.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=previous_gross,
        as_of=AS_OF,
    )
    previous = OrderReservationFillAccrual(
        fill_count=1,
        cumulative_quantity=Decimal("2.000000"),
        cumulative_gross=previous_gross,
        cumulative_fees=previous_fees,
    )
    filled_reservation = fixture.reservation.apply_fill(
        filled_quantity=previous.cumulative_quantity,
        cash_consumed=previous_gross + previous_fees.total_fee,
    )
    return prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=fixture.event.source_event_id,
            intent=intent,
            stored_intent_payload_hash=intent.request_payload_hash,
            reservation=filled_reservation,
            fee_policy=fixture.fee_policy,
            fill_occurred_at=fixture.event.occurred_at,
            quantity=fixture.event.quantity,
            price=fixture.event.price,
            prior=previous,
            close_order=False,
        )
    )


def _fixture_with_zero_prior(
    fixture: _Fixture,
    *,
    zero_quantity: Decimal,
    zero_money: Decimal,
) -> _Fixture:
    """Rebuild equivalent economics with explicit zero scale/sign variants."""

    zero_fees = TradeFeeBreakdown(
        commission=zero_money,
        transfer_fee=zero_money,
        stamp_duty=zero_money,
        slippage=zero_money,
        total_fee=zero_money,
    )
    prior = OrderReservationFillAccrual(
        fill_count=0,
        cumulative_quantity=zero_quantity,
        cumulative_gross=zero_money,
        cumulative_fees=zero_fees,
    )
    economics = prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=fixture.event.source_event_id,
            intent=fixture.intent,
            stored_intent_payload_hash=fixture.intent.request_payload_hash,
            reservation=fixture.reservation,
            fee_policy=fixture.fee_policy,
            fill_occurred_at=fixture.event.occurred_at,
            quantity=fixture.event.quantity,
            price=fixture.event.price,
            prior=prior,
            close_order=False,
        )
    )
    return replace(fixture, economics=economics)


def test_round_trip_preserves_exact_typed_event_economics_and_utc_instants() -> None:
    """Round-trip retains financial values and normalizes aware instants to UTC."""

    fixture = _fixture()
    encoded = _encode(fixture)

    decoded = decode_order_reservation_fill_snapshot(encoded)

    assert type(decoded) is DecodedOrderReservationFillSnapshot
    assert decoded.event == fixture.event
    assert decoded.economics == fixture.economics
    assert decoded.economics.quantity == Decimal("10.000000")
    assert decoded.economics.price == Decimal("10.0000")
    assert decoded.economics.gross_amount == Decimal("100.00")
    assert decoded.event.occurred_at == AS_OF
    assert decoded.event.occurred_at.utcoffset() == timedelta(0)


def test_four_hashes_seal_distinct_layers_and_receipt_needs_no_future_primary_key() -> None:
    """External, typed-event, Domain-request, economics and receipt hashes differ."""

    fixture = _fixture()
    encoded = _encode(fixture)
    repeated = _encode(fixture)

    assert encoded.source_event_payload_hash == fixture.event.event_payload_hash
    assert encoded.source_event_snapshot_hash != encoded.source_event_payload_hash
    assert encoded.economic_request_hash == fixture.economics.payload_hash
    assert encoded.economics_snapshot_hash != encoded.economic_request_hash
    assert encoded.receipt_hash not in {
        encoded.source_event_payload_hash,
        encoded.source_event_snapshot_hash,
        encoded.economic_request_hash,
        encoded.economics_snapshot_hash,
    }
    assert repeated.receipt_hash == encoded.receipt_hash
    assert encoded.reservation_id == 41
    assert encoded.fill_sequence == fixture.economics.cumulative_state.fill_count
    assert not hasattr(encoded, "trade_id")
    assert not hasattr(encoded, "receipt_id")


def test_self_consistent_prior_and_fee_rewrite_fails_the_old_economics_seal() -> None:
    """Mutable accrual tampering cannot pass using only the Domain request hash."""

    fixture = _fixture()
    encoded = _encode(fixture)
    altered_economics = _alternate_accrual(fixture)
    altered = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=altered_economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=altered_economics.cumulative_state.fill_count,
        plan_snapshot_hash=PLAN_HASH,
    )

    assert altered_economics.payload_hash == fixture.economics.payload_hash
    assert altered.economics_snapshot_hash != encoded.economics_snapshot_hash
    tampered = replace(
        encoded,
        fill_sequence=altered.fill_sequence,
        economics_snapshot_json=altered.economics_snapshot_json,
    )
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


@pytest.mark.parametrize(
    "changed_field",
    ("source_namespace", "source_version", "source_observed_at"),
)
def test_source_snapshot_seal_rejects_relabelled_event_with_same_external_hash(
    changed_field: str,
) -> None:
    """Namespace, schema or clock changes fail the local seal despite raw hash reuse."""

    fixture = _fixture()
    encoded = _encode(fixture)
    changed_value: object
    if changed_field == "source_observed_at":
        changed_value = AS_OF + timedelta(seconds=1)
    elif changed_field == "source_namespace":
        changed_value = "other-local-matcher"
    else:
        changed_value = "event-schema-v2"
    changed_event = replace(fixture.event, **{changed_field: changed_value})
    changed_snapshot = encode_order_reservation_fill_snapshot(
        event=changed_event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
    )

    assert changed_event.event_payload_hash == fixture.event.event_payload_hash
    assert changed_snapshot.source_event_snapshot_hash != encoded.source_event_snapshot_hash
    tampered = replace(
        encoded,
        source_event_snapshot_json=changed_snapshot.source_event_snapshot_json,
    )
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("reservation_id", 42), ("fill_sequence", 2)),
)
def test_parent_locator_and_explicit_sequence_are_cross_checked(
    field_name: str, value: int
) -> None:
    """Receipt metadata cannot drift from the source and cumulative economics."""

    encoded = _encode(_fixture())
    tampered = replace(encoded, **{field_name: value})

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


@pytest.mark.parametrize("mutation", ("missing", "unknown"))
def test_json_field_set_is_exact_and_unknown_or_missing_fields_are_rejected(
    mutation: str,
) -> None:
    """The JSON boundary never silently ignores schema drift or absent evidence."""

    encoded = _encode(_fixture())
    event_payload = _json_object(encoded.source_event_snapshot_json)
    if mutation == "missing":
        event_payload.pop("recorded_at")
    else:
        event_payload["unrecognized_clock"] = "2026-10-16T02:00:00Z"
    tampered = replace(
        encoded,
        source_event_snapshot_json=_canonical_json(event_payload),
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


@pytest.mark.parametrize(
    ("snapshot_field", "nested_key", "value"),
    (
        ("economics_snapshot_json", "commission", None),
        ("source_event_snapshot_json", "source_observed_at", None),
    ),
)
def test_unknown_none_is_not_coerced_to_zero_or_a_wall_clock(
    snapshot_field: str, nested_key: str, value: object
) -> None:
    """Unknown fee and source-clock evidence remains invalid, never defaulted."""

    encoded = _encode(_fixture())
    if snapshot_field == "economics_snapshot_json":
        payload = _json_object(encoded.economics_snapshot_json)
        fees = _nested_object(payload, "incremental_fees")
        fees[nested_key] = value
        snapshot_json = _canonical_json(payload)
    else:
        payload = _json_object(encoded.source_event_snapshot_json)
        payload[nested_key] = value
        snapshot_json = _canonical_json(payload)
    tampered = replace(encoded, **{snapshot_field: snapshot_json})

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


def test_noncanonical_decimal_text_is_rejected_without_rounding() -> None:
    """Exponent spellings are not silently normalized into accepted amounts."""

    encoded = _encode(_fixture())
    payload = _json_object(encoded.economics_snapshot_json)
    payload["quantity"] = "1E1"
    tampered = replace(
        encoded,
        economics_snapshot_json=_canonical_json(payload),
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


def test_metadata_hashes_are_recomputed_from_the_complete_typed_snapshots() -> None:
    """Outer metadata cannot replace the independently recomputed source/request hashes."""

    encoded = _encode(_fixture())
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(replace(encoded, source_event_payload_hash="e" * 64))
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(replace(encoded, economic_request_hash="e" * 64))
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(replace(encoded, receipt_hash="e" * 64))


def test_unknown_event_kind_is_logged_safely_and_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """UNKNOWN cannot be serialized as a real fill and logs no event identifiers."""

    fixture = _fixture()
    unknown = replace(
        fixture.event,
        event_kind=LocalSimulatedFillEventKind.UNKNOWN,
    )
    logger_name = "apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        with pytest.raises(SimulatedSettlementContractError):
            encode_order_reservation_fill_snapshot(
                event=unknown,
                economics=fixture.economics,
                reservation_id=unknown.reservation_id,
                fill_sequence=1,
                plan_snapshot_hash=PLAN_HASH,
            )

    warnings = [record for record in caplog.records if record.name == logger_name]
    assert len(warnings) == 1
    assert getattr(warnings[0], "code", None) == "SIMULATED_FILL_EVENT_KIND_UNKNOWN"
    assert unknown.source_event_id not in warnings[0].getMessage()
    assert EVENT_HASH not in warnings[0].getMessage()


def test_positive_and_negative_zero_scales_have_identical_snapshot_hashes() -> None:
    """Equal zero representations produce one canonical wire snapshot and receipt."""

    fixture = _fixture()
    positive_zero = _fixture_with_zero_prior(
        fixture,
        zero_quantity=Decimal("0"),
        zero_money=Decimal("0"),
    )
    negative_zero = _fixture_with_zero_prior(
        fixture,
        zero_quantity=Decimal("-0.000000"),
        zero_money=Decimal("-0.00"),
    )
    original_snapshot = _encode(fixture)
    positive_snapshot = _encode(positive_zero)
    negative_snapshot = _encode(negative_zero)

    assert positive_zero.economics.payload_hash == fixture.economics.payload_hash
    assert negative_zero.economics.payload_hash == fixture.economics.payload_hash
    assert (
        positive_snapshot.source_event_snapshot_hash == original_snapshot.source_event_snapshot_hash
    )
    assert (
        negative_snapshot.source_event_snapshot_hash == original_snapshot.source_event_snapshot_hash
    )
    assert positive_snapshot.economics_snapshot_json == original_snapshot.economics_snapshot_json
    assert negative_snapshot.economics_snapshot_json == original_snapshot.economics_snapshot_json
    assert positive_snapshot.economics_snapshot_hash == original_snapshot.economics_snapshot_hash
    assert negative_snapshot.economics_snapshot_hash == original_snapshot.economics_snapshot_hash
    assert positive_snapshot.receipt_hash == original_snapshot.receipt_hash
    assert negative_snapshot.receipt_hash == original_snapshot.receipt_hash
    prior = _nested_object(_json_object(negative_snapshot.economics_snapshot_json), "prior")
    assert prior["cumulative_quantity"] == "0"
    assert prior["cumulative_gross"] == "0"


@pytest.mark.parametrize(
    ("path", "wire_value"),
    (
        (("prior", "cumulative_quantity"), "-0.000000"),
        (("prior", "cumulative_gross"), "0.00"),
        (("prior", "cumulative_fees", "commission"), "-0.00"),
    ),
)
def test_noncanonical_zero_wire_spelling_is_rejected(
    path: tuple[str, ...], wire_value: str
) -> None:
    """A validly resealed alternate zero spelling fails canonical reserialization."""

    fixture = _fixture()
    encoded = _encode(fixture)
    canonical_json, wire_json, resealed = _reseal_noncanonical_zero_economics(
        fixture=fixture,
        encoded=encoded,
        path=path,
        wire_value=wire_value,
    )
    event_json_hash = hashlib.sha256(encoded.source_event_snapshot_json.encode("utf-8")).hexdigest()
    economics_hash = hashlib.sha256(wire_json.encode("utf-8")).hexdigest()

    assert canonical_json != wire_json
    assert resealed.source_event_payload_hash == fixture.event.event_payload_hash
    assert resealed.source_event_snapshot_hash == event_json_hash
    assert resealed.economic_request_hash == fixture.economics.payload_hash
    assert resealed.economics_snapshot_hash == economics_hash
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(resealed)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("account_id", 8),
        ("user_id", 12),
        ("order_idempotency_key", "other-order"),
        ("intent_payload_hash", "e" * 64),
        ("reservation_request_hash", "e" * 64),
        ("security_id", "SH.OTHER.SECURITY"),
        ("asset_code", "601000.SH"),
        ("side", SimulatedTradeSide.SELL),
        ("quantity", Decimal("11.000000")),
        ("price", Decimal("9.0000")),
        ("occurred_at", AS_OF + timedelta(seconds=1)),
        ("event_kind", LocalSimulatedFillEventKind.FINAL_FILL),
        ("plan_snapshot_hash", "e" * 64),
    ),
)
def test_individually_valid_event_fields_must_match_economics(
    field_name: str, value: object
) -> None:
    """A valid event cannot be paired with economics for another owner/order/fill."""

    fixture = _fixture()
    mismatched_event = replace(fixture.event, **{field_name: value})

    with pytest.raises(SimulatedSettlementContractError):
        encode_order_reservation_fill_snapshot(
            event=mismatched_event,
            economics=fixture.economics,
            reservation_id=mismatched_event.reservation_id,
            fill_sequence=1,
            plan_snapshot_hash=PLAN_HASH,
        )


def _initial_position_mark(fixture: _Fixture) -> InitialPositionMarkProof:
    """Build an exact source-bound mark after the fixture's fill instant."""

    return InitialPositionMarkProof(
        security_id=fixture.intent.security_id,
        asset_code=fixture.intent.asset_code,
        asset_type=fixture.intent.asset_type,
        market=fixture.intent.market,
        board=fixture.intent.board,
        price=Decimal("10.1234"),
        source_observed_at=AS_OF,
        source_available_at=None,
        read_at=AS_OF + timedelta(minutes=1),
        publication_as_of=AS_OF + timedelta(seconds=5),
        published_at=AS_OF + timedelta(seconds=10),
        valid_until=AS_OF + timedelta(minutes=10),
        freshness_window_seconds=600,
        source_identity="fixture-market-source",
        source_record_id="mark-row-001",
        source_content_hash="a" * 64,
        publication_id="mark-publication-001",
        publication_hash="b" * 64,
        policy_identity="mark-policy-v1",
        policy_content_hash="c" * 64,
    )


def test_legacy_v1_defaults_and_receipt_hash_remain_unchanged() -> None:
    """A call without a mark retains the exact legacy v1 receipt envelope."""

    fixture = _fixture()
    encoded = _encode(fixture)
    v1_receipt_payload: dict[str, object] = {
        "schema": "simulated-order-reservation-fill-receipt.v1",
        "reservation_id": encoded.reservation_id,
        "fill_sequence": encoded.fill_sequence,
        "source_namespace": fixture.event.source_namespace,
        "source_version": fixture.event.source_version,
        "source_event_id": fixture.event.source_event_id,
        "source_event_payload_hash": encoded.source_event_payload_hash,
        "source_event_snapshot_hash": encoded.source_event_snapshot_hash,
        "economic_request_hash": encoded.economic_request_hash,
        "economics_snapshot_hash": encoded.economics_snapshot_hash,
        "intent_payload_hash": fixture.economics.intent_payload_hash,
        "fee_policy_hash": fixture.economics.fee_policy_hash,
        "plan_snapshot_hash": encoded.plan_snapshot_hash,
        "account_id": fixture.event.account_id,
        "user_id": fixture.event.user_id,
        "order_idempotency_key": fixture.event.order_idempotency_key,
        "security_id": fixture.event.security_id,
        "asset_code": fixture.event.asset_code,
        "side": fixture.event.side.value,
    }

    assert encoded.receipt_version == 1
    assert encoded.initial_position_mark_evidence_json is None
    assert (
        encoded.receipt_hash
        == hashlib.sha256(_canonical_json(v1_receipt_payload).encode("utf-8")).hexdigest()
    )
    assert (
        encoded.source_event_snapshot_hash
        == hashlib.sha256(encoded.source_event_snapshot_json.encode("utf-8")).hexdigest()
    )
    assert (
        encoded.economics_snapshot_hash
        == hashlib.sha256(encoded.economics_snapshot_json.encode("utf-8")).hexdigest()
    )


def test_v2_round_trip_seals_mark_and_allows_nonfirst_buy_sequence() -> None:
    """V2 retains the complete typed mark while V1 fill snapshots stay intact."""

    fixture = _fixture()
    economics = _alternate_accrual(fixture)
    mark = _initial_position_mark(fixture)
    encoded = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=economics.cumulative_state.fill_count,
        plan_snapshot_hash=PLAN_HASH,
        initial_position_mark=mark,
    )

    decoded = decode_order_reservation_fill_snapshot(encoded)

    assert encoded.receipt_version == 2
    assert encoded.initial_position_mark_evidence_json == _canonical_json(mark.to_payload())
    assert decoded.receipt_version == 2
    assert decoded.initial_position_mark_evidence == mark
    assert decoded.fill_sequence == 2
    assert decoded.economics == economics
    assert decoded.source_event_snapshot_hash == encoded.source_event_snapshot_hash
    assert decoded.economics_snapshot_hash == encoded.economics_snapshot_hash


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("security_id", "another-security"),
        ("asset_code", "000002.SZ"),
        ("asset_type", "fund"),
        ("market", "another-market"),
        ("board", "another-board"),
    ),
)
def test_v2_requires_mark_to_match_all_economics_instrument_fields(
    field_name: str, value: str
) -> None:
    """A valid mark for another instrument cannot bind these fill economics."""

    fixture = _fixture()
    mark = replace(_initial_position_mark(fixture), **{field_name: value})

    with pytest.raises(SimulatedSettlementContractError):
        encode_order_reservation_fill_snapshot(
            event=fixture.event,
            economics=fixture.economics,
            reservation_id=fixture.event.reservation_id,
            fill_sequence=1,
            plan_snapshot_hash=PLAN_HASH,
            initial_position_mark=mark,
        )


def test_v2_is_rejected_for_sell_and_receipt_version_mark_pair_is_exact() -> None:
    """Only BUY accepts V2, and the version cannot disagree with mark presence."""

    fixture = _fixture()
    mark = _initial_position_mark(fixture)
    sell = _fixture(side=SimulatedTradeSide.SELL)
    with pytest.raises(SimulatedSettlementContractError):
        encode_order_reservation_fill_snapshot(
            event=sell.event,
            economics=sell.economics,
            reservation_id=sell.event.reservation_id,
            fill_sequence=1,
            plan_snapshot_hash=PLAN_HASH,
            initial_position_mark=_initial_position_mark(sell),
        )

    legacy = _encode(fixture)
    v2 = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
        initial_position_mark=mark,
    )
    with pytest.raises(SimulatedSettlementContractError):
        replace(legacy, receipt_version=2)
    with pytest.raises(SimulatedSettlementContractError):
        replace(v2, receipt_version=1)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("price", "10.2345"),
        ("source_content_hash", "d" * 64),
        ("publication_hash", "e" * 64),
        ("policy_identity", "another-mark-policy"),
    ),
)
def test_v2_receipt_hash_covers_selected_mark_fields(field_name: str, value: object) -> None:
    """Selected valid mark changes fail against the existing outer receipt seal."""

    fixture = _fixture()
    encoded = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
        initial_position_mark=_initial_position_mark(fixture),
    )
    mark_payload = _json_object(cast(str, encoded.initial_position_mark_evidence_json))
    mark_payload[field_name] = value
    tampered = replace(
        encoded,
        initial_position_mark_evidence_json=_canonical_json(mark_payload),
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


@pytest.mark.parametrize("mutation", ("missing", "unknown"))
def test_v2_mark_json_requires_exact_fields(mutation: str) -> None:
    """Mark wire decoding rejects absent and unrecognized evidence fields."""

    fixture = _fixture()
    encoded = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
        initial_position_mark=_initial_position_mark(fixture),
    )
    mark_payload = _json_object(cast(str, encoded.initial_position_mark_evidence_json))
    if mutation == "missing":
        mark_payload.pop("source_record_id")
    else:
        mark_payload["unrecognized_claim"] = "extra"
    tampered = replace(
        encoded,
        initial_position_mark_evidence_json=_canonical_json(mark_payload),
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(tampered)


def test_v2_outer_receipt_hash_tampering_is_rejected() -> None:
    """Receipt version two remains sealed by its recomputed complete envelope."""

    fixture = _fixture()
    encoded = encode_order_reservation_fill_snapshot(
        event=fixture.event,
        economics=fixture.economics,
        reservation_id=fixture.event.reservation_id,
        fill_sequence=1,
        plan_snapshot_hash=PLAN_HASH,
        initial_position_mark=_initial_position_mark(fixture),
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_reservation_fill_snapshot(replace(encoded, receipt_hash="f" * 64))


def test_v2_mark_read_must_not_precede_durable_event_recording() -> None:
    """A self-valid mark read before event recording cannot be sealed in V2."""

    fixture = _fixture()
    event = replace(fixture.event, recorded_at=AS_OF + timedelta(minutes=8))
    mark = replace(
        _initial_position_mark(fixture),
        source_observed_at=AS_OF + timedelta(minutes=2),
        publication_as_of=AS_OF + timedelta(minutes=2, seconds=30),
        published_at=AS_OF + timedelta(minutes=3),
        read_at=AS_OF + timedelta(minutes=4),
        valid_until=AS_OF + timedelta(minutes=12),
        freshness_window_seconds=600,
    )

    with pytest.raises(SimulatedSettlementContractError):
        encode_order_reservation_fill_snapshot(
            event=event,
            economics=fixture.economics,
            reservation_id=event.reservation_id,
            fill_sequence=1,
            plan_snapshot_hash=PLAN_HASH,
            initial_position_mark=mark,
        )


def test_public_initial_mark_encode_rejects_unpaired_surrogate() -> None:
    """Standalone evidence encoding must reject non-UTF-8 source tokens."""

    fixture = _fixture()
    proof = replace(_initial_position_mark(fixture), source_identity="\ud800")

    with pytest.raises(SimulatedSettlementContractError):
        encode_initial_position_mark_evidence(proof)


def test_public_initial_mark_decode_rejects_unpaired_surrogate() -> None:
    """A canonical payload with a raw surrogate fails proof text validation."""

    fixture = _fixture()
    encoded = encode_initial_position_mark_evidence(_initial_position_mark(fixture))
    payload = json.loads(encoded)
    payload["source_identity"] = "\ud800"
    surrogate_json = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    with pytest.raises(SimulatedSettlementContractError):
        decode_initial_position_mark_evidence(surrogate_json)
