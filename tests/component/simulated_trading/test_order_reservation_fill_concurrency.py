"""Native PostgreSQL concurrency contracts for persisted local order fills."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

import pytest
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading import (
    test_order_reservation_concurrency as _native_concurrency,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _calendar as _settlement_calendar,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _execute_use_case as _execute_settlement_use_case,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _AccountParentLockWait,
    _assert_account_parent_lock_wait,
    _lock_account_parent,
    _submit_worker,
    _wait_for_account_parent_lock,
    _WorkerCall,
    _WorkerOutcome,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _Harness,
    _invoke,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

_require_migrated_native_postgres = _native_concurrency._require_migrated_native_postgres


pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True, slots=True)
class _SerializedPair:
    """Keep both outcomes and the observed PostgreSQL parent-row wait."""

    holder_pid: int
    waiter_pid: int
    lock_wait: _AccountParentLockWait
    first_result: object
    waiter_outcome: _WorkerOutcome


def _run_first_then_waiter(
    *,
    account: SimulatedAccountModel,
    first_operation: Callable[[], object],
    waiting_operation: Callable[[], object],
    thread_name: str,
) -> _SerializedPair:
    """Commit one operation while a second connection waits on the account row."""

    worker_call: _WorkerCall | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name) as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(account)
            first_result = first_operation()
            worker_call = _submit_worker(executor, waiting_operation)
            waiter_pid = worker_call.backend_pids[0]
            assert waiter_pid != holder_pid
            lock_wait = _wait_for_account_parent_lock(
                waiter_pid=waiter_pid,
                allowed_blocker_pids=(holder_pid,),
                future=worker_call.future,
            )
            _assert_account_parent_lock_wait(lock_wait)
            assert holder_pid in lock_wait.blocker_pids
        assert worker_call is not None
        waiter_outcome = worker_call.future.result(timeout=20)
    return _SerializedPair(
        holder_pid=holder_pid,
        waiter_pid=waiter_pid,
        lock_wait=lock_wait,
        first_result=first_result,
        waiter_outcome=waiter_outcome,
    )


def _account_state(account_id: int) -> tuple[Decimal, Decimal, Decimal, int, int]:
    """Return durable account cash, mark, total value and trade counters."""

    account = SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS).get(pk=account_id)
    return (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        account.winning_trades,
    )


def _position_state(
    *,
    account_id: int,
    asset_code: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, bool, bool | None]:
    """Return durable position quantity, sellability, cost and valuation state."""

    position = PositionModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=account_id,
        asset_code=asset_code,
    )
    return (
        position.quantity,
        position.available_quantity,
        position.total_cost,
        position.market_value,
        position.current_price,
        position.valuation_known,
        position.cost_basis_known,
    )


def _reservation_resources(
    reservation: SimulatedOrderReservationModel,
) -> tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return exact durable fill and release totals for one parent order."""

    return (
        reservation.status,
        reservation.filled_quantity,
        reservation.cash_consumed,
        reservation.shares_consumed,
        reservation.cash_released,
        reservation.shares_released,
        reservation.cash_reserved,
        reservation.shares_reserved,
    )


@dataclass(slots=True)
class _InitialPositionMarkReader:
    """Return one independently prepared mark proof and record its exact request."""

    proof: InitialPositionMarkProof | None
    calls: list[tuple[str, str, str, str, str, datetime]]

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Record the identity and cutoff before returning the configured proof."""

        self.calls.append((security_id, asset_code, asset_type, market, board, read_at))
        return self.proof


def _initial_position_mark(
    *,
    event: LocalSimulatedFillEventV1,
    reservation: SimulatedOrderReservationModel,
    read_at: datetime,
) -> InitialPositionMarkProof:
    """Build a source-backed mark independent of the event's execution price."""

    observed_at = read_at - timedelta(seconds=10)
    return InitialPositionMarkProof(
        security_id=event.security_id,
        asset_code=event.asset_code,
        asset_type=reservation.asset_type,
        market=reservation.market,
        board=reservation.board,
        price=Decimal("10.2500"),
        source_observed_at=observed_at,
        source_available_at=None,
        read_at=read_at,
        publication_as_of=read_at - timedelta(seconds=2),
        published_at=read_at - timedelta(seconds=1),
        valid_until=observed_at + timedelta(seconds=600),
        freshness_window_seconds=600,
        source_identity="test.independent-current-mark",
        source_record_id="test-first-buy-mark-record-001",
        source_content_hash="a" * 64,
        publication_id="test-first-buy-mark-publication-001",
        publication_hash="b" * 64,
        policy_identity="test-first-buy-mark-policy-v1",
        policy_content_hash="c" * 64,
    )


def _harness_with_one_session_settlement_lag(harness: _Harness) -> _Harness:
    """Use the explicit ordinary T+1 fixture policy for this concurrency case."""

    assert type(harness.account.pk) is int
    assert type(harness.user_id) is int
    evidence = _settlement_calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    preparer, rule_reader, _ = _execute_settlement_use_case(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        as_of=AS_OF,
        evidence=evidence,
        lag=1,
    )
    reserve = ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=harness.repository,
        clock=_FixedClock(AS_OF),
    )
    return replace(harness, preparer=preparer, reserve=reserve, rule_reader=rule_reader)


@pytest.fixture(autouse=True)
def _use_established_native_database_guard(
    _require_migrated_native_postgres: None,
) -> None:
    """Reuse the existing migration, PostgreSQL, and TEST.NAME safety guard."""

    del _require_migrated_native_postgres


def test_postgres_same_fill_event_is_written_once_across_two_connections(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An exact concurrent event replay returns the one durable Trade and receipt."""

    del persisted_receipt_schema
    harness = reservation_harness
    position = _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    account_before = _account_state(harness.account.pk)

    def apply_same_event() -> SimulatedOrderFillResult:
        """Submit the original stable event locator and payload unchanged."""

        return _invoke(
            repository,
            rows.event,
            rows.proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    pair = _run_first_then_waiter(
        account=harness.account,
        first_operation=apply_same_event,
        waiting_operation=apply_same_event,
        thread_name="fill-same-event-replay",
    )
    assert pair.waiter_pid != pair.holder_pid
    assert pair.lock_wait.wait_event_type == "Lock"
    assert pair.holder_pid in pair.lock_wait.blocker_pids
    assert isinstance(pair.first_result, SimulatedOrderFillResult)
    assert pair.first_result.replayed is False
    assert pair.waiter_outcome.blocked_code is None
    assert isinstance(pair.waiter_outcome.value, SimulatedOrderFillResult)
    replay = pair.waiter_outcome.value
    assert replay.replayed is True
    assert replay.reservation == pair.first_result.reservation
    assert len(reader.calls) == 1

    trades = list(
        SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=harness.account.pk)
        .order_by("pk")
    )
    receipts = list(
        SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade__account_id=harness.account.pk)
        .order_by("pk")
    )
    assert len(trades) == 1
    assert len(receipts) == 1
    assert receipts[0].trade_id == trades[0].pk
    assert receipts[0].source_event_id == rows.event.source_event_id
    assert receipts[0].receipt_hash == trades[0].request_payload_hash
    trade = trades[0]
    fee_total = trade.commission + trade.transfer_fee + trade.stamp_duty + trade.slippage
    assert trade.total_cost == trade.amount + fee_total
    account_after = _account_state(harness.account.pk)
    assert account_after[0] == account_before[0] - trade.total_cost
    assert account_after[3] == account_before[3] + 1
    assert _position_state(
        account_id=harness.account.pk,
        asset_code=rows.event.asset_code,
    ) == (
        position.quantity + rows.event.quantity,
        position.available_quantity,
        position.total_cost + trade.total_cost,
        Decimal("1100.00"),
        position.current_price,
        True,
        position.cost_basis_known,
    )
    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert rows.reservation.filled_quantity == rows.event.quantity
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows.reservation.cash_consumed == trade.total_cost
    assert rows.reservation.cash_released == Decimal("0.00")
    remaining_cash = (
        rows.reservation.cash_reserved
        - rows.reservation.cash_consumed
        - rows.reservation.cash_released
    )
    assert remaining_cash == rows.reservation.cash_reserved - trade.total_cost
    assert remaining_cash > Decimal("0.00")
    assert replay.reservation.status is OrderReservationStatus.ACTIVE
    assert replay.reservation.remaining_cash == remaining_cash
    assert (
        rows.reservation.shares_consumed + rows.reservation.shares_released
        == rows.reservation.shares_reserved
    )
    assert rows.reservation.shares_consumed == Decimal("0.000000")
    assert rows.reservation.shares_released == Decimal("0.000000")


@pytest.mark.parametrize(
    "first_action",
    ["fill", "cancel"],
    ids=["fill-then-cancel", "cancel-then-fill"],
)
def test_postgres_fill_cancel_race_preserves_exact_resources_once(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    first_action: Literal["fill", "cancel"],
) -> None:
    """Both serialized fill/cancel orders conserve the hold and avoid duplicate fees."""

    del persisted_receipt_schema
    harness = reservation_harness
    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    reader = _EventReader(rows.event, [])
    fill_repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        using="default",
    )
    account_before = _account_state(harness.account.pk)
    position_before = _position_state(
        account_id=harness.account.pk,
        asset_code=rows.event.asset_code,
    )

    def apply_fill() -> SimulatedOrderFillResult:
        """Apply the one stable partial event through the real writer."""

        return _invoke(
            fill_repository,
            rows.event,
            rows.proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    def cancel_order() -> OrderReservation:
        """Cancel the same owner-scoped hold through its real repository."""

        return harness.repository.cancel_order(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            idempotency_key=rows.reservation.idempotency_key,
            clock=_FixedClock(_READ_CUTOFF),
        )

    if first_action == "fill":
        first_operation: Callable[[], object] = apply_fill
        waiting_operation: Callable[[], object] = cancel_order
    else:
        first_operation = cancel_order
        waiting_operation = apply_fill

    pair = _run_first_then_waiter(
        account=harness.account,
        first_operation=first_operation,
        waiting_operation=waiting_operation,
        thread_name=f"fill-cancel-{first_action}-first",
    )
    assert pair.waiter_pid != pair.holder_pid
    assert pair.lock_wait.wait_event_type == "Lock"
    assert pair.holder_pid in pair.lock_wait.blocker_pids

    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    trades = list(
        SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=harness.account.pk)
        .order_by("pk")
    )
    receipts = list(
        SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade__account_id=harness.account.pk)
        .order_by("pk")
    )
    if first_action == "fill":
        assert isinstance(pair.first_result, SimulatedOrderFillResult)
        assert pair.first_result.replayed is False
        assert pair.waiter_outcome.blocked_code is None
        assert isinstance(pair.waiter_outcome.value, OrderReservation)
        assert pair.waiter_outcome.value.status is OrderReservationStatus.CANCELLED
        assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
        assert len(trades) == 1
        assert len(receipts) == 1
        assert receipts[0].trade_id == trades[0].pk
        assert receipts[0].source_event_id == rows.event.source_event_id
        assert len(reader.calls) == 1
        filled = pair.first_result.reservation
        assert rows.reservation.filled_quantity == filled.filled_quantity
        assert rows.reservation.cash_consumed == filled.cash_consumed
        assert rows.reservation.shares_consumed == filled.shares_consumed
        remaining_cash_after_fill = (
            filled.cash_reserved - filled.cash_consumed - filled.cash_released
        )
        remaining_shares_after_fill = (
            filled.shares_reserved - filled.shares_consumed - filled.shares_released
        )
        assert rows.reservation.cash_released == filled.cash_released + remaining_cash_after_fill
        assert rows.reservation.shares_released == (
            filled.shares_released + remaining_shares_after_fill
        )
        assert (
            rows.reservation.cash_consumed + rows.reservation.cash_released
            == rows.reservation.cash_reserved
        )
        assert (
            rows.reservation.shares_consumed + rows.reservation.shares_released
            == rows.reservation.shares_reserved
        )
        account_after = _account_state(harness.account.pk)
        assert account_after[0] == account_before[0] - trades[0].total_cost
        assert account_after[3] == account_before[3] + 1
        position_after = _position_state(
            account_id=harness.account.pk,
            asset_code=rows.event.asset_code,
        )
        assert position_after[0] == position_before[0] + rows.event.quantity
        assert position_after[1] == position_before[1]
    else:
        assert isinstance(pair.first_result, OrderReservation)
        assert pair.first_result.status is OrderReservationStatus.CANCELLED
        assert pair.waiter_outcome.value is None
        assert pair.waiter_outcome.blocked_code == "ORDER_RESERVATION_TERMINAL"
        assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
        assert len(trades) == 0
        assert len(receipts) == 0
        assert reader.calls == []
        assert rows.reservation.filled_quantity == Decimal("0.000000")
        assert rows.reservation.cash_consumed == Decimal("0.00")
        assert rows.reservation.shares_consumed == Decimal("0.000000")
        assert rows.reservation.cash_released == rows.reservation.cash_reserved
        assert rows.reservation.shares_released == rows.reservation.shares_reserved
        assert _account_state(harness.account.pk) == account_before
        assert (
            _position_state(
                account_id=harness.account.pk,
                asset_code=rows.event.asset_code,
            )
            == position_before
        )

    final_resources = _reservation_resources(rows.reservation)
    repeated_cancel = harness.repository.cancel_order(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
        clock=_FixedClock(_READ_CUTOFF),
    )
    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert repeated_cancel.status is OrderReservationStatus.CANCELLED
    assert _reservation_resources(rows.reservation) == final_resources


def test_postgres_concurrent_first_buys_serialize_position_creation_and_conserve_ledgers(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Two distinct lag-one BUYs create one marked Position under the account lock."""

    del persisted_receipt_schema
    harness = _harness_with_one_session_settlement_lag(reservation_harness)
    first_rows = _reader_rows(harness)
    first_rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)

    second_intent = _intent_for(harness, key="first-buy-concurrent-reservation-002")
    harness.reserve.execute(
        second_intent,
        fee_budget=Decimal("20.00"),
        as_of=AS_OF,
    )
    second_reservation = SimulatedOrderReservationModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=harness.account.pk,
        idempotency_key=second_intent.idempotency_key,
    )
    assert type(first_rows.reservation.pk) is int
    assert type(second_reservation.pk) is int
    assert first_rows.reservation.pk != second_reservation.pk
    second_fill_at = first_rows.event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        first_rows.event,
        source_event_id="first-buy-concurrent-source-event-002",
        event_payload_hash="6" * 64,
        source_snapshot_id="first-buy-concurrent-source-snapshot-002",
        source_snapshot_hash="7" * 64,
        reservation_id=second_reservation.pk,
        account_id=second_reservation.account_id,
        user_id=second_reservation.owner_user_id,
        order_idempotency_key=second_reservation.idempotency_key,
        intent_payload_hash=second_reservation.intent_payload_hash,
        reservation_request_hash=second_reservation.reservation_request_hash,
        plan_snapshot_hash=second_reservation.plan_snapshot_hash,
        security_id=second_reservation.security_id,
        asset_code=second_reservation.asset_code,
        side=SimulatedTradeSide(second_reservation.side),
        quantity=Decimal("20.000000"),
        occurred_at=second_fill_at,
        source_observed_at=second_fill_at,
        source_available_at=second_fill_at,
        recorded_at=second_fill_at,
    )
    second_proof = build_order_fill_settlement_proof(
        calendar_evidence=first_rows.proof.calendar_evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=second_event.occurred_at,
        settlement_exchange=first_rows.proof.settlement_exchange,
        settlement_lag_sessions=first_rows.proof.settlement_lag_sessions,
    )

    _set_consistent_account_mark(harness.account, market_value=Decimal("0.00"))
    assert (
        PositionModel.objects.using(DEFAULT_DB_ALIAS).filter(account_id=harness.account.pk).count()
        == 0
    )
    account_before = _account_state(harness.account.pk)
    assert account_before[1] == Decimal("0.00")
    assert account_before[2] == account_before[0]
    account_before_row = SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS).get(
        pk=harness.account.pk
    )
    assert account_before_row.cash_known is True
    assert account_before_row.cash_reconciliation_status == "simulated_ledger"
    assert first_rows.proof.settlement_lag_sessions == 1
    assert second_proof.settlement_lag_sessions == 1

    first_event_reader = _EventReader(first_rows.event, [])
    second_event_reader = _EventReader(second_event, [])
    mark_reader_first = _InitialPositionMarkReader(
        _initial_position_mark(
            event=first_rows.event,
            reservation=first_rows.reservation,
            read_at=_READ_CUTOFF,
        ),
        [],
    )
    mark_reader_second = _InitialPositionMarkReader(None, [])
    first_repository = DjangoSimulatedOrderFillRepository(
        event_reader=first_event_reader,
        initial_position_mark_reader=mark_reader_first,
        using=DEFAULT_DB_ALIAS,
    )
    second_repository = DjangoSimulatedOrderFillRepository(
        event_reader=second_event_reader,
        initial_position_mark_reader=mark_reader_second,
        using=DEFAULT_DB_ALIAS,
    )

    def apply_first_fill() -> SimulatedOrderFillResult:
        """Apply the first event with the only proof capable of creating a Position."""

        return _invoke(
            first_repository,
            first_rows.event,
            first_rows.proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    def apply_second_fill() -> SimulatedOrderFillResult:
        """Apply a distinct event after the waiting connection acquires the lock."""

        return _invoke(
            second_repository,
            second_event,
            second_proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    pair = _run_first_then_waiter(
        account=harness.account,
        first_operation=apply_first_fill,
        waiting_operation=apply_second_fill,
        thread_name="first-buy-position-create-race",
    )
    assert pair.waiter_pid != pair.holder_pid
    assert pair.lock_wait.wait_event_type == "Lock"
    assert pair.holder_pid in pair.lock_wait.blocker_pids
    assert isinstance(pair.first_result, SimulatedOrderFillResult)
    assert pair.first_result.replayed is False
    assert pair.waiter_outcome.blocked_code is None
    assert isinstance(pair.waiter_outcome.value, SimulatedOrderFillResult)
    second_result = pair.waiter_outcome.value
    assert second_result.replayed is False
    assert len(first_event_reader.calls) == 1
    assert len(second_event_reader.calls) == 1
    assert mark_reader_first.calls == [
        (
            first_rows.event.security_id,
            first_rows.event.asset_code,
            first_rows.reservation.asset_type,
            first_rows.reservation.market,
            first_rows.reservation.board,
            _READ_CUTOFF,
        )
    ]
    assert mark_reader_second.calls == []

    positions = list(
        PositionModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=harness.account.pk)
        .order_by("pk")
    )
    assert len(positions) == 1
    position = positions[0]
    trades = list(
        SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=harness.account.pk)
        .order_by("pk")
    )
    receipts = list(
        SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade__account_id=harness.account.pk)
        .order_by("reservation_id")
    )
    assert len(trades) == 2
    assert len(receipts) == 2
    assert {receipt.reservation_id for receipt in receipts} == {
        first_rows.reservation.pk,
        second_reservation.pk,
    }
    trade_by_id = {trade.pk: trade for trade in trades}
    receipt_by_reservation = {receipt.reservation_id: receipt for receipt in receipts}
    first_receipt = receipt_by_reservation[first_rows.reservation.pk]
    second_receipt = receipt_by_reservation[second_reservation.pk]
    first_trade = trade_by_id[first_receipt.trade_id]
    second_trade = trade_by_id[second_receipt.trade_id]
    assert first_receipt.fill_sequence == second_receipt.fill_sequence == 1
    assert first_receipt.receipt_version == 2
    assert second_receipt.receipt_version == 1
    assert first_receipt.initial_position_mark_evidence is not None
    assert second_receipt.initial_position_mark_evidence is None
    assert first_receipt.source_event_id == first_rows.event.source_event_id
    assert second_receipt.source_event_id == second_event.source_event_id
    assert first_receipt.trade_id == first_trade.pk
    assert second_receipt.trade_id == second_trade.pk
    assert first_receipt.receipt_hash == first_trade.request_payload_hash
    assert second_receipt.receipt_hash == second_trade.request_payload_hash

    expected_quantities = (first_rows.event.quantity, second_event.quantity)
    for trade, quantity in zip(trades, expected_quantities, strict=True):
        component_fees = sum(
            (
                value if value is not None else Decimal("0.00")
                for value in (
                    trade.commission,
                    trade.transfer_fee,
                    trade.stamp_duty,
                    trade.slippage,
                )
            ),
            Decimal("0.00"),
        )
        assert trade.quantity == quantity
        assert trade.amount == trade.quantity * trade.price
        assert trade.total_cost == trade.amount + component_fees
        assert component_fees > Decimal("0.00")
        assert trade.settlement_status == "pending"
        assert trade.settlement_lag_sessions == 1
        assert trade.settlement_release_date == first_rows.proof.expected_release_session
    total_fees = sum(
        (
            trade.commission
            + (trade.transfer_fee or Decimal("0.00"))
            + (trade.stamp_duty or Decimal("0.00"))
            + trade.slippage
            for trade in trades
        ),
        Decimal("0.00"),
    )
    total_cost = sum((trade.total_cost for trade in trades), Decimal("0.00"))
    assert total_cost == sum((trade.amount for trade in trades), Decimal("0.00")) + total_fees
    assert total_cost == first_trade.total_cost + second_trade.total_cost

    position.refresh_from_db(using=DEFAULT_DB_ALIAS)
    expected_quantity = first_rows.event.quantity + second_event.quantity
    assert position.quantity == expected_quantity
    assert position.available_quantity == Decimal("0.000000")
    assert position.current_price == Decimal("10.2500")
    assert position.current_price != first_rows.event.price
    assert position.first_buy_date == first_rows.proof.fill_market_session
    assert position.market_value == Decimal("307.50")
    assert position.total_cost == total_cost
    with localcontext() as context:
        context.prec = 80
        expected_average_cost = (total_cost / expected_quantity).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_EVEN,
        )
    assert position.avg_cost == expected_average_cost
    assert position.cost_basis_known is True
    assert position.valuation_known is True
    assert position.unrealized_pnl == position.market_value - position.total_cost

    pending_trades = [trade for trade in trades if trade.settlement_status == "pending"]
    pending_quantity = sum((trade.quantity for trade in pending_trades), Decimal("0.000000"))
    assert len(pending_trades) == 2
    assert pending_quantity == expected_quantity
    assert position.available_quantity + pending_quantity == position.quantity
    account_after = _account_state(harness.account.pk)
    assert account_after[0] == account_before[0] - total_cost
    assert account_after[1] == position.market_value
    assert account_after[2] == account_after[0] + account_after[1]
    assert account_after[3] == account_before[3] + 2

    reservations = list(
        SimulatedOrderReservationModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(pk__in=(first_rows.reservation.pk, second_reservation.pk))
        .order_by("pk")
    )
    assert len(reservations) == 2
    remaining_cash_holds = Decimal("0.00")
    expected_event_by_reservation = {
        first_rows.reservation.pk: first_rows.event,
        second_reservation.pk: second_event,
    }
    expected_trade_by_reservation = {
        first_rows.reservation.pk: first_trade,
        second_reservation.pk: second_trade,
    }
    for reservation in reservations:
        reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
        event = expected_event_by_reservation[reservation.pk]
        trade = expected_trade_by_reservation[reservation.pk]
        assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
        assert reservation.filled_quantity == event.quantity
        assert reservation.cash_consumed == trade.total_cost
        assert reservation.cash_released == Decimal("0.00")
        assert reservation.shares_consumed == Decimal("0.000000")
        assert reservation.shares_released == Decimal("0.000000")
        assert reservation.fee_budget is not None
        assert reservation.cash_reserved == reservation.notional + reservation.fee_budget
        remaining_cash = (
            reservation.cash_reserved - reservation.cash_consumed - reservation.cash_released
        )
        assert remaining_cash > Decimal("0.00")
        assert (
            reservation.cash_consumed + reservation.cash_released + remaining_cash
            == reservation.cash_reserved
        )
        remaining_cash_holds += remaining_cash
    assert account_after[0] >= remaining_cash_holds
