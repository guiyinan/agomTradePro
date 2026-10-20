"""Native PostgreSQL concurrency contracts for persisted local order fills."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import pytest
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.order_reservation_fill import (
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
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
