"""Strict single-row receipt/Trade reconciliation tests for G2 storage."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast

import pytest
from django.db import connection, models
from django.test.utils import CaptureQueriesContext

from apps.data_center.domain.exchange_calendar import exchange_calendar_request_scope_hash
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
    simulated_order_fill_trade_key,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_binding_codec import (
    encode_order_reservation_fill_binding,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _create_receipt,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    EncodedOrderReservationFillSnapshot,
    encode_order_reservation_fill_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_ZERO_FEES = TradeFeeBreakdown(
    commission=Decimal("0.00"),
    transfer_fee=Decimal("0.00"),
    stamp_duty=Decimal("0.00"),
    slippage=Decimal("0.00"),
    total_fee=Decimal("0.00"),
)
_EVENT_AT = AS_OF + timedelta(minutes=1)
_READ_CUTOFF = AS_OF + timedelta(minutes=3)


@pytest.fixture
def persisted_receipt_schema(reservation_harness: _Harness) -> Iterator[None]:
    """Create or clear the receipt table after its reservation and ledger parents."""

    del reservation_harness
    with isolated_schema((SimulatedOrderFillReceiptModel,)):
        yield


@dataclass(frozen=True, slots=True)
class _Rows:
    """Keep exact ORM rows, source facts, and encoded snapshot for one reader case."""

    reservation: SimulatedOrderReservationModel
    receipt: SimulatedOrderFillReceiptModel
    trade: SimulatedTradeModel
    event: LocalSimulatedFillEventV1
    economics: OrderReservationFillEconomics
    proof: OrderFillSettlementProof
    encoded_snapshot: EncodedOrderReservationFillSnapshot
    initial_mark: InitialPositionMarkProof | None


def _object(value: object, label: str) -> dict[str, object]:
    """Narrow one test JSON object without accepting arbitrary mapping shapes."""

    if type(value) is not dict:
        raise AssertionError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _calendar_evidence(exchange: str) -> ExecutionCalendarEvidence:
    """Build explicit published sessions for an independently valid fill proof."""

    start = date(2026, 10, 15)
    end = date(2026, 10, 23)
    open_dates = {
        date(2026, 10, 15),
        date(2026, 10, 16),
        date(2026, 10, 19),
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    }
    days: list[ExchangeCalendarDay] = []
    previous_open = date(2026, 10, 14)
    current = start
    while current <= end:
        is_open = current in open_dates
        days.append(ExchangeCalendarDay(exchange, current, is_open, previous_open))
        if is_open:
            previous_open = current
        current += timedelta(days=1)

    response_completed = AS_OF - timedelta(minutes=20)
    raw = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "a" * 64,
        record_digest="sha256:" + "b" * 64,
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(exchange, start, end),
        original_body_retained=True,
        response_completed_at=response_completed,
        provider_name="row-reader-fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange=exchange,
        coverage_start=start,
        coverage_end=end,
        days=tuple(days),
        provider_name="row-reader-fixture-provider",
        raw_reference=raw,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed,
        recorded_at=AS_OF - timedelta(minutes=10),
        source_published_at=AS_OF - timedelta(minutes=30),
    )
    publication = CalendarPublicationReference(
        publication_id="row-reader-calendar-publication-001",
        member_id=snapshot.snapshot_id,
        publication_hash="d" * 64,
        fact_content_hash="e" * 64,
        policy_hash="f" * 64,
        published_at=AS_OF - timedelta(minutes=5),
        recorded_at=AS_OF - timedelta(minutes=4),
        reference_valid_from=AS_OF - timedelta(days=1),
        reference_valid_until=AS_OF + timedelta(days=20),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _initial_mark_for_intent(intent: SimulatedTradeIntent) -> InitialPositionMarkProof:
    """Build a typed apply-time mark fixture bound to one exact intent."""

    observed_at = AS_OF + timedelta(minutes=2)
    return InitialPositionMarkProof(
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        price=Decimal("10.1234"),
        source_observed_at=observed_at,
        source_available_at=observed_at + timedelta(seconds=5),
        read_at=AS_OF + timedelta(minutes=4),
        publication_as_of=observed_at + timedelta(seconds=10),
        published_at=observed_at + timedelta(seconds=20),
        valid_until=observed_at + timedelta(seconds=600),
        freshness_window_seconds=600,
        source_identity="receipt-test-mark-source",
        source_record_id="receipt-test-mark-row-001",
        source_content_hash="a" * 64,
        publication_id="receipt-test-mark-publication-001",
        publication_hash="b" * 64,
        policy_identity="receipt-test-mark-policy-v1",
        policy_content_hash="c" * 64,
    )


def _reader_rows(
    harness: _Harness,
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    proof_exchange: str | None = None,
    proof_lag: int | None = None,
    invalid_fee_delta: bool = False,
    fill_occurred_at: datetime | None = None,
    include_initial_mark: bool = False,
) -> _Rows:
    """Create a real sealed reservation and in-memory ORM receipt/Trade rows."""

    if side is SimulatedTradeSide.SELL:
        _create_position(harness.account)
    intent = _intent_for(harness, side=side, key="fill-row-reader-order")
    if include_initial_mark and side is not SimulatedTradeSide.BUY:
        raise AssertionError("initial-position mark fixture applies only to a BUY")
    initial_mark = _initial_mark_for_intent(intent) if include_initial_mark else None
    fee_budget = Decimal("20.00") if side is SimulatedTradeSide.BUY else None
    harness.reserve.execute(intent, fee_budget=fee_budget, as_of=AS_OF)
    reservation = SimulatedOrderReservationModel.objects.get(
        account=harness.account,
        idempotency_key=intent.idempotency_key,
    )
    selected_fill_time = fill_occurred_at or _EVENT_AT
    domain_reservation = decode_order_reservation(reservation)
    parent_snapshot = validated_plan_snapshot(reservation)
    fee_policy: SimulatedFeePolicyV2 = fee_policy_from_snapshot(parent_snapshot)
    parent_calendar = _object(parent_snapshot["calendar_evidence"], "calendar_evidence")
    parent_calendar_snapshot = _object(parent_calendar["snapshot"], "calendar snapshot")
    parent_exchange = parent_calendar_snapshot["exchange"]
    if type(parent_exchange) is not str:
        raise AssertionError("sealed parent exchange must be text")
    evidence = _calendar_evidence(proof_exchange or parent_exchange)
    settlement_lag = parent_snapshot["settlement_lag_sessions"]
    if type(settlement_lag) is not int:
        raise AssertionError("sealed parent settlement lag must be an integer")
    selected_lag = proof_lag if proof_lag is not None else settlement_lag
    proof = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=selected_fill_time,
        settlement_exchange=evidence.snapshot.exchange,
        settlement_lag_sessions=selected_lag,
    )
    event = LocalSimulatedFillEventV1(
        source_namespace="row-reader-local-matcher",
        source_version="event-schema-v1",
        source_event_id="row-reader-event-0001",
        event_payload_hash="1" * 64,
        source_snapshot_id="row-reader-source-snapshot-001",
        source_snapshot_hash="2" * 64,
        reservation_id=cast(int, reservation.pk),
        account_id=cast(int, reservation.account_id),
        user_id=cast(int, reservation.owner_user_id),
        order_idempotency_key=reservation.idempotency_key,
        intent_payload_hash=reservation.intent_payload_hash,
        reservation_request_hash=reservation.reservation_request_hash,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        security_id=reservation.security_id,
        asset_code=reservation.asset_code,
        side=SimulatedTradeSide(reservation.side),
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        occurred_at=selected_fill_time,
        source_observed_at=selected_fill_time,
        source_available_at=selected_fill_time,
        recorded_at=selected_fill_time,
    )
    economics_reservation = domain_reservation
    if selected_fill_time < domain_reservation.reserved_at:
        economics_reservation = replace(
            domain_reservation,
            reserved_at=selected_fill_time - timedelta(seconds=1),
        )
    economics = prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=event.source_event_id,
            intent=intent,
            stored_intent_payload_hash=reservation.intent_payload_hash,
            reservation=economics_reservation,
            fee_policy=fee_policy,
            fill_occurred_at=event.occurred_at,
            quantity=event.quantity,
            price=event.price,
            prior=OrderReservationFillAccrual(
                fill_count=0,
                cumulative_quantity=Decimal("0.000000"),
                cumulative_gross=Decimal("0.00"),
                cumulative_fees=_ZERO_FEES,
            ),
            close_order=False,
        )
    )
    if invalid_fee_delta:
        altered_fees = replace(
            economics.incremental_fees,
            commission=economics.incremental_fees.commission + Decimal("0.01"),
            total_fee=economics.incremental_fees.total_fee + Decimal("0.01"),
        )
        altered_cumulative_fees = replace(
            economics.cumulative_state.cumulative_fees,
            commission=economics.cumulative_state.cumulative_fees.commission + Decimal("0.01"),
            total_fee=economics.cumulative_state.cumulative_fees.total_fee + Decimal("0.01"),
        )
        economics = replace(
            economics,
            incremental_fees=altered_fees,
            cumulative_state=replace(
                economics.cumulative_state,
                cumulative_fees=altered_cumulative_fees,
            ),
        )
    applied = domain_reservation.apply_fill(
        filled_quantity=economics.quantity,
        cash_consumed=(
            economics.gross_amount + economics.incremental_fees.total_fee
            if side is SimulatedTradeSide.BUY
            else max(
                economics.incremental_fees.total_fee - economics.gross_amount,
                Decimal("0.00"),
            )
        ),
        close_order=False,
    )
    reservation.status = applied.status.value
    reservation.filled_quantity = applied.filled_quantity
    reservation.cash_consumed = applied.cash_consumed
    reservation.shares_consumed = applied.shares_consumed
    reservation.cash_released = applied.cash_released
    reservation.shares_released = applied.shares_released
    encoded_snapshot = encode_order_reservation_fill_snapshot(
        event=event,
        economics=economics,
        reservation_id=cast(int, reservation.pk),
        fill_sequence=1,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        initial_position_mark=initial_mark,
    )
    binding = encode_order_reservation_fill_binding(
        snapshot=encoded_snapshot,
        proof=proof,
    )
    trade_pk = 701
    trade_key = simulated_order_fill_trade_key(
        reservation_id=cast(int, reservation.pk),
        source_namespace=event.source_namespace,
        fill_event_id=event.source_event_id,
    )
    fee = economics.incremental_fees
    total_cost = (
        economics.gross_amount + fee.total_fee
        if event.side is SimulatedTradeSide.BUY
        else fee.total_fee
    )
    settlement_status = "pending" if event.side is SimulatedTradeSide.BUY else None
    trade = SimulatedTradeModel(
        pk=trade_pk,
        account_id=event.account_id,
        asset_code=reservation.asset_code,
        asset_name=reservation.asset_name,
        asset_type=reservation.asset_type,
        action=event.side.value,
        quantity=economics.quantity,
        price=economics.price,
        amount=economics.gross_amount,
        commission=fee.commission,
        transfer_fee=fee.transfer_fee,
        stamp_duty=fee.stamp_duty,
        slippage=fee.slippage,
        total_cost=total_cost,
        fee_amounts_known=True,
        cost_basis_known=True if event.side is SimulatedTradeSide.BUY else None,
        realized_pnl=None,
        realized_pnl_pct=None,
        reason=intent.reason,
        signal_id=intent.signal_id,
        order_date=date.fromisoformat(cast(str, parent_snapshot["market_session"])),
        execution_date=proof.fill_market_session,
        execution_time=event.occurred_at,
        status="executed",
        idempotency_key=trade_key,
        request_payload_hash=encoded_snapshot.receipt_hash,
        fee_config_id=fee_policy.fee_schedule_v1.config_id,
        fee_schedule_hash=fee_policy.content_hash,
        fee_schedule_snapshot=fee_policy.to_payload(),
        fee_precision_basis=fee_policy.fee_schedule_v1.precision_basis.value,
        fee_calculation_purpose=fee_policy.fee_schedule_v1.calculation_purpose.value,
        fee_rounding_policy=fee_policy.fee_schedule_v1.rounding_policy.value,
        settlement_status=settlement_status,
        settlement_security_id=reservation.security_id,
        settlement_market=reservation.market,
        settlement_exchange=proof.settlement_exchange,
        settlement_board=reservation.board,
        settlement_market_session=proof.fill_market_session,
        settlement_lag_sessions=proof.settlement_lag_sessions,
        settlement_plan_binding_version=4,
        settlement_plan_binding_payload=binding.to_payload(),
        settlement_plan_binding_hash=binding.settlement_plan_binding_hash,
        settlement_bundle_id=cast(str, parent_snapshot["settlement_bundle_id"]),
        settlement_bundle_version=cast(str, parent_snapshot["settlement_bundle_version"]),
        settlement_bundle_hash=cast(str, parent_snapshot["settlement_bundle_hash"]),
        settlement_policy_id=cast(str, parent_snapshot["settlement_policy_id"]),
        settlement_policy_version=cast(str, parent_snapshot["settlement_policy_version"]),
        settlement_policy_hash=cast(str, parent_snapshot["settlement_policy_hash"]),
        execution_rule_v2_hash=cast(str, parent_snapshot["execution_rule_v2_hash"]),
        settlement_release_date=(
            proof.expected_release_session if event.side is SimulatedTradeSide.BUY else None
        ),
        settlement_calendar_snapshot_id=proof.calendar_evidence.snapshot.snapshot_id,
        settlement_calendar_content_hash=proof.calendar_evidence.snapshot.content_hash,
        settlement_calendar_record_digest=proof.calendar_evidence.snapshot.record_digest,
        settlement_calendar_publication_id=cast(
            str, proof.calendar_evidence.publication.publication_id
        ),
        settlement_calendar_publication_hash=cast(
            str, proof.calendar_evidence.publication.publication_hash
        ),
        settlement_calendar_policy_hash=cast(str, proof.calendar_evidence.publication.policy_hash),
        settlement_calendar_evidence_hash=proof.calendar_evidence.evidence_hash,
        settlement_calendar_timezone=cast(str, proof.calendar_evidence.publication.timezone_name),
        settlement_released_at=None,
        settlement_release_session=None,
        settlement_release_calendar_snapshot_id=None,
        settlement_release_calendar_content_hash=None,
        settlement_release_calendar_record_digest=None,
        settlement_release_calendar_publication_id=None,
        settlement_release_calendar_publication_hash=None,
        settlement_release_calendar_policy_hash=None,
        settlement_release_calendar_evidence_hash=None,
        settlement_release_calendar_timezone=None,
    )
    receipt = SimulatedOrderFillReceiptModel(
        pk=801,
        reservation_id=cast(int, reservation.pk),
        trade_id=trade_pk,
        fill_sequence=encoded_snapshot.fill_sequence,
        source_namespace=encoded_snapshot.source_namespace,
        source_version=encoded_snapshot.source_version,
        source_event_id=encoded_snapshot.source_event_id,
        event_kind=event.event_kind.value,
        source_event_payload=cast(
            dict[str, object],
            json.loads(encoded_snapshot.source_event_snapshot_json),
        ),
        source_event_payload_hash=encoded_snapshot.source_event_payload_hash,
        source_event_snapshot_hash=encoded_snapshot.source_event_snapshot_hash,
        economic_request_hash=encoded_snapshot.economic_request_hash,
        economics_snapshot_hash=encoded_snapshot.economics_snapshot_hash,
        plan_snapshot_hash=encoded_snapshot.plan_snapshot_hash,
        economics_payload=cast(
            dict[str, object],
            json.loads(encoded_snapshot.economics_snapshot_json),
        ),
        receipt_hash=encoded_snapshot.receipt_hash,
        receipt_version=encoded_snapshot.receipt_version,
        initial_position_mark_evidence=(
            _object(
                json.loads(encoded_snapshot.initial_position_mark_evidence_json),
                "initial position mark evidence",
            )
            if encoded_snapshot.initial_position_mark_evidence_json is not None
            else None
        ),
        created_at=AS_OF + timedelta(minutes=2),
    )
    return _Rows(
        reservation,
        receipt,
        trade,
        event,
        economics,
        proof,
        encoded_snapshot,
        initial_mark,
    )


def _persist_reader_rows(rows: _Rows) -> _Rows:
    """Persist one internally consistent post-fill row set for query-boundary tests.

    The production fill writer is intentionally outside this reader-only packet.
    This fixture applies the exact Domain transition to the already-created
    reservation, then uses Django's base QuerySet update only to materialize
    that valid state before inserting its linked Trade and append-only receipt.
    """

    reservation_id = cast(int, rows.reservation.pk)
    reservation_query = SimulatedOrderReservationModel.objects.filter(pk=reservation_id)
    updated = models.QuerySet.update(
        reservation_query,
        status=rows.reservation.status,
        filled_quantity=rows.reservation.filled_quantity,
        cash_consumed=rows.reservation.cash_consumed,
        shares_consumed=rows.reservation.shares_consumed,
        cash_released=rows.reservation.cash_released,
        shares_released=rows.reservation.shares_released,
    )
    assert updated == 1
    rows.reservation.refresh_from_db()

    rows.trade.pk = None
    rows.trade.save(force_insert=True)
    receipt = _create_receipt(
        using=connection.alias,
        encoded=rows.encoded_snapshot,
        event=rows.event,
        trade=rows.trade,
        reservation_row=rows.reservation,
    )
    rows.reservation.refresh_from_db()
    receipt.refresh_from_db()
    rows.trade.refresh_from_db()
    return _Rows(
        rows.reservation,
        receipt,
        rows.trade,
        rows.event,
        rows.economics,
        rows.proof,
        rows.encoded_snapshot,
        rows.initial_mark,
    )


def test_reader_reconciles_exact_loaded_rows_without_deriving_unknown_pnl(
    reservation_harness: _Harness,
) -> None:
    """One complete persisted-shaped row returns typed facts and preserves hash roles."""

    rows = _reader_rows(reservation_harness)
    result = read_order_reservation_fill_row(
        reservation_row=rows.reservation,
        receipt_row=rows.receipt,
        trade_row=rows.trade,
    )

    assert result.reservation_id == rows.receipt.reservation_id
    assert result.trade_id == rows.trade.pk
    assert result.fill_sequence == rows.receipt.fill_sequence
    assert result.trade_key == rows.trade.idempotency_key
    assert result.event == rows.event
    assert result.economics == rows.economics
    assert result.proof == rows.proof
    assert result.receipt_id == rows.receipt.pk
    assert result.event.event_payload_hash == rows.receipt.source_event_payload_hash
    assert result.economics.payload_hash == rows.receipt.economic_request_hash
    assert result.receipt_hash == rows.receipt.receipt_hash
    assert result.proof.proof_hash != result.receipt_hash
    assert rows.trade.realized_pnl is None
    assert rows.trade.realized_pnl_pct is None


def test_reader_accepts_persisted_complete_rows_without_issuing_queries(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Fully loaded reservation, receipt, and Trade reads require zero SQL."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness))

    with CaptureQueriesContext(connection) as captured:
        result = read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )

    assert captured.captured_queries == []
    assert result.receipt_id == rows.receipt.pk
    assert result.trade_id == rows.trade.pk
    assert result.economics == rows.economics
    assert rows.receipt.receipt_version == 1
    assert rows.receipt.initial_position_mark_evidence is None


def test_reader_accepts_v2_initial_mark_and_trade_receipt_binding(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """V2 mark evidence is persisted with the receipt bound by the Trade V4 seal."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness, include_initial_mark=True))
    assert rows.initial_mark is not None
    assert rows.receipt.receipt_version == 2
    assert rows.receipt.initial_position_mark_evidence == rows.initial_mark.to_payload()
    assert rows.trade.request_payload_hash == rows.receipt.receipt_hash
    assert rows.trade.settlement_plan_binding_payload["receipt_hash"] == rows.receipt.receipt_hash

    result = read_order_reservation_fill_row(
        reservation_row=rows.reservation,
        receipt_row=rows.receipt,
        trade_row=rows.trade,
    )
    assert result.receipt_hash == rows.receipt.receipt_hash
    assert result.trade_id == rows.trade.pk


@pytest.mark.parametrize(
    "tamper",
    ("mark", "version", "receipt_hash", "v4_binding_hash"),
    ids=("mark-content", "version-mark-pair", "receipt-seal", "trade-v4-seal"),
)
def test_reader_rejects_v2_receipt_or_trade_seal_mutation_without_ledger_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    tamper: str,
) -> None:
    """V2 tampering is rejected and the persisted financial rows remain unchanged."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness, include_initial_mark=True))
    assert rows.initial_mark is not None
    reservation_id = cast(int, rows.reservation.pk)
    receipt_id = cast(int, rows.receipt.pk)
    trade_id = cast(int, rows.trade.pk)
    before = (
        SimulatedOrderReservationModel.objects.filter(pk=reservation_id)
        .values("status", "filled_quantity", "cash_consumed", "cash_released")
        .get(),
        SimulatedOrderFillReceiptModel.objects.filter(pk=receipt_id)
        .values("receipt_version", "initial_position_mark_evidence", "receipt_hash")
        .get(),
        SimulatedTradeModel.objects.filter(pk=trade_id)
        .values("request_payload_hash", "settlement_plan_binding_hash", "quantity", "amount")
        .get(),
    )
    if tamper == "mark":
        changed_mark = dict(rows.receipt.initial_position_mark_evidence)
        changed_mark["source_record_id"] = "different-mark-row"
        rows.receipt.initial_position_mark_evidence = changed_mark
    elif tamper == "version":
        rows.receipt.receipt_version = 1
    elif tamper == "receipt_hash":
        rows.receipt.receipt_hash = "d" * 64
    else:
        rows.trade.settlement_plan_binding_hash = "e" * 64

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )

    after = (
        SimulatedOrderReservationModel.objects.filter(pk=reservation_id)
        .values("status", "filled_quantity", "cash_consumed", "cash_released")
        .get(),
        SimulatedOrderFillReceiptModel.objects.filter(pk=receipt_id)
        .values("receipt_version", "initial_position_mark_evidence", "receipt_hash")
        .get(),
        SimulatedTradeModel.objects.filter(pk=trade_id)
        .values("request_payload_hash", "settlement_plan_binding_hash", "quantity", "amount")
        .get(),
    )
    assert after == before
    assert SimulatedOrderFillReceiptModel.objects.filter(reservation_id=reservation_id).count() == 1


@pytest.mark.parametrize("deferred_row", ("reservation", "receipt", "trade"))
def test_reader_rejects_deferred_rows_before_any_implicit_query(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    deferred_row: str,
) -> None:
    """A persisted only-PK instance is rejected without loading missing columns."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness))
    reservation_row = rows.reservation
    receipt_row = rows.receipt
    trade_row = rows.trade
    if deferred_row == "reservation":
        reservation_row = SimulatedOrderReservationModel.objects.only("pk").get(
            pk=cast(int, rows.reservation.pk)
        )
    elif deferred_row == "receipt":
        receipt_row = SimulatedOrderFillReceiptModel.objects.only("pk").get(
            pk=cast(int, rows.receipt.pk)
        )
    else:
        trade_row = SimulatedTradeModel.objects.only("pk").get(pk=cast(int, rows.trade.pk))

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(SimulatedSettlementContractError, match="deferred"):
            read_order_reservation_fill_row(
                reservation_row=reservation_row,
                receipt_row=receipt_row,
                trade_row=trade_row,
            )

    assert captured.captured_queries == []


def test_reader_buy_total_cost_is_exact_under_low_ambient_decimal_precision(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Fee-bearing persisted BUY rows do not depend on caller Decimal precision."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness))
    assert rows.economics.incremental_fees.total_fee > Decimal("0.00")

    with localcontext() as decimal_context:
        decimal_context.prec = 2
        with CaptureQueriesContext(connection) as captured:
            result = read_order_reservation_fill_row(
                reservation_row=rows.reservation,
                receipt_row=rows.receipt,
                trade_row=rows.trade,
            )
        assert decimal_context.prec == 2

    assert captured.captured_queries == []
    assert result.economics == rows.economics
    assert rows.trade.total_cost == (
        rows.economics.gross_amount + rows.economics.incremental_fees.total_fee
    )


def test_reader_accepts_persisted_sell_fee_only_cost_with_null_settlement(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """SELL cost retains fees only and never creates a BUY settlement status."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness, side=SimulatedTradeSide.SELL))

    assert rows.economics.incremental_fees.total_fee > Decimal("0.00")
    assert rows.trade.total_cost == rows.economics.incremental_fees.total_fee
    assert rows.trade.settlement_status is None
    assert rows.trade.settlement_release_date is None

    result = read_order_reservation_fill_row(
        reservation_row=rows.reservation,
        receipt_row=rows.receipt,
        trade_row=rows.trade,
    )

    assert result.economics == rows.economics
    assert result.event.side is SimulatedTradeSide.SELL


@pytest.mark.parametrize("field_name", ("source_event_payload_hash", "economic_request_hash"))
def test_reader_rejects_receipt_columns_detached_from_canonical_payloads(
    reservation_harness: _Harness,
    field_name: str,
) -> None:
    """Independent source/economic digests are checked against their exact JSON seals."""

    rows = _reader_rows(reservation_harness)
    setattr(rows.receipt, field_name, "9" * 64)

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("idempotency_key", "wrong-fill-key"),
        ("request_payload_hash", "9" * 64),
        ("amount", Decimal("100.01")),
        ("settlement_exchange", "SZ"),
        ("settlement_lag_sessions", 1),
        ("settlement_calendar_evidence_hash", "8" * 64),
        ("fee_amounts_known", False),
    ),
)
def test_reader_rejects_trade_columns_detached_from_receipt_or_proof(
    reservation_harness: _Harness,
    field_name: str,
    replacement: object,
) -> None:
    """The ordinary Trade projection cannot drift from immutable per-fill evidence."""

    rows = _reader_rows(reservation_harness)
    setattr(rows.trade, field_name, replacement)

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_rejects_receipt_linked_to_a_different_trade(
    reservation_harness: _Harness,
) -> None:
    """The OneToOne row association is independently checked by the reader."""

    rows = _reader_rows(reservation_harness)
    rows.receipt.trade_id = rows.trade.pk + 1

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_rejects_a_self_consistent_proof_for_another_parent_exchange(
    reservation_harness: _Harness,
) -> None:
    """A valid re-sealed proof still cannot replace the order's sealed exchange."""

    rows = _reader_rows(reservation_harness, proof_exchange="SZ")

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_rejects_a_self_consistent_proof_with_another_parent_lag(
    reservation_harness: _Harness,
) -> None:
    """A proof's valid lag arithmetic must also match the frozen order policy."""

    rows = _reader_rows(reservation_harness, proof_lag=1)

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_reprices_a_self_consistent_fee_payload_against_sealed_fee_v2(
    reservation_harness: _Harness,
) -> None:
    """A re-sealed economics snapshot cannot replace the parent's FeeV2 result."""

    rows = _reader_rows(reservation_harness, invalid_fee_delta=True)

    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_rejects_a_resealed_fill_that_predates_its_parent_reservation(
    reservation_harness: _Harness,
) -> None:
    """A typed event and proof cannot place execution before the order existed."""

    parent_reserved_at = AS_OF
    rows = _reader_rows(
        reservation_harness,
        fill_occurred_at=parent_reserved_at - timedelta(minutes=1),
    )

    assert rows.event.occurred_at < rows.reservation.reserved_at
    assert rows.proof.fill_occurred_at == rows.event.occurred_at
    with pytest.raises(SimulatedSettlementContractError):
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=rows.receipt,
            trade_row=rows.trade,
        )


def test_reader_rejects_v2_json_null_mark_evidence_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A JSON literal null is non-SQL-NULL but is not valid V2 mark evidence."""

    del persisted_receipt_schema
    rows = _persist_reader_rows(_reader_rows(reservation_harness, include_initial_mark=True))
    assert rows.initial_mark is not None
    assert rows.receipt.receipt_version == 2
    receipt_id = cast(int, rows.receipt.pk)
    table = connection.ops.quote_name(SimulatedOrderFillReceiptModel._meta.db_table)
    evidence_column = connection.ops.quote_name(
        SimulatedOrderFillReceiptModel._meta.get_field("initial_position_mark_evidence").column
    )
    primary_key_column = connection.ops.quote_name(SimulatedOrderFillReceiptModel._meta.pk.column)
    if connection.vendor == "sqlite":
        update_sql = (
            f"UPDATE {table} SET {evidence_column} = json('null') "
            f"WHERE {primary_key_column} = %s"
        )
        update_params: tuple[object, ...] = (receipt_id,)
    elif connection.vendor == "postgresql":
        update_sql = (
            f"UPDATE {table} SET {evidence_column} = %s::jsonb " f"WHERE {primary_key_column} = %s"
        )
        update_params = ("null", receipt_id)
    else:
        pytest.fail(f"JSON-null receipt test does not support {connection.vendor}")

    with connection.cursor() as cursor:
        cursor.execute(update_sql, update_params)
        assert cursor.rowcount == 1
        cursor.execute(
            f"SELECT {evidence_column} IS NULL FROM {table} " f"WHERE {primary_key_column} = %s",
            [receipt_id],
        )
        sql_null_before = cursor.fetchone()
    assert sql_null_before == (False,)

    rows.receipt.refresh_from_db()
    assert rows.receipt.initial_position_mark_evidence is None
    reservation_id = cast(int, rows.reservation.pk)
    trade_id = cast(int, rows.trade.pk)
    before = (
        SimulatedOrderReservationModel.objects.filter(pk=reservation_id)
        .values("status", "filled_quantity", "cash_consumed", "cash_released")
        .get(),
        SimulatedOrderFillReceiptModel.objects.filter(pk=receipt_id)
        .values("receipt_version", "initial_position_mark_evidence", "receipt_hash")
        .get(),
        SimulatedTradeModel.objects.filter(pk=trade_id)
        .values("request_payload_hash", "settlement_plan_binding_hash", "quantity", "amount")
        .get(),
    )
    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(SimulatedSettlementContractError):
            read_order_reservation_fill_row(
                reservation_row=rows.reservation,
                receipt_row=rows.receipt,
                trade_row=rows.trade,
            )
    assert captured.captured_queries == []
    after = (
        SimulatedOrderReservationModel.objects.filter(pk=reservation_id)
        .values("status", "filled_quantity", "cash_consumed", "cash_released")
        .get(),
        SimulatedOrderFillReceiptModel.objects.filter(pk=receipt_id)
        .values("receipt_version", "initial_position_mark_evidence", "receipt_hash")
        .get(),
        SimulatedTradeModel.objects.filter(pk=trade_id)
        .values("request_payload_hash", "settlement_plan_binding_hash", "quantity", "amount")
        .get(),
    )
    assert after == before
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {evidence_column} IS NULL FROM {table} " f"WHERE {primary_key_column} = %s",
            [receipt_id],
        )
        sql_null_after = cursor.fetchone()
    assert sql_null_after == (False,)
