"""Native PostgreSQL actor revocation races for simulated-order reservations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from time import monotonic, sleep

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.simulated_trading.domain.order_reservation import OrderReservationResult
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF, _Clock
from tests.component.simulated_trading.test_order_reservation_actor_authority import (
    _ledger_state,
)
from tests.component.simulated_trading.test_order_reservation_actor_authority import (
    ledger as ledger,
)
from tests.component.simulated_trading.test_order_reservation_actor_authority import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_order_reservation_actor_authority import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _submit_worker,
    _WorkerCall,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
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


def _assert_waiting_for_actor(worker: _WorkerCall, holder_pid: int) -> None:
    """Observe the real user SELECT FOR UPDATE blocked by the revoking connection."""
    deadline = monotonic() + 6
    table = get_user_model()._meta.db_table.lower()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT wait_event_type, query, pg_blocking_pids(pid) "
                "FROM pg_stat_activity WHERE pid = %s",
                [worker.backend_pids[0]],
            )
            row = cursor.fetchone()
        if row is not None and row[0] == "Lock" and holder_pid in row[2]:
            query = row[1].lower()
            assert query.lstrip().startswith("select ")
            assert table in query and "for update" in query
            return
        if worker.future.done():
            pytest.fail(f"reservation bypassed the locked actor: {worker.future.result()!r}")
        sleep(0.02)
    pytest.fail("reservation did not wait on the locked current user")


@pytest.mark.parametrize("operation", ["create", "lookup_replay", "writer_replay"])
@pytest.mark.parametrize("deactivate", [True, False])
def test_reservation_serializes_with_current_actor_revocation(
    reservation_harness: _Harness,
    django_db_use_migrations: bool,
    operation: str,
    deactivate: bool,
) -> None:
    """All Reserve entries wait for the actual user row and use its committed state."""
    if connection.vendor != "postgresql":
        pytest.skip("actor row-lock proof requires native PostgreSQL")
    assert django_db_use_migrations
    assert_native_postgres_test_database()
    harness = reservation_harness
    intent = _intent_for(harness, key="actor-lock-reservation")
    prepared = harness.preparer.prepare(intent, as_of=AS_OF)
    if operation != "create":
        harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    before = _ledger_state(harness)

    def reserve() -> object:
        if operation == "lookup_replay":
            return harness.repository.find_idempotent_reservation(
                intent=intent, fee_budget=Decimal("5.00")
            )
        return harness.repository.reserve_order(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            fee_budget=Decimal("5.00"),
            clock=_Clock(AS_OF),
        )

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="reservation-actor") as executor:
        with transaction.atomic():
            actor = get_user_model()._base_manager.select_for_update().get(pk=harness.user_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                holder_pid = cursor.fetchone()[0]
            worker = _submit_worker(executor, reserve)
            _assert_waiting_for_actor(worker, holder_pid)
            if deactivate:
                actor.is_active = False
                actor.save(update_fields=["is_active"])
        outcome = worker.future.result(timeout=20)

    if deactivate:
        assert outcome.blocked_code == "SIMULATED_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"
        assert outcome.value is None
        assert _ledger_state(harness) == before
    else:
        assert outcome.blocked_code is None
        assert isinstance(outcome.value, OrderReservationResult)
        assert outcome.value.replayed is (operation != "create")
        assert outcome.value.reservation.cash_reserved == Decimal("1005.00")
        if operation != "create":
            assert _ledger_state(harness) == before
