"""Native PostgreSQL races for account-scoped simulated order holds."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import (
    DEFAULT_DB_ALIAS,
    close_old_connections,
    connection,
    connections,
    transaction,
)

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationResult,
    OrderReservationStatus,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position as _create_position,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness as _ReservationHarness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _intent_for as _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True)
class _WorkerOutcome:
    """Return one thread's actual backend identity and business result."""

    backend_pid: int
    value: object | None
    blocked_code: str | None


@dataclass(frozen=True)
class _WorkerCall:
    """Keep a worker future and its independently opened PostgreSQL backend."""

    backend_pids: list[int]
    future: Future[_WorkerOutcome]


@dataclass(frozen=True)
class _AccountParentLockWait:
    """Preserve the PostgreSQL catalog evidence for a real parent-row waiter."""

    query: str
    blocker_pids: tuple[int, ...]
    wait_event_type: str
    relation_oid: int
    relation_lock_mode: str
    relation_lock_granted: bool
    account_table: str


@pytest.fixture(autouse=True)
def _require_migrated_native_postgres(django_db_use_migrations: bool) -> None:
    """Run row-lock claims only against the explicitly configured PostgreSQL test DB."""

    if not django_db_use_migrations:
        pytest.skip("simulated order-reservation races require the migrated test database")
    if connection.vendor != "postgresql":
        pytest.skip("simulated order-reservation row-lock races require PostgreSQL")
    assert_native_postgres_test_database()


def _lock_account_parent(account: SimulatedAccountModel) -> int:
    """Hold the real simulated-account parent row and return this backend PID."""

    assert connection.in_atomic_block
    assert type(account.pk) is int
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        pid_row = cursor.fetchone()
    assert pid_row is not None and type(pid_row[0]) is int
    SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS).select_for_update().get(
        pk=account.pk
    )
    return int(pid_row[0])


def _execute_on_fresh_thread_connection(
    operation: Callable[[], object],
    connected: Event,
    backend_pids: list[int],
) -> _WorkerOutcome:
    """Run a real service call using a fresh, bounded thread-local DB connection."""

    close_old_connections()
    worker_connection = connections[DEFAULT_DB_ALIAS]
    try:
        with worker_connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '8000ms'")
            cursor.execute("SET statement_timeout = '15000ms'")
            cursor.execute("SELECT pg_backend_pid()")
            pid_row = cursor.fetchone()
        assert pid_row is not None and type(pid_row[0]) is int
        backend_pid = int(pid_row[0])
        backend_pids.append(backend_pid)
        connected.set()
        try:
            value = operation()
        except SimulatedTradeExecutionBlocked as error:
            return _WorkerOutcome(
                backend_pid=backend_pid,
                value=None,
                blocked_code=error.code,
            )
        return _WorkerOutcome(
            backend_pid=backend_pid,
            value=value,
            blocked_code=None,
        )
    finally:
        worker_connection.close()


def _submit_worker(
    executor: ThreadPoolExecutor,
    operation: Callable[[], object],
) -> _WorkerCall:
    """Start one operation and wait a bounded time for its separate backend PID."""

    connected = Event()
    backend_pids: list[int] = []
    future = executor.submit(
        _execute_on_fresh_thread_connection,
        operation,
        connected,
        backend_pids,
    )
    if not connected.wait(timeout=5):
        if future.done():
            future.result()
        raise AssertionError("worker did not open its PostgreSQL connection within five seconds")
    assert len(backend_pids) == 1
    return _WorkerCall(backend_pids=backend_pids, future=future)


def _wait_for_account_parent_lock(
    *,
    waiter_pid: int,
    allowed_blocker_pids: tuple[int, ...],
    future: Future[_WorkerOutcome],
) -> _AccountParentLockWait:
    """Observe a real parent wait using activity and relation-lock catalog evidence."""

    deadline = monotonic() + 6.0
    last_query = ""
    last_blockers: tuple[int, ...] = ()
    last_wait_event: str | None = None
    last_relation_oid: int | None = None
    last_lock_mode: str | None = None
    last_lock_granted: bool | None = None
    table_name = SimulatedAccountModel._meta.db_table.lower()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT activity.wait_event_type, activity.query, "
                "pg_blocking_pids(activity.pid), relation_lock.relation, "
                "relation_lock.mode, relation_lock.granted "
                "FROM pg_stat_activity AS activity "
                "JOIN pg_locks AS relation_lock ON relation_lock.pid = activity.pid "
                "WHERE activity.pid = %s "
                "AND relation_lock.locktype = 'relation' "
                "AND relation_lock.database = ("
                "SELECT oid FROM pg_database WHERE datname = current_database()"
                ") "
                "AND relation_lock.relation = to_regclass(%s)::oid "
                "AND relation_lock.mode = 'RowShareLock' "
                "ORDER BY relation_lock.granted DESC",
                [waiter_pid, table_name],
            )
            row = cursor.fetchone()
        if row is not None and len(row) == 6:
            (
                wait_value,
                query_value,
                blocker_value,
                relation_oid_value,
                lock_mode_value,
                lock_granted_value,
            ) = row
            last_wait_event = wait_value if isinstance(wait_value, str) else None
            last_query = query_value if isinstance(query_value, str) else ""
            if isinstance(blocker_value, (list, tuple)):
                last_blockers = tuple(int(pid) for pid in blocker_value)
            else:
                last_blockers = ()
            last_relation_oid = relation_oid_value if type(relation_oid_value) is int else None
            last_lock_mode = lock_mode_value if isinstance(lock_mode_value, str) else None
            last_lock_granted = lock_granted_value if type(lock_granted_value) is bool else None
            query_lower = last_query.lstrip().lower()
            query_prefix = query_lower[:512]
            is_expected_query = query_prefix.startswith("select ") and table_name in query_prefix
            has_expected_blocker = any(pid in last_blockers for pid in allowed_blocker_pids)
            has_expected_relation_lock = (
                last_relation_oid is not None
                and last_lock_mode == "RowShareLock"
                and last_lock_granted is True
            )
            if (
                last_wait_event == "Lock"
                and is_expected_query
                and has_expected_blocker
                and has_expected_relation_lock
            ):
                assert last_wait_event is not None
                assert last_relation_oid is not None
                assert last_lock_mode is not None
                assert last_lock_granted is True
                return _AccountParentLockWait(
                    query=last_query,
                    blocker_pids=last_blockers,
                    wait_event_type=last_wait_event,
                    relation_oid=last_relation_oid,
                    relation_lock_mode=last_lock_mode,
                    relation_lock_granted=last_lock_granted,
                    account_table=SimulatedAccountModel._meta.db_table,
                )
        if future.done():
            finished = future.result()
            raise AssertionError(
                "worker completed before PostgreSQL reported the parent-row lock wait: "
                f"{finished!r}"
            )
        sleep(0.02)
    raise AssertionError(
        "worker did not wait on the locked simulated-account row; "
        f"wait_event={last_wait_event!r}, blockers={last_blockers!r}, "
        f"relation_oid={last_relation_oid!r}, lock_mode={last_lock_mode!r}, "
        f"lock_granted={last_lock_granted!r}, query={last_query!r}"
    )


def _assert_account_parent_lock_wait(wait: _AccountParentLockWait) -> None:
    """Assert the observation identifies a SELECT and lock on the account table."""

    assert wait.wait_event_type == "Lock"
    assert wait.relation_oid > 0
    assert wait.relation_lock_mode == "RowShareLock"
    assert wait.relation_lock_granted is True
    query_prefix = wait.query.lstrip().lower()[:512]
    assert wait.account_table.lower() in query_prefix
    assert query_prefix.startswith("select ")


def _reservation_rows(account_id: int) -> list[SimulatedOrderReservationModel]:
    """Read persisted reservation rows in stable order for final accounting assertions."""

    return list(
        SimulatedOrderReservationModel._default_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=account_id)
        .order_by("pk")
    )


def test_postgres_competing_buy_reservations_cannot_double_spend_cash(
    reservation_harness: _ReservationHarness,
) -> None:
    """A second BUY waits for the account lock and sees the first committed cash hold."""

    harness = reservation_harness
    first_intent = _intent_for(
        harness,
        key="pg-buy-hold-first",
        quantity=Decimal("5000"),
    )
    second_intent = _intent_for(
        harness,
        key="pg-buy-hold-second",
        quantity=Decimal("5000"),
    )
    fee_budget = Decimal("100.00")
    worker: _WorkerCall | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="buy-reservation-race") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            first = harness.reserve.execute(
                first_intent,
                fee_budget=fee_budget,
                as_of=AS_OF,
            )
            assert first.reservation.cash_reserved == Decimal("50100.00")
            worker = _submit_worker(
                executor,
                lambda: harness.reserve.execute(
                    second_intent,
                    fee_budget=fee_budget,
                    as_of=AS_OF,
                ),
            )
            waiter_pid = worker.backend_pids[0]
            assert waiter_pid != holder_pid
            wait = _wait_for_account_parent_lock(
                waiter_pid=waiter_pid,
                allowed_blocker_pids=(holder_pid,),
                future=worker.future,
            )
            _assert_account_parent_lock_wait(wait)
            assert holder_pid in wait.blocker_pids

        assert worker is not None
        outcome = worker.future.result(timeout=20)

    assert outcome.backend_pid != holder_pid
    assert outcome.value is None
    assert outcome.blocked_code is not None
    rows = _reservation_rows(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].idempotency_key == first_intent.idempotency_key
    assert rows[0].status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows[0].cash_reserved == Decimal("50100.00")
    assert rows[0].cash_released == Decimal("0.00")
    harness.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert harness.account.current_cash == Decimal("100000.00")
    assert SimulatedTradeModel._default_manager.filter(account_id=harness.account.pk).count() == 0


def test_postgres_competing_sell_reservations_cannot_double_hold_settled_shares(
    reservation_harness: _ReservationHarness,
) -> None:
    """A second SELL rechecks settled availability after waiting for the account lock."""

    harness = reservation_harness
    position = _create_position(harness.account)
    first_intent = _intent_for(
        harness,
        side=SimulatedTradeSide.SELL,
        key="pg-sell-hold-first",
        quantity=Decimal("100"),
    )
    second_intent = _intent_for(
        harness,
        side=SimulatedTradeSide.SELL,
        key="pg-sell-hold-second",
        quantity=Decimal("100"),
    )
    worker: _WorkerCall | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sell-reservation-race") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            first = harness.reserve.execute(first_intent, fee_budget=None, as_of=AS_OF)
            assert first.reservation.shares_reserved == Decimal("100.000000")
            assert first.book.available_shares == Decimal("0.000000")
            worker = _submit_worker(
                executor,
                lambda: harness.reserve.execute(second_intent, fee_budget=None, as_of=AS_OF),
            )
            waiter_pid = worker.backend_pids[0]
            assert waiter_pid != holder_pid
            wait = _wait_for_account_parent_lock(
                waiter_pid=waiter_pid,
                allowed_blocker_pids=(holder_pid,),
                future=worker.future,
            )
            _assert_account_parent_lock_wait(wait)
            assert holder_pid in wait.blocker_pids

        assert worker is not None
        outcome = worker.future.result(timeout=20)

    assert outcome.backend_pid != holder_pid
    assert outcome.value is None
    assert outcome.blocked_code is not None
    rows = _reservation_rows(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].idempotency_key == first_intent.idempotency_key
    assert rows[0].status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows[0].shares_reserved == Decimal("100.000000")
    position.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("100.000000")
    harness.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert harness.account.current_cash == Decimal("100000.00")
    assert SimulatedTradeModel._default_manager.filter(account_id=harness.account.pk).count() == 0


@pytest.mark.parametrize(
    ("side", "quantity", "fee_budget"),
    [
        pytest.param(
            SimulatedTradeSide.BUY,
            Decimal("5000"),
            Decimal("100.00"),
            id="held-buy-cash",
        ),
        pytest.param(
            SimulatedTradeSide.SELL,
            Decimal("100"),
            None,
            id="held-sell-shares",
        ),
    ],
)
def test_postgres_order_hold_serializes_ordinary_legacy_execution(
    reservation_harness: _ReservationHarness,
    side: SimulatedTradeSide,
    quantity: Decimal,
    fee_budget: Decimal | None,
) -> None:
    """A real ordinary UoW cannot spend cash or shares retained by an active order."""

    harness = reservation_harness
    if side is SimulatedTradeSide.SELL:
        _create_position(harness.account)
    held_intent = _intent_for(
        harness,
        side=side,
        key=f"pg-held-{side.value}",
        quantity=quantity,
    )
    ordinary_intent = _intent_for(
        harness,
        side=side,
        key=f"pg-ordinary-{side.value}",
        quantity=quantity,
    )
    worker: _WorkerCall | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ordinary-trade-race") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            held = harness.reserve.execute(
                held_intent,
                fee_budget=fee_budget,
                as_of=AS_OF,
            )
            worker = _submit_worker(
                executor,
                lambda: harness.preparer.execute(ordinary_intent, as_of=AS_OF),
            )
            waiter_pid = worker.backend_pids[0]
            assert waiter_pid != holder_pid
            wait = _wait_for_account_parent_lock(
                waiter_pid=waiter_pid,
                allowed_blocker_pids=(holder_pid,),
                future=worker.future,
            )
            _assert_account_parent_lock_wait(wait)
            assert holder_pid in wait.blocker_pids

        assert worker is not None
        outcome = worker.future.result(timeout=20)

    assert outcome.backend_pid != holder_pid
    assert outcome.value is None
    if side is SimulatedTradeSide.SELL:
        assert outcome.blocked_code == "ORDER_RESERVATION_ACTIVE"
        assert held.reservation.shares_reserved == Decimal("100.000000")
        position = PositionModel._default_manager.get(
            account_id=harness.account.pk,
            asset_code=held_intent.asset_code,
        )
        assert position.quantity == Decimal("100.000000")
        assert position.available_quantity == Decimal("100.000000")
    else:
        assert outcome.blocked_code == "SIMULATED_TRADE_EXECUTION_BLOCKED"
        assert held.reservation.cash_reserved == Decimal("50100.00")
        assert PositionModel._default_manager.filter(account_id=harness.account.pk).count() == 0
    rows = _reservation_rows(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].idempotency_key == held_intent.idempotency_key
    assert rows[0].status == SimulatedOrderReservationModel.STATUS_ACTIVE
    harness.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert harness.account.current_cash == Decimal("100000.00")
    assert SimulatedTradeModel._default_manager.filter(account_id=harness.account.pk).count() == 0


def test_postgres_cancel_competition_and_terminal_reserve_replay_release_once(
    reservation_harness: _ReservationHarness,
) -> None:
    """Concurrent cancels serialize, and terminal replay cannot release or reopen twice."""

    harness = reservation_harness
    intent = _intent_for(harness, key="pg-cancel-replay-once")
    created = harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    initial_reserved_cash = created.reservation.cash_reserved
    assert initial_reserved_cash == Decimal("1005.00")
    cancel_clock = _FixedClock(AS_OF + timedelta(minutes=1))

    def cancel_once() -> object:
        """Run the real owner-scoped cancellation use case on a worker connection."""

        return CancelSimulatedOrderReservationUseCase(
            repository=harness.repository,
            clock=cancel_clock,
        ).execute(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            idempotency_key=intent.idempotency_key,
        )

    workers: list[_WorkerCall] = []
    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="cancel-reservation-race",
    ) as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            first_worker = _submit_worker(executor, cancel_once)
            workers.append(first_worker)
            first_pid = first_worker.backend_pids[0]
            assert first_pid != holder_pid
            first_wait = _wait_for_account_parent_lock(
                waiter_pid=first_pid,
                allowed_blocker_pids=(holder_pid,),
                future=first_worker.future,
            )
            _assert_account_parent_lock_wait(first_wait)
            assert holder_pid in first_wait.blocker_pids

            second_worker = _submit_worker(executor, cancel_once)
            workers.append(second_worker)
            second_pid = second_worker.backend_pids[0]
            assert second_pid not in (holder_pid, first_pid)
            second_wait = _wait_for_account_parent_lock(
                waiter_pid=second_pid,
                allowed_blocker_pids=(holder_pid, first_pid),
                future=second_worker.future,
            )
            _assert_account_parent_lock_wait(second_wait)
            assert any(pid in (holder_pid, first_pid) for pid in second_wait.blocker_pids)

        outcomes = [worker.future.result(timeout=20) for worker in workers]

    assert all(outcome.value is not None for outcome in outcomes)
    assert all(outcome.blocked_code is None for outcome in outcomes)
    assert type(outcomes[0].value) is OrderReservation
    assert type(outcomes[1].value) is OrderReservation
    first_cancelled = outcomes[0].value
    second_cancelled = outcomes[1].value
    assert first_cancelled == second_cancelled
    assert first_cancelled.status is OrderReservationStatus.CANCELLED
    assert first_cancelled.cash_released == initial_reserved_cash
    assert first_cancelled.cash_consumed == Decimal("0.00")
    assert first_cancelled.shares_released == Decimal("0.000000")

    replay = harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    repeated_cancel = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=cancel_clock,
    ).execute(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=intent.idempotency_key,
    )
    assert type(replay) is OrderReservationResult
    assert replay.replayed is True
    assert replay.reservation == first_cancelled
    assert repeated_cancel == first_cancelled

    rows = _reservation_rows(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert rows[0].cash_reserved == initial_reserved_cash
    assert rows[0].cash_released == initial_reserved_cash
    assert rows[0].cash_consumed == Decimal("0.00")
    assert rows[0].shares_reserved == Decimal("0.000000")
    assert rows[0].shares_released == Decimal("0.000000")
    harness.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert harness.account.current_cash == Decimal("100000.00")
    assert SimulatedTradeModel._default_manager.filter(account_id=harness.account.pk).count() == 0


def test_postgres_cancel_races_same_key_reserve_replay_without_reopening_hold(
    reservation_harness: _ReservationHarness,
) -> None:
    """A concurrent exact reserve replay cannot reopen a hold being cancelled."""

    harness = reservation_harness
    intent = _intent_for(harness, key="pg-cancel-reserve-race")
    created = harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    initial_reserved_cash = created.reservation.cash_reserved
    assert initial_reserved_cash == Decimal("1005.00")
    cancel_clock = _FixedClock(AS_OF + timedelta(minutes=1))

    def cancel_once() -> object:
        """Run the real owner-scoped cancellation use case on its own connection."""

        return CancelSimulatedOrderReservationUseCase(
            repository=harness.repository,
            clock=cancel_clock,
        ).execute(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            idempotency_key=intent.idempotency_key,
        )

    def replay_same_key() -> object:
        """Run the exact original reservation request as a concurrent replay."""

        return harness.reserve.execute(
            intent,
            fee_budget=Decimal("5.00"),
            as_of=AS_OF,
        )

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cancel-reserve-race") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            cancel_worker = _submit_worker(executor, cancel_once)
            cancel_pid = cancel_worker.backend_pids[0]
            assert cancel_pid != holder_pid
            cancel_wait = _wait_for_account_parent_lock(
                waiter_pid=cancel_pid,
                allowed_blocker_pids=(holder_pid,),
                future=cancel_worker.future,
            )
            _assert_account_parent_lock_wait(cancel_wait)
            assert holder_pid in cancel_wait.blocker_pids

            reserve_worker = _submit_worker(executor, replay_same_key)
            reserve_pid = reserve_worker.backend_pids[0]
            assert reserve_pid not in (holder_pid, cancel_pid)
            reserve_wait = _wait_for_account_parent_lock(
                waiter_pid=reserve_pid,
                allowed_blocker_pids=(holder_pid, cancel_pid),
                future=reserve_worker.future,
            )
            _assert_account_parent_lock_wait(reserve_wait)
            assert any(pid in (holder_pid, cancel_pid) for pid in reserve_wait.blocker_pids)

        cancel_outcome = cancel_worker.future.result(timeout=20)
        reserve_outcome = reserve_worker.future.result(timeout=20)

    assert cancel_outcome.backend_pid != reserve_outcome.backend_pid
    assert cancel_outcome.blocked_code is None
    assert type(cancel_outcome.value) is OrderReservation
    cancelled = cancel_outcome.value
    assert cancelled.status is OrderReservationStatus.CANCELLED
    assert cancelled.cash_released == initial_reserved_cash
    assert cancelled.cash_consumed == Decimal("0.00")
    assert reserve_outcome.blocked_code is None
    assert type(reserve_outcome.value) is OrderReservationResult
    concurrent_replay = reserve_outcome.value
    assert concurrent_replay.replayed is True
    assert concurrent_replay.reservation.status in (
        OrderReservationStatus.ACTIVE,
        OrderReservationStatus.CANCELLED,
    )

    terminal_replay = harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    repeated_cancel = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=cancel_clock,
    ).execute(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=intent.idempotency_key,
    )
    assert terminal_replay.replayed is True
    assert terminal_replay.reservation == cancelled
    assert repeated_cancel == cancelled

    rows = _reservation_rows(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert rows[0].cash_reserved == initial_reserved_cash
    assert rows[0].cash_released == initial_reserved_cash
    assert rows[0].cash_consumed == Decimal("0.00")
    assert rows[0].shares_reserved == Decimal("0.000000")
    assert rows[0].shares_released == Decimal("0.000000")
    harness.account.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert harness.account.current_cash == Decimal("100000.00")
    assert SimulatedTradeModel._default_manager.filter(account_id=harness.account.pk).count() == 0


@dataclass(frozen=True)
class _FixedClock:
    """Return one deterministic aware instant to a cancellation use case."""

    current: datetime

    def now(self) -> datetime:
        """Return the injected aware instant without relying on wall-clock time."""

        return self.current
