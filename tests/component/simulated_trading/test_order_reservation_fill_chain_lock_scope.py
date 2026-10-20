"""Reject cross-account receipt links without locking the foreign Trade row."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from decimal import Decimal
from threading import Event

import pytest
from django.db import DEFAULT_DB_ALIAS, connection, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    validate_locked_order_fill_chain,
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
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_concurrency import (
    _submit_worker,
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
    _Rows,
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
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True, slots=True)
class _CrossAccountReceipt:
    """Keep the valid chain rows and deliberately corrupt linked Trade."""

    harness: _Harness
    rows: _Rows
    foreign_account: SimulatedAccountModel
    foreign_trade: SimulatedTradeModel


@pytest.fixture
def _require_native_postgres(django_db_use_migrations: bool) -> None:
    """Run lock-scope timing only against the qualified migrated PostgreSQL DB."""

    if not django_db_use_migrations or connection.vendor != "postgresql":
        pytest.skip("cross-account Trade lock-scope check requires native PostgreSQL")
    assert_native_postgres_test_database()


def _prepare_cross_account_receipt(harness: _Harness) -> _CrossAccountReceipt:
    """Persist one valid BUY, then rewire its immutable receipt to another account."""

    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    rows.reservation.refresh_from_db(using=DEFAULT_DB_ALIAS)
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        using=DEFAULT_DB_ALIAS,
    )
    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert result.replayed is False
    assert type(result.trade_id) is int

    foreign_account = SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS).create(
        user_id=harness.user_id,
        account_name="Foreign receipt lock-scope fixture",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        auto_trading_enabled=False,
    )
    foreign_trade = SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS).create(
        account=foreign_account,
        asset_code=rows.event.asset_code,
        asset_name="Foreign fixture Trade",
        asset_type="equity",
        action=SimulatedTradeSide.BUY.value,
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("10.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("10.00"),
        order_date=AS_OF.date(),
        execution_date=AS_OF.date(),
        execution_time=AS_OF,
        status="executed",
    )
    receipt = SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS).get(
        reservation_id=rows.reservation.pk,
        source_namespace=rows.event.source_namespace,
        source_event_id=rows.event.source_event_id,
    )
    receipt_table = connection.ops.quote_name(SimulatedOrderFillReceiptModel._meta.db_table)
    receipt_trade_column = connection.ops.quote_name(
        SimulatedOrderFillReceiptModel._meta.get_field("trade").column
    )
    receipt_pk_column = connection.ops.quote_name(SimulatedOrderFillReceiptModel._meta.pk.column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {receipt_table} SET {receipt_trade_column} = %s "
            f"WHERE {receipt_pk_column} = %s",
            [foreign_trade.pk, receipt.pk],
        )
    receipt.refresh_from_db(using=DEFAULT_DB_ALIAS)
    assert receipt.trade_id == foreign_trade.pk
    return _CrossAccountReceipt(
        harness=harness,
        rows=rows,
        foreign_account=foreign_account,
        foreign_trade=foreign_trade,
    )


def _financial_snapshot(
    *,
    account_ids: tuple[int, ...],
    reservation_id: int,
) -> tuple[object, ...]:
    """Capture durable financial state and the intentionally corrupt receipt link."""

    accounts = tuple(
        SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(pk__in=account_ids)
        .order_by("pk")
        .values_list(
            "pk",
            "current_cash",
            "current_market_value",
            "total_value",
            "total_trades",
            "winning_trades",
            "cash_known",
            "cash_reconciliation_status",
        )
    )
    positions = tuple(
        PositionModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id__in=account_ids)
        .order_by("pk")
        .values_list(
            "pk",
            "account_id",
            "quantity",
            "available_quantity",
            "available_quantity_known",
            "avg_cost",
            "total_cost",
            "market_value",
            "current_price",
            "cost_basis_known",
        )
    )
    reservations = tuple(
        SimulatedOrderReservationModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(pk=reservation_id)
        .values_list(
            "pk",
            "status",
            "filled_quantity",
            "cash_consumed",
            "shares_consumed",
            "cash_released",
            "shares_released",
        )
    )
    trades = tuple(
        SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id__in=account_ids)
        .order_by("pk")
        .values_list(
            "pk",
            "account_id",
            "quantity",
            "amount",
            "commission",
            "transfer_fee",
            "stamp_duty",
            "slippage",
            "total_cost",
            "settlement_status",
            "settlement_released_at",
        )
    )
    receipts = tuple(
        SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(reservation_id=reservation_id)
        .order_by("pk")
        .values_list("pk", "reservation_id", "trade_id", "receipt_hash", "fill_sequence")
    )
    return accounts, positions, reservations, trades, receipts


def _validate_with_parent_locks(
    *,
    account_id: int,
    reservation_id: int,
    entered: Event | None = None,
) -> None:
    """Call the reader only after locking its owning account and reservation."""

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS).select_for_update().get(pk=account_id)
        reservation = (
            SimulatedOrderReservationModel.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .get(pk=reservation_id, account_id=account_id)
        )
        if entered is not None:
            entered.set()
        validate_locked_order_fill_chain(reservation_row=reservation, using=DEFAULT_DB_ALIAS)


def test_foreign_account_trade_link_is_blocked_without_financial_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A corrupted receipt link fails closed and leaves every ledger row unchanged."""

    del persisted_receipt_schema
    corrupted = _prepare_cross_account_receipt(reservation_harness)
    own_account_id = corrupted.harness.account.pk
    foreign_account_id = corrupted.foreign_account.pk
    reservation_id = corrupted.rows.reservation.pk
    assert type(own_account_id) is int
    assert type(foreign_account_id) is int
    assert type(reservation_id) is int
    before = _financial_snapshot(
        account_ids=(own_account_id, foreign_account_id),
        reservation_id=reservation_id,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _validate_with_parent_locks(
            account_id=own_account_id,
            reservation_id=reservation_id,
        )

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert before == _financial_snapshot(
        account_ids=(own_account_id, foreign_account_id),
        reservation_id=reservation_id,
    )


def test_foreign_trade_row_lock_does_not_block_scoped_chain_validation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    _require_native_postgres: None,
) -> None:
    """An owned chain check must reject a foreign link without waiting on that Trade."""

    del persisted_receipt_schema, _require_native_postgres
    corrupted = _prepare_cross_account_receipt(reservation_harness)
    own_account_id = corrupted.harness.account.pk
    reservation_id = corrupted.rows.reservation.pk
    foreign_trade_id = corrupted.foreign_trade.pk
    assert type(own_account_id) is int
    assert type(reservation_id) is int
    assert type(foreign_trade_id) is int

    worker_entered = Event()
    worker_call = None
    timed_out = False
    timeout_state: tuple[object, ...] | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="foreign-trade-lock-scope") as pool:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS).select_for_update().get(
                pk=foreign_trade_id
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                holder_row = cursor.fetchone()
            assert holder_row is not None and type(holder_row[0]) is int
            holder_pid = holder_row[0]
            worker_call = _submit_worker(
                pool,
                lambda: _validate_with_parent_locks(
                    account_id=own_account_id,
                    reservation_id=reservation_id,
                    entered=worker_entered,
                ),
            )
            assert worker_call.backend_pids[0] != holder_pid
            assert worker_entered.wait(timeout=5)
            try:
                outcome = worker_call.future.result(timeout=4)
            except TimeoutError:
                timed_out = True
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT wait_event_type, pg_blocking_pids(pid), query "
                        "FROM pg_stat_activity WHERE pid = %s",
                        [worker_call.backend_pids[0]],
                    )
                    timeout_state = cursor.fetchone()
        assert worker_call is not None
        if timed_out:
            outcome = worker_call.future.result(timeout=20)

    assert not timed_out, f"chain validation waited on a foreign Trade lock: {timeout_state!r}"
    assert outcome.value is None
    assert outcome.blocked_code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
