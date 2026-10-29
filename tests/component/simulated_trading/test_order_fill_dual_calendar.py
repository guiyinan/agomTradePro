"""Exercise separate event-time and current-time fill calendars."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.contrib.auth import get_user_model

from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    ReleaseDueSimulatedSettlementsUseCase,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading import test_execution_settlement_uow as settlement_uow_tests
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _Clock,
    _execute_use_case,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _IdentityReader as _BaseIdentityReader,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
    _Rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_EVENT_AT = AS_OF + timedelta(minutes=1)
_APPLY_AT = AS_OF + timedelta(hours=3)
_CROSS_DAY_APPLY_AT = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
_LEGACY_APPLY_AT = _READ_CUTOFF
_RELEASE_AT = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
_OPEN_DATES = {
    date(2026, 10, 16),
    date(2026, 10, 19),
    date(2026, 10, 20),
    date(2026, 10, 21),
}


@dataclass(slots=True)
class _CalendarReader:
    """Return one deliberately injected calendar result and record its cutoff."""

    evidence: ExecutionCalendarEvidence | None
    calls: list[tuple[str, datetime, date | None]]

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Return the configured evidence without normalizing invalid fixtures."""

        self.calls.append((exchange, as_of, coverage_start))
        return self.evidence


class _CrossDayIdentityReader(_BaseIdentityReader):
    """Keep the synthetic sealed identity explicitly valid through next-session Apply."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Extend only this reservation fixture's identity window before it is sealed."""

        evidence = super().get_execution_instrument_identity(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(
            evidence,
            identity_valid_until=_CROSS_DAY_APPLY_AT + timedelta(days=1),
        )


def _reservation_harness_with_calendar(
    base: _Harness,
    *,
    settlement_lag_sessions: int,
    calendar_valid_until: datetime,
) -> tuple[_Harness, ExecutionCalendarEvidence]:
    """Reserve against one calendar that may expire before the later Apply read."""

    initial_evidence = _calendar(as_of=AS_OF, open_dates=_OPEN_DATES)
    publication = initial_evidence.publication
    if publication is None:
        raise AssertionError("reservation fixture must have a formal calendar publication")
    sealed_evidence = ExecutionCalendarEvidence(
        snapshot=initial_evidence.snapshot,
        publication=replace(publication, reference_valid_until=calendar_valid_until),
    )
    preparer, rule_reader, _ = _execute_use_case(
        account_id=cast(int, base.account.pk),
        user_id=base.user_id,
        as_of=AS_OF,
        evidence=sealed_evidence,
        lag=settlement_lag_sessions,
    )
    reserve = ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=base.repository,
        clock=_Clock(AS_OF),
    )
    return (
        replace(base, preparer=preparer, reserve=reserve, rule_reader=rule_reader),
        sealed_evidence,
    )


def _event_proof(
    *,
    rows: _Rows,
    evidence: ExecutionCalendarEvidence,
    cutoff: datetime | None = None,
    occurred_at: datetime | None = None,
) -> OrderFillSettlementProof:
    """Build the event proof from one supplied calendar without changing clocks."""

    selected_event_time = occurred_at if occurred_at is not None else rows.event.occurred_at
    selected_cutoff = cutoff if cutoff is not None else selected_event_time
    return build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=selected_cutoff,
        fill_occurred_at=selected_event_time,
        settlement_exchange=evidence.snapshot.exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )


def _apply(
    *,
    rows: _Rows,
    proof: OrderFillSettlementProof,
    calendar_reader: PublishedExecutionCalendarReader | None,
    clock_at: datetime,
) -> object:
    """Apply the configured row-reader fixture through the real ORM writer."""

    event = rows.event
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(event, []),
        current_calendar_reader=calendar_reader,
        using="default",
    )
    return repository.apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=proof,
        clock=_FixedClock(clock_at),
    )


def _fill_state(
    *,
    account: SimulatedAccountModel,
    reservation_id: int,
) -> tuple[object, ...]:
    """Capture persistent financial rows and reservation state around rejection."""

    account_row = SimulatedAccountModel.objects.get(pk=account.pk)
    reservation = SimulatedOrderReservationModel.objects.get(pk=reservation_id)
    positions = tuple(
        PositionModel.objects.filter(account_id=account.pk)
        .order_by("pk")
        .values_list("pk", "quantity", "available_quantity", "total_cost", "market_value")
    )
    trades = tuple(
        SimulatedTradeModel.objects.filter(account_id=account.pk)
        .order_by("pk")
        .values_list("pk", "quantity", "settlement_status", "settlement_release_proof_hash")
    )
    receipts = tuple(
        SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account.pk)
        .order_by("pk")
        .values_list("pk", "receipt_hash")
    )
    return (
        account_row.current_cash,
        account_row.current_market_value,
        account_row.total_value,
        account_row.total_trades,
        positions,
        trades,
        receipts,
        reservation.status,
        reservation.filled_quantity,
        reservation.cash_consumed,
        reservation.shares_consumed,
        reservation.cash_released,
        reservation.shares_released,
    )


def _persisted_fill(
    *,
    reservation: SimulatedOrderReservationModel,
) -> DecodedOrderReservationFillRow:
    """Read the exact stored Trade and receipt through the canonical row reader."""

    stored_reservation = SimulatedOrderReservationModel.objects.get(pk=reservation.pk)
    receipt = SimulatedOrderFillReceiptModel.objects.get(reservation_id=reservation.pk)
    trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
    return read_order_reservation_fill_row(
        reservation_row=stored_reservation,
        receipt_row=receipt,
        trade_row=trade,
    )


def _prepare_rows(
    base: _Harness,
    *,
    lag: int,
    calendar_valid_until: datetime,
) -> tuple[_Harness, ExecutionCalendarEvidence, _Rows]:
    """Prepare one active BUY with an existing Position and retained calendar."""

    harness, sealed_evidence = _reservation_harness_with_calendar(
        base,
        settlement_lag_sessions=lag,
        calendar_valid_until=calendar_valid_until,
    )
    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    return harness, sealed_evidence, rows


def test_apply_uses_event_time_reservation_calendar_and_fresh_lock_time_calendar(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The sealed calendar can expire after the event when current evidence is fresh."""

    del ledger, persisted_receipt_schema
    sealed_until = _EVENT_AT + timedelta(seconds=30)
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=2,
        calendar_valid_until=sealed_until,
    )
    current_evidence = _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(current_evidence, [])
    event_proof = _event_proof(rows=rows, evidence=sealed_evidence)

    _apply(
        rows=rows,
        proof=event_proof,
        calendar_reader=current_reader,
        clock_at=_APPLY_AT,
    )

    stored = _persisted_fill(reservation=rows.reservation)
    assert stored.proof.calendar_evidence.evidence_hash == sealed_evidence.evidence_hash
    assert stored.proof.calendar_read_cutoff == rows.event.occurred_at
    assert stored.release_proof is None
    assert current_reader.calls == [("SH", _APPLY_AT, rows.proof.fill_market_session)]


@pytest.mark.parametrize(
    ("current_kind", "expected_code"),
    (
        ("missing", "SIMULATED_FILL_RELEASE_CALENDAR_UNAVAILABLE"),
        ("stale", "SIMULATED_FILL_RELEASE_CALENDAR_INVALID"),
        ("wrong_exchange", "SIMULATED_FILL_RELEASE_CALENDAR_INVALID"),
        ("missing_event_coverage", "SIMULATED_FILL_RELEASE_CALENDAR_INVALID"),
    ),
)
def test_invalid_current_calendar_blocks_without_ledger_mutation(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    current_kind: str,
    expected_code: str,
) -> None:
    """Missing or unsuitable lock-time evidence cannot create a fill or release."""

    del ledger, persisted_receipt_schema
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=2,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    current_evidence: ExecutionCalendarEvidence | None
    if current_kind == "missing":
        current_evidence = None
    elif current_kind == "stale":
        stale_evidence = _calendar(as_of=AS_OF, open_dates=_OPEN_DATES)
        assert stale_evidence.publication is not None
        current_evidence = ExecutionCalendarEvidence(
            snapshot=stale_evidence.snapshot,
            publication=replace(
                stale_evidence.publication,
                reference_valid_until=_APPLY_AT - timedelta(seconds=1),
            ),
        )
    elif current_kind == "wrong_exchange":
        current_evidence = _calendar(
            as_of=_APPLY_AT,
            open_dates=_OPEN_DATES,
            exchange="SZ",
        )
    else:
        current_evidence = _calendar(
            as_of=_APPLY_AT,
            open_dates={date(2026, 10, 17), date(2026, 10, 19), date(2026, 10, 20)},
            start=date(2026, 10, 17),
            end=date(2026, 10, 21),
        )
    current_reader = _CalendarReader(current_evidence, [])
    proof = _event_proof(rows=rows, evidence=sealed_evidence)
    before = _fill_state(account=harness.account, reservation_id=rows.reservation.pk)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _apply(
            rows=rows,
            proof=proof,
            calendar_reader=current_reader,
            clock_at=_APPLY_AT,
        )

    assert blocked.value.code == expected_code
    assert _fill_state(account=harness.account, reservation_id=rows.reservation.pk) == before
    assert current_reader.calls == [("SH", _APPLY_AT, rows.proof.fill_market_session)]


def test_inactive_owner_is_blocked_before_event_or_calendar_reads(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An inactive owner cannot apply a fill even with valid event/current calendars."""

    del persisted_receipt_schema
    user, _ = ledger
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=2,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    current_evidence = _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(current_evidence, [])
    proof = _event_proof(rows=rows, evidence=sealed_evidence)
    before = _fill_state(account=harness.account, reservation_id=rows.reservation.pk)
    user_row = get_user_model().objects.get(pk=harness.user_id)
    assert getattr(user, "pk", None) == harness.user_id
    user_row.is_active = False
    user_row.save(update_fields=["is_active"])

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _apply(
            rows=rows,
            proof=proof,
            calendar_reader=current_reader,
            clock_at=_APPLY_AT,
        )

    assert blocked.value.code == "SIMULATED_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"
    assert _fill_state(account=harness.account, reservation_id=rows.reservation.pk) == before
    assert current_reader.calls == []


def test_event_proof_from_replacement_calendar_is_rejected_without_writes(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Same-exchange replacement evidence cannot stand in for the sealed event calendar."""

    del ledger, persisted_receipt_schema
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=2,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    replacement_evidence = _calendar(as_of=AS_OF, open_dates=_OPEN_DATES)
    current_evidence = _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    reader = _CalendarReader(current_evidence, [])
    replacement_proof = _event_proof(rows=rows, evidence=replacement_evidence)
    assert replacement_evidence.evidence_hash != sealed_evidence.evidence_hash
    before = _fill_state(account=harness.account, reservation_id=rows.reservation.pk)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _apply(
            rows=rows,
            proof=replacement_proof,
            calendar_reader=reader,
            clock_at=_APPLY_AT,
        )

    assert blocked.value.code == "SIMULATED_FILL_CALENDAR_INVALID"
    assert _fill_state(account=harness.account, reservation_id=rows.reservation.pk) == before
    assert reader.calls == []


def test_event_after_sealed_calendar_expiry_is_rejected_without_writes(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A different event-time calendar cannot replace the expired sealed reference."""

    del ledger, persisted_receipt_schema
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=2,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    expired_event_at = _EVENT_AT + timedelta(minutes=2)
    event = replace(
        rows.event,
        occurred_at=expired_event_at,
        source_observed_at=expired_event_at,
        source_available_at=expired_event_at,
        recorded_at=expired_event_at,
    )
    rows = replace(rows, event=event)
    replacement_evidence = _calendar(as_of=expired_event_at, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(replacement_evidence, [])
    replacement_proof = build_order_fill_settlement_proof(
        calendar_evidence=replacement_evidence,
        calendar_read_cutoff=expired_event_at,
        fill_occurred_at=expired_event_at,
        settlement_exchange="SH",
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    assert replacement_evidence.evidence_hash != sealed_evidence.evidence_hash
    before = _fill_state(account=harness.account, reservation_id=rows.reservation.pk)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _apply(
            rows=rows,
            proof=replacement_proof,
            calendar_reader=current_reader,
            clock_at=_APPLY_AT,
        )

    assert blocked.value.code == "SIMULATED_FILL_CALENDAR_INVALID"
    assert _fill_state(account=harness.account, reservation_id=rows.reservation.pk) == before
    assert current_reader.calls == []


def test_t0_fill_persists_distinct_event_and_current_release_proofs(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A new zero-lag fill seals current release evidence separately from its event proof."""

    del ledger, persisted_receipt_schema
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=0,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    current_evidence = _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(current_evidence, [])
    event_proof = _event_proof(rows=rows, evidence=sealed_evidence)

    _apply(
        rows=rows,
        proof=event_proof,
        calendar_reader=current_reader,
        clock_at=_APPLY_AT,
    )

    stored = _persisted_fill(reservation=rows.reservation)
    assert stored.proof.calendar_evidence.evidence_hash == sealed_evidence.evidence_hash
    assert stored.release_proof is not None
    assert stored.release_proof.calendar_evidence.evidence_hash == current_evidence.evidence_hash
    assert (
        stored.proof.calendar_evidence.evidence_hash
        != stored.release_proof.calendar_evidence.evidence_hash
    )
    trade = SimulatedTradeModel.objects.get(pk=stored.trade_id)
    assert trade.settlement_status == "released"
    assert trade.settlement_release_proof_payload is not None
    assert trade.settlement_release_proof_hash == stored.release_proof.proof_hash


def test_cross_day_t0_keeps_event_receipt_date_and_seals_later_release_session(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later current session releases T+0 without rewriting the fill or receipt date."""

    del ledger, persisted_receipt_schema
    with monkeypatch.context() as patch:
        patch.setattr(
            settlement_uow_tests,
            "_IdentityReader",
            _CrossDayIdentityReader,
        )
        harness, sealed_evidence, rows = _prepare_rows(
            reservation_harness,
            lag=0,
            calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
        )

    identity_payload = cast(dict[str, object], rows.reservation.plan_snapshot["identity_evidence"])
    identity_until_text = identity_payload["identity_valid_until"]
    assert type(identity_until_text) is str
    identity_until = datetime.fromisoformat(identity_until_text.replace("Z", "+00:00"))
    assert identity_until > _CROSS_DAY_APPLY_AT
    original_plan_hash = rows.reservation.plan_snapshot_hash

    current_evidence = _calendar(as_of=_CROSS_DAY_APPLY_AT, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(current_evidence, [])
    event_proof = _event_proof(rows=rows, evidence=sealed_evidence)
    assert event_proof.fill_market_session == date(2026, 10, 16)
    assert current_evidence.current_open_session(_CROSS_DAY_APPLY_AT) == date(2026, 10, 19)
    assert current_evidence.snapshot.recorded_at > rows.event.occurred_at

    _apply(
        rows=rows,
        proof=event_proof,
        calendar_reader=current_reader,
        clock_at=_CROSS_DAY_APPLY_AT,
    )

    stored = _persisted_fill(reservation=rows.reservation)
    assert stored.event == rows.event
    assert stored.proof.fill_market_session == date(2026, 10, 16)
    assert stored.proof.calendar_read_cutoff == rows.event.occurred_at
    assert stored.release_proof is not None
    assert stored.release_proof.fill_market_session == date(2026, 10, 16)
    assert stored.release_proof.release_session == date(2026, 10, 19)
    assert stored.release_proof.calendar_evidence.evidence_hash == current_evidence.evidence_hash
    reservation_after = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    assert reservation_after.plan_snapshot_hash == original_plan_hash
    trade = SimulatedTradeModel.objects.get(pk=stored.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.get(pk=stored.receipt_id)
    assert trade.execution_date == date(2026, 10, 16)
    assert trade.settlement_release_date == date(2026, 10, 16)
    assert trade.settlement_release_session == date(2026, 10, 19)
    assert trade.settlement_released_at == _CROSS_DAY_APPLY_AT
    assert receipt.source_event_id == rows.event.source_event_id
    assert receipt.source_event_payload_hash == rows.event.event_payload_hash
    assert SimulatedOrderFillReceiptModel.objects.filter(reservation=rows.reservation).count() == 1
    assert current_reader.calls == [("SH", _CROSS_DAY_APPLY_AT, date(2026, 10, 16))]


def test_legacy_t0_without_current_reader_keeps_proof_compatibility(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The absent optional reader preserves the existing zero-lag proof format."""

    del ledger, persisted_receipt_schema
    harness, _, rows = _prepare_rows(
        reservation_harness,
        lag=0,
        calendar_valid_until=AS_OF + timedelta(days=10),
    )
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        using="default",
    )
    repository.apply_fill_event(
        event=rows.event,
        expected_event_payload_hash=rows.event.event_payload_hash,
        settlement_proof=rows.proof,
        clock=_FixedClock(_LEGACY_APPLY_AT),
    )

    stored = _persisted_fill(reservation=rows.reservation)
    trade = SimulatedTradeModel.objects.get(pk=stored.trade_id)
    assert trade.settlement_status == "released"
    assert trade.settlement_release_proof_payload is None
    assert trade.settlement_release_proof_hash is None
    assert stored.release_proof is None


def test_t1_fill_stays_pending_then_release_use_case_seals_later_calendar(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """T+1 remains pending at fill and receives a separate proof at later release."""

    del ledger, persisted_receipt_schema
    harness, sealed_evidence, rows = _prepare_rows(
        reservation_harness,
        lag=1,
        calendar_valid_until=_EVENT_AT + timedelta(seconds=30),
    )
    current_evidence = _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    current_reader = _CalendarReader(current_evidence, [])
    event_proof = _event_proof(rows=rows, evidence=sealed_evidence)

    _apply(
        rows=rows,
        proof=event_proof,
        calendar_reader=current_reader,
        clock_at=_APPLY_AT,
    )
    pending = _persisted_fill(reservation=rows.reservation)
    pending_trade = SimulatedTradeModel.objects.get(pk=pending.trade_id)
    assert pending_trade.settlement_status == "pending"
    assert pending.release_proof is None

    release_evidence = _calendar(as_of=_RELEASE_AT, open_dates=_OPEN_DATES)
    release_reader = _CalendarReader(release_evidence, [])
    release = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=release_reader,
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_FixedClock(_RELEASE_AT),
    )
    released_count = release.execute(
        account_id=cast(int, harness.account.pk),
        user_id=harness.user_id,
        asset_code=rows.event.asset_code,
        exchange="SH",
    )

    assert released_count == 1
    released = _persisted_fill(reservation=rows.reservation)
    assert released.proof.calendar_evidence.evidence_hash == sealed_evidence.evidence_hash
    assert released.release_proof is not None
    assert released.release_proof.calendar_evidence.evidence_hash == release_evidence.evidence_hash
    position = PositionModel.objects.get(account=harness.account, asset_code=rows.event.asset_code)
    assert position.available_quantity == Decimal("110.000000")
