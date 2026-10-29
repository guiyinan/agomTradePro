"""Native PostgreSQL races and migration safety for local daily matching."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from threading import Barrier, Lock, local
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.db import DEFAULT_DB_ALIAS, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    LocalDailyMatchEvidenceKind,
    LocalDailyMatchSourceReference,
    QualifiedLocalDailyMatchInput,
    RecordLocalDailyMatchUseCase,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.application.order_reservation_fill import OrderFillContext
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.domain.order_reservation import OrderReservation, OrderReservationStatus
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF as RESERVATION_AS_OF,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _qualified_input as _storage_qualified_input,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _assert_account_parent_lock_wait,
    _lock_account_parent,
    _submit_worker,
    _wait_for_account_parent_lock,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
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

_SESSION = date(2026, 10, 16)
_MATCH_AS_OF = datetime(2026, 10, 17, 1, 59, tzinfo=UTC)
_BEFORE = ("simulated_trading", "0040_simulated_fee_correction")
_AFTER = ("simulated_trading", "0041_local_daily_match_decisions")
_MATCH_TABLE = LocalDailyMatchModel._meta.db_table
_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)


@pytest.fixture(autouse=True)
def _require_migrated_native_postgres(django_db_use_migrations: bool) -> None:
    """Require the explicitly isolated PostgreSQL test DB with migration 0041."""

    if connection.vendor != "postgresql":
        pytest.skip("local daily-match concurrency and migration tests require PostgreSQL")
    if not django_db_use_migrations:
        pytest.skip("local daily-match tests require real migrations, not a no-migrations schema")
    assert_native_postgres_test_database()
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert _MATCH_TABLE in connection.introspection.table_names()


@pytest.fixture
def _match_history_cleanup(reservation_harness: _Harness) -> Iterator[_Harness]:
    """Remove only this fixture account's append-only rows after each scenario."""

    yield reservation_harness
    account_id = reservation_harness.account.pk
    assert type(account_id) is int
    if _MATCH_TABLE not in connection.introspection.table_names():
        return
    quoted_table = connection.ops.quote_name(_MATCH_TABLE)
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {quoted_table} WHERE account_id = %s",
            [account_id],
        )


@pytest.fixture
def _full_app_registry_for_migration_loader(
    transactional_db: None,
) -> Iterator[None]:
    """Expose migration dependencies while preserving pytest's partial app scope."""

    del transactional_db
    expected_partial_names = tuple(sorted(_PARTIAL_APP_NAMES))
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
            if django_apps.is_installed("apps.strategy"):
                break
        assert django_apps.is_installed("apps.strategy")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


class _FixedClock:
    """Return one fixed aware time for persisted producer and cancellation calls."""

    def now(self) -> datetime:
        """Return the exact source decision cutoff used by these fixtures."""

        return _MATCH_AS_OF


class _QualificationReader:
    """Supply typed preverified inputs and optionally align concurrent source reads."""

    def __init__(
        self,
        values: Mapping[str, QualifiedLocalDailyMatchInput],
        *,
        first_read_barrier: Barrier | None = None,
    ) -> None:
        self._values = dict(values)
        self._first_read_barrier = first_read_barrier
        self._thread_state = local()
        self._calls_lock = Lock()
        self.calls: list[tuple[LocalDailyMatchCommand, datetime]] = []

    def read(
        self,
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
    ) -> QualifiedLocalDailyMatchInput:
        """Return the fixture for this order at both normal and locked reads."""

        del context
        value = self._values[command.order_idempotency_key]
        assert value.as_of == as_of
        if self._first_read_barrier is not None and not getattr(
            self._thread_state, "first_read_complete", False
        ):
            self._first_read_barrier.wait(timeout=10)
            self._thread_state.first_read_complete = True
        with self._calls_lock:
            self.calls.append((command, as_of))
        return value


def _qualified_input(
    *,
    security_id: str,
    source_key: str,
    volume: Decimal = Decimal("1000"),
    participation_rate: Decimal = Decimal("0.1"),
    share_step: Decimal = Decimal("1"),
    close_price: Decimal = Decimal("9.50"),
) -> QualifiedLocalDailyMatchInput:
    """Build an exact storage-fixture input with a source-specific evidence hash."""

    base = _storage_qualified_input(security_id=security_id, close_price=close_price)
    policy = replace(
        base.policy_binding.policy,
        participation_rate=participation_rate,
        share_step=share_step,
    )
    provenance = replace(base.policy_binding.provenance, read_at=_MATCH_AS_OF)
    binding = replace(base.policy_binding, policy=policy, provenance=provenance)
    observation = replace(base.observation, traded_volume=volume)
    evidence = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_PUBLICATION,
        identity=f"price-publication:{source_key}",
        content_hash=sha256(source_key.encode("utf-8")).hexdigest(),
        recorded_at=base.evidence[0].recorded_at,
    )
    return replace(
        base,
        as_of=_MATCH_AS_OF,
        policy_binding=binding,
        observation=observation,
        evidence=(evidence,),
    )


def _command(
    harness: _Harness,
    *,
    operation_key: str,
    order_key: str,
    qmt_binding_id: str | None = None,
) -> LocalDailyMatchCommand:
    """Address one real reservation with an exact owner and session identity."""

    assert type(harness.account.pk) is int
    return LocalDailyMatchCommand(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        order_idempotency_key=order_key,
        operation_key=operation_key,
        session_date=_SESSION,
        qmt_binding_id=qmt_binding_id or str(uuid4()),
    )


def _reserve_order(
    harness: _Harness,
    *,
    order_key: str,
    quantity: Decimal,
) -> SimulatedOrderReservationModel:
    """Accept one real BUY hold through the established reservation use case."""

    intent = _intent_for(
        harness,
        key=order_key,
        quantity=quantity,
        price=Decimal("10.00"),
    )
    harness.reserve.execute(
        intent,
        fee_budget=Decimal("50.00"),
        as_of=RESERVATION_AS_OF,
    )
    row = SimulatedOrderReservationModel._default_manager.get(
        account_id=harness.account.pk,
        idempotency_key=order_key,
    )
    assert row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert row.quantity == quantity
    return row


def _record_use_case(reader: _QualificationReader) -> RecordLocalDailyMatchUseCase:
    """Build the real repository-backed use case around a typed source stub."""

    return RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using=DEFAULT_DB_ALIAS),
        qualification_reader=reader,
        clock=_FixedClock(),
    )


def _rows_for(account_id: int) -> list[LocalDailyMatchModel]:
    """Read this account's persisted decisions in their stable primary-key order."""

    return list(
        LocalDailyMatchModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=account_id)
        .order_by("pk")
    )


def _stored_row_values(row: LocalDailyMatchModel) -> tuple[tuple[str, object], ...]:
    """Snapshot all concrete row fields for an irreversible-migration assertion."""

    return tuple(
        (field.attname, getattr(row, field.attname)) for field in row._meta.concrete_fields
    )


def test_postgres_same_account_operation_race_returns_one_exact_replay(
    _match_history_cleanup: _Harness,
) -> None:
    """Two backend connections serialize one operation into one durable decision."""

    harness = _match_history_cleanup
    reservation = _reserve_order(
        harness,
        order_key="pg-daily-match-replay-order",
        quantity=Decimal("100"),
    )
    command = _command(
        harness,
        operation_key="pg-daily-match-replay-op",
        order_key="pg-daily-match-replay-order",
    )
    reader = _QualificationReader(
        {
            command.order_idempotency_key: _qualified_input(
                security_id=reservation.security_id,
                source_key="replay-source",
            )
        }
    )
    use_case = _record_use_case(reader)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="daily-match-replay") as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            first_worker = _submit_worker(executor, lambda: use_case.execute(command))
            first_wait = _wait_for_account_parent_lock(
                waiter_pid=first_worker.backend_pids[0],
                allowed_blocker_pids=(holder_pid,),
                future=first_worker.future,
            )
            _assert_account_parent_lock_wait(first_wait)
            second_worker = _submit_worker(executor, lambda: use_case.execute(command))
            second_wait = _wait_for_account_parent_lock(
                waiter_pid=second_worker.backend_pids[0],
                allowed_blocker_pids=(holder_pid, first_worker.backend_pids[0]),
                future=second_worker.future,
            )
            _assert_account_parent_lock_wait(second_wait)

        first = first_worker.future.result(timeout=20)
        second = second_worker.future.result(timeout=20)

    assert first.backend_pid != second.backend_pid
    assert first.blocked_code is None
    assert second.blocked_code is None
    assert type(first.value) is LocalDailyMatchDecision
    assert type(second.value) is LocalDailyMatchDecision
    decisions = (first.value, second.value)
    replay_flags = {item.replayed for item in decisions}
    assert replay_flags == {False, True}
    first_decision, second_decision = decisions
    assert first_decision.request_hash == second_decision.request_hash
    assert first_decision.result == second_decision.result
    assert first_decision.event == second_decision.event
    assert len(_rows_for(harness.account.pk)) == 1
    assert 2 <= len(reader.calls) <= 3


def test_postgres_pending_matches_share_account_security_session_capacity_across_sources(
    _match_history_cleanup: _Harness,
) -> None:
    """Pending rows under different source hashes still consume one daily allowance."""

    harness = _match_history_cleanup
    order_keys = ("pg-daily-capacity-a", "pg-daily-capacity-b")
    reservations = tuple(
        _reserve_order(harness, order_key=key, quantity=Decimal("500")) for key in order_keys
    )
    commands = tuple(
        _command(harness, operation_key=f"{key}-operation", order_key=key) for key in order_keys
    )
    inputs = {
        order_keys[0]: _qualified_input(
            security_id=reservations[0].security_id,
            source_key="publication-source-a",
            volume=Decimal("600"),
            participation_rate=Decimal("1"),
            share_step=Decimal("100"),
        ),
        order_keys[1]: _qualified_input(
            security_id=reservations[1].security_id,
            source_key="publication-source-b",
            volume=Decimal("600"),
            participation_rate=Decimal("1"),
            share_step=Decimal("100"),
        ),
    }
    assert inputs[order_keys[0]].observation.observation_id == (
        inputs[order_keys[1]].observation.observation_id
    )
    assert inputs[order_keys[0]].evidence != inputs[order_keys[1]].evidence
    reader = _QualificationReader(inputs, first_read_barrier=Barrier(2))
    use_case = _record_use_case(reader)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="daily-match-capacity") as executor:
        first_worker = _submit_worker(
            executor,
            lambda: use_case.execute(commands[0]),
        )
        second_worker = _submit_worker(
            executor,
            lambda: use_case.execute(commands[1]),
        )
        first = first_worker.future.result(timeout=25)
        second = second_worker.future.result(timeout=25)

    assert first.backend_pid != second.backend_pid
    assert first.blocked_code is None
    assert second.blocked_code is None
    assert type(first.value) is LocalDailyMatchDecision
    assert type(second.value) is LocalDailyMatchDecision
    decisions = (first.value, second.value)
    assert all(item.result.outcome is LocalMatchOutcome.MATCHED for item in decisions)
    assert all(item.event is not None for item in decisions)
    quantities = sorted(item.event.quantity for item in decisions if item.event is not None)
    assert len(quantities) == 2
    assert quantities == [Decimal("100.000000"), Decimal("500.000000")]
    assert sum(quantities, Decimal("0")) == Decimal("600.000000")

    rows = _rows_for(harness.account.pk)
    assert len(rows) == 2
    assert len({row.observation_id for row in rows}) == 1
    assert len({row.observation_source_hash for row in rows}) == 2
    assert {row.outcome for row in rows} == {LocalDailyMatchModel.OUTCOME_MATCHED}
    assert all(row.event_payload is not None for row in rows)
    assert all(row.recorded_at == _MATCH_AS_OF for row in rows)


def test_postgres_same_reservation_cannot_record_one_observation_twice_under_new_operation(
    _match_history_cleanup: _Harness,
) -> None:
    """A new operation key cannot create a second pending event for one order/day."""

    harness = _match_history_cleanup
    reservation = _reserve_order(
        harness,
        order_key="pg-daily-same-order-observation",
        quantity=Decimal("200"),
    )
    binding_id = str(uuid4())
    first_command = _command(
        harness,
        operation_key="pg-daily-same-order-op-a",
        order_key="pg-daily-same-order-observation",
        qmt_binding_id=binding_id,
    )
    replacement_command = _command(
        harness,
        operation_key="pg-daily-same-order-op-b",
        order_key="pg-daily-same-order-observation",
        qmt_binding_id=binding_id,
    )
    qualified = _qualified_input(
        security_id=reservation.security_id,
        source_key="same-order-source",
    )
    use_case = _record_use_case(
        _QualificationReader({first_command.order_idempotency_key: qualified})
    )

    first = use_case.execute(first_command)
    assert first.result.outcome is LocalMatchOutcome.MATCHED
    with pytest.raises(SimulatedTradeIdempotencyConflict):
        use_case.execute(replacement_command)

    rows = _rows_for(harness.account.pk)
    assert len(rows) == 1
    assert rows[0].operation_key == first_command.operation_key
    assert rows[0].observation_id == qualified.observation.observation_id
    assert rows[0].outcome == LocalDailyMatchModel.OUTCOME_MATCHED


def test_postgres_daily_producer_and_cancel_cannot_leave_an_unconsumed_fill_on_released_hold(
    _match_history_cleanup: _Harness,
) -> None:
    """The parent lock commits either a pending event or cancellation, never both."""

    harness = _match_history_cleanup
    reservation = _reserve_order(
        harness,
        order_key="pg-daily-cancel-race-order",
        quantity=Decimal("100"),
    )
    command = _command(
        harness,
        operation_key="pg-daily-cancel-race-op",
        order_key="pg-daily-cancel-race-order",
    )
    reader = _QualificationReader(
        {
            command.order_idempotency_key: _qualified_input(
                security_id=reservation.security_id,
                source_key="cancel-race-source",
            )
        }
    )
    producer = _record_use_case(reader)
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=_FixedClock(),
    )
    producer_worker = None
    cancel_worker = None

    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="daily-match-cancel-race"
    ) as executor:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            holder_pid = _lock_account_parent(harness.account)
            producer_worker = _submit_worker(
                executor,
                lambda: producer.execute(command),
            )
            producer_wait = _wait_for_account_parent_lock(
                waiter_pid=producer_worker.backend_pids[0],
                allowed_blocker_pids=(holder_pid,),
                future=producer_worker.future,
            )
            _assert_account_parent_lock_wait(producer_wait)
            cancel_worker = _submit_worker(
                executor,
                lambda: cancel.execute(
                    account_id=harness.account.pk,
                    user_id=harness.user_id,
                    idempotency_key=command.order_idempotency_key,
                ),
            )
            cancel_wait = _wait_for_account_parent_lock(
                waiter_pid=cancel_worker.backend_pids[0],
                allowed_blocker_pids=(holder_pid, producer_worker.backend_pids[0]),
                future=cancel_worker.future,
            )
            _assert_account_parent_lock_wait(cancel_wait)

        producer_outcome = producer_worker.future.result(timeout=20)
        cancel_outcome = cancel_worker.future.result(timeout=20)

    assert producer_outcome.backend_pid != cancel_outcome.backend_pid
    rows = _rows_for(harness.account.pk)
    reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert reservation.filled_quantity == Decimal("0.000000")

    if producer_outcome.blocked_code is None:
        decision = producer_outcome.value
        assert type(decision) is LocalDailyMatchDecision
        assert decision.result.outcome is LocalMatchOutcome.MATCHED
        assert cancel_outcome.value is None
        assert cancel_outcome.blocked_code == "LOCAL_DAILY_MATCH_PENDING_FILL"
        assert len(rows) == 1
        assert rows[0].outcome == LocalDailyMatchModel.OUTCOME_MATCHED
        assert rows[0].event_payload is not None
        assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
        assert reservation.cash_released == Decimal("0.00")
    else:
        assert producer_outcome.value is None
        assert producer_outcome.blocked_code == "ORDER_RESERVATION_TERMINAL"
        assert cancel_outcome.blocked_code is None
        cancelled = cancel_outcome.value
        assert type(cancelled) is OrderReservation
        assert cancelled.status is OrderReservationStatus.CANCELLED
        assert not rows
        assert reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED


def test_postgres_0041_empty_round_trip_and_history_guard_preserve_actual_decision(
    _match_history_cleanup: _Harness,
    _full_app_registry_for_migration_loader: None,
) -> None:
    """The real migration reverses only while empty and guards stored decisions."""

    del _full_app_registry_for_migration_loader
    harness = _match_history_cleanup
    assert type(harness.account.pk) is int
    assert _MATCH_TABLE in connection.introspection.table_names()
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert not _rows_for(harness.account.pk)

    leaf_nodes = list(MigrationExecutor(connection).loader.graph.leaf_nodes())
    history_pk: int | None = None
    try:
        MigrationExecutor(connection).migrate([_BEFORE])
        assert _MATCH_TABLE not in connection.introspection.table_names()
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert _BEFORE in MigrationRecorder(connection).applied_migrations()

        MigrationExecutor(connection).migrate([_AFTER])
        assert _MATCH_TABLE in connection.introspection.table_names()
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        assert not _rows_for(harness.account.pk)

        reservation = _reserve_order(
            harness,
            order_key="pg-daily-migration-history-order",
            quantity=Decimal("100"),
        )
        command = _command(
            harness,
            operation_key="pg-daily-migration-history-op",
            order_key="pg-daily-migration-history-order",
        )
        qualification = _qualified_input(
            security_id=reservation.security_id,
            source_key="migration-history-source",
            close_price=Decimal("10.50"),
        )
        decision = _record_use_case(
            _QualificationReader({command.order_idempotency_key: qualification})
        ).execute(command)
        assert decision.result.outcome is LocalMatchOutcome.NO_MATCH
        assert decision.event is None
        persisted = _rows_for(harness.account.pk)
        assert len(persisted) == 1
        history_pk = persisted[0].pk
        assert history_pk is not None
        original_values = _stored_row_values(persisted[0])

        with pytest.raises(
            IrreversibleError,
            match="Cannot drop local daily match schema while decision history exists",
        ):
            MigrationExecutor(connection).migrate([_BEFORE])

        assert _MATCH_TABLE in connection.introspection.table_names()
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        retained = LocalDailyMatchModel._base_manager.using(DEFAULT_DB_ALIAS).get(pk=history_pk)
        assert _stored_row_values(retained) == original_values
    finally:
        if _MATCH_TABLE in connection.introspection.table_names():
            quoted_table = connection.ops.quote_name(_MATCH_TABLE)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {quoted_table} WHERE account_id = %s",
                    [harness.account.pk],
                )
        MigrationExecutor(connection).migrate(leaf_nodes)
