"""Native PostgreSQL serialization of owner Apply and Cancel operations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.db import connection, transaction

from apps.simulated_trading.application.owner_order_operations import OwnerOrderFillApplied
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import SimulatedTradeModel
from tests.component.simulated_trading.test_order_decision_history_api import (
    _OrderDecisionHistoryCase,
)
from tests.component.simulated_trading.test_order_decision_history_api import ledger as ledger
from tests.component.simulated_trading.test_order_decision_history_api import (
    local_daily_match_schema as local_daily_match_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    order_decision_history_case as order_decision_history_case,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _assert_account_parent_lock_wait,
    _lock_account_parent,
    _submit_worker,
    _wait_for_account_parent_lock,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)


def test_owner_apply_and_cancel_serialize_without_losing_the_saved_fill(
    order_decision_history_case: _OrderDecisionHistoryCase,
    django_db_use_migrations: bool,
) -> None:
    """Two real connections wait on the parent, then settle once and release only 90."""
    if connection.vendor != "postgresql":
        pytest.skip("row-lock proof requires native PostgreSQL")
    assert django_db_use_migrations
    assert_native_postgres_test_database()
    from tests.component.simulated_trading.test_owner_order_operations_api import (
        build_owner_operations,
    )

    case = order_decision_history_case
    use_case = build_owner_operations(case)
    decision_id = LocalDailyMatchModel._base_manager.get(
        reservation_id=case.order.pk, operation_key=case.matched.command.operation_key
    ).pk
    scope = {
        "account_id": case.harness.account.pk,
        "user_id": case.harness.user_id,
        "order_id": case.order.pk,
    }

    def apply() -> object:
        return use_case.apply_retained_fill(**scope, decision_id=decision_id, confirmed=True)

    def cancel() -> object:
        return use_case.cancel_remaining(**scope, confirmed=True)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="owner-order-operation") as executor:
        with transaction.atomic():
            holder = _lock_account_parent(case.harness.account)
            apply_worker = _submit_worker(executor, apply)
            _assert_account_parent_lock_wait(
                _wait_for_account_parent_lock(
                    waiter_pid=apply_worker.backend_pids[0],
                    allowed_blocker_pids=(holder,),
                    future=apply_worker.future,
                )
            )
            cancel_worker = _submit_worker(executor, cancel)
            _assert_account_parent_lock_wait(
                _wait_for_account_parent_lock(
                    waiter_pid=cancel_worker.backend_pids[0],
                    allowed_blocker_pids=(holder, apply_worker.backend_pids[0]),
                    future=cancel_worker.future,
                )
            )
        applied = apply_worker.future.result(timeout=20)
        cancelled = cancel_worker.future.result(timeout=20)

    assert type(applied.value) is OwnerOrderFillApplied
    assert applied.blocked_code is None
    # Cancel may get the writer first and correctly block on the saved pending event.
    # Retrying the same order after Apply must release precisely the current remainder.
    if cancelled.blocked_code is not None:
        assert "PENDING" in cancelled.blocked_code
    terminal = use_case.cancel_remaining(**scope, confirmed=True)
    assert terminal.reservation.status is OrderReservationStatus.CANCELLED
    assert terminal.reservation.filled_quantity == Decimal("10.000000")
    assert terminal.reservation.shares_consumed == Decimal("10.000000")
    assert terminal.reservation.shares_released == Decimal("90.000000")
    assert terminal.reservation.cash_released == Decimal("0.00")
    repeat = use_case.apply_retained_fill(**scope, decision_id=decision_id, confirmed=True)
    assert repeat.result.replayed is True
    assert repeat.result.trade_id == applied.value.result.trade_id
    assert repeat.result.reservation == terminal.reservation
    assert use_case.cancel_remaining(**scope, confirmed=True) == terminal
    assert SimulatedTradeModel._base_manager.filter(account_id=case.harness.account.pk).count() == 1
    assert (
        SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=case.order.pk).count()
        == 1
    )
