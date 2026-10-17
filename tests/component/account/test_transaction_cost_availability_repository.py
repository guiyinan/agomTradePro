"""Private real-ORM candidate tests for transaction-cost availability."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue
from typing import Protocol
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    models,
    transaction,
)
from django.db.models.signals import post_save

from apps.account.domain.transaction_cost_contracts import TransactionCostRecord
from apps.account.domain.transaction_record_contracts import (
    NewTransactionRecord,
    TransactionRecord,
)
from apps.account.infrastructure.models import (
    AssetCategoryModel,
    BrokerTradeImportBatchModel,
    CurrencyModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.account.infrastructure.repositories import (
    ManualTradeSyncRepository,
    TransactionRepository,
)
from core.exceptions import AuthorizationError, InvalidInputError
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=["django.contrib.auth", "django.contrib.contenttypes"],
)

FeeAmounts = tuple[Decimal, Decimal, Decimal, Decimal]
FeeStates = tuple[bool | None, bool | None, bool | None, bool | None]
_SCHEMA_MODELS: tuple[type[models.Model], ...] = (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PositionModel,
    BrokerTradeImportBatchModel,
    TransactionModel,
)


class _DjangoDbBlocker(Protocol):
    def unblock(self) -> AbstractContextManager[None]:
        """Temporarily allow schema setup for the test-owned tables."""


@pytest.fixture(autouse=True)
def _schema(
    django_db_setup: object,
    django_db_blocker: _DjangoDbBlocker,
) -> Iterator[None]:
    """Reuse migrated tables or create and clean only this repository's tables."""

    del django_db_setup
    with django_db_blocker.unblock():
        with isolated_schema(_SCHEMA_MODELS):
            yield


def _new_user(label: str) -> User:
    """Persist an owner row without running unrelated user-provisioning signals."""

    username = f"fee-repo-{label}-{uuid4().hex}"
    user = User(username=username, is_active=True)
    User._default_manager.bulk_create([user])
    return User._default_manager.get(username=username)


def _new_portfolio(owner: User, label: str) -> PortfolioModel:
    """Create a real owner-scoped portfolio row."""

    return PortfolioModel._default_manager.create(
        user=owner,
        name=f"fee repository {label}",
    )


def _new_transaction(
    portfolio: PortfolioModel,
    *,
    fees: FeeAmounts = (
        Decimal("5"),
        Decimal("2"),
        Decimal("3"),
        Decimal("1"),
    ),
    known: FeeStates = (True, True, True, True),
    estimated_cost: Decimal | None = Decimal("10"),
    cost_variance: Decimal | None = Decimal("0"),
    cost_variance_pct: float | None = 0.0,
    traded_at: datetime = datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
) -> TransactionModel:
    """Create one real ledger row with explicit values and availability states."""

    commission, slippage, stamp_duty, transfer_fee = fees
    commission_known, slippage_known, stamp_duty_known, transfer_fee_known = known
    return TransactionModel._default_manager.create(
        portfolio=portfolio,
        position=None,
        action="sell",
        asset_code="600000.SH",
        shares=100.0,
        price=Decimal("10.00"),
        notional=Decimal("1000.00"),
        commission=commission,
        slippage=slippage,
        stamp_duty=stamp_duty,
        transfer_fee=transfer_fee,
        commission_known=commission_known,
        slippage_known=slippage_known,
        stamp_duty_known=stamp_duty_known,
        transfer_fee_known=transfer_fee_known,
        estimated_cost=estimated_cost,
        cost_variance=cost_variance,
        cost_variance_pct=cost_variance_pct,
        traded_at=traded_at,
    )


def _cost_state(model: TransactionModel) -> tuple[object, ...]:
    """Snapshot every amount, known flag, and derived value from a persisted row."""

    return (
        model.commission,
        model.slippage,
        model.stamp_duty,
        model.transfer_fee,
        model.commission_known,
        model.slippage_known,
        model.stamp_duty_known,
        model.transfer_fee_known,
        model.estimated_cost,
        model.cost_variance,
        model.cost_variance_pct,
    )


def _actual_amounts(model: TransactionModel) -> FeeAmounts:
    """Return the four persisted fee amounts in contract order."""

    return (
        model.commission,
        model.slippage,
        model.stamp_duty,
        model.transfer_fee,
    )


def _known_states(model: TransactionModel) -> FeeStates:
    """Return the four persisted availability states in contract order."""

    return (
        model.commission_known,
        model.slippage_known,
        model.stamp_duty_known,
        model.transfer_fee_known,
    )


@pytest.mark.parametrize(
    ("patch", "expected_fees", "expected_known", "expected_projected_fees"),
    [
        pytest.param(
            {"commission": Decimal("0")},
            (Decimal("0"), Decimal("2"), Decimal("3"), Decimal("1")),
            (True, False, None, True),
            (Decimal("0"), None, None, Decimal("1")),
            id="explicit-zero-commission-preserves-omitted-fields",
        ),
        pytest.param(
            {"slippage": Decimal("0")},
            (Decimal("5"), Decimal("0"), Decimal("3"), Decimal("1")),
            (True, True, None, True),
            (Decimal("5"), Decimal("0"), None, Decimal("1")),
            id="explicit-zero-slippage-preserves-omitted-fields",
        ),
        pytest.param(
            {"stamp_duty": Decimal("0")},
            (Decimal("5"), Decimal("2"), Decimal("0"), Decimal("1")),
            (True, False, True, True),
            (Decimal("5"), None, Decimal("0"), Decimal("1")),
            id="explicit-zero-stamp-duty-preserves-omitted-fields",
        ),
        pytest.param(
            {"transfer_fee": Decimal("0")},
            (Decimal("5"), Decimal("2"), Decimal("3"), Decimal("0")),
            (True, False, None, True),
            (Decimal("5"), None, None, Decimal("0")),
            id="explicit-zero-transfer-fee-preserves-omitted-fields",
        ),
    ],
)
def test_none_preserves_each_omitted_amount_and_state_while_zero_is_known(
    patch: dict[str, Decimal],
    expected_fees: FeeAmounts,
    expected_known: FeeStates,
    expected_projected_fees: tuple[
        Decimal | None,
        Decimal | None,
        Decimal | None,
        Decimal | None,
    ],
) -> None:
    owner = _new_user("partial-update")
    portfolio = _new_portfolio(owner, "partial-update")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("5"), Decimal("2"), Decimal("3"), Decimal("1")),
        known=(True, False, None, True),
        cost_variance=Decimal("88"),
        cost_variance_pct=8.8,
    )

    result = TransactionRepository().update_transaction_costs(
        row.pk,
        actor_user_id=owner.pk,
        **patch,
    )

    assert result is not None
    assert (
        result["commission"],
        result["slippage"],
        result["stamp_duty"],
        result["transfer_fee"],
    ) == expected_projected_fees
    assert (
        result["commission_known"],
        result["slippage_known"],
        result["stamp_duty_known"],
        result["transfer_fee_known"],
    ) == expected_known

    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert _actual_amounts(persisted) == expected_fees
    assert _known_states(persisted) == expected_known


def test_partial_correction_recomputes_variance_from_the_entire_fresh_row() -> None:
    owner = _new_user("whole-row-variance")
    portfolio = _new_portfolio(owner, "whole-row-variance")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("5"), Decimal("2"), Decimal("3"), Decimal("1")),
        known=(True, True, True, True),
        estimated_cost=Decimal("10"),
        cost_variance=Decimal("77"),
        cost_variance_pct=7.7,
    )

    result = TransactionRepository().update_transaction_costs(
        row.pk,
        actor_user_id=owner.pk,
        commission=Decimal("12"),
    )

    assert result is not None
    assert (
        result["commission"],
        result["slippage"],
        result["stamp_duty"],
        result["transfer_fee"],
    ) == (Decimal("12"), Decimal("2"), Decimal("3"), Decimal("1"))
    assert result["cost_variance"] == Decimal("8")
    assert result["cost_variance_pct"] == pytest.approx(0.8)

    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert persisted.cost_variance == Decimal("8")
    assert persisted.cost_variance_pct == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("known", "estimated_cost"),
    [
        pytest.param((True, False, True, True), Decimal("10"), id="false-known-flag"),
        pytest.param((True, None, True, True), Decimal("10"), id="null-known-flag"),
        pytest.param((True, True, True, True), None, id="missing-estimate"),
    ],
)
def test_unknown_actual_or_missing_estimate_clears_stale_derived_values(
    known: FeeStates,
    estimated_cost: Decimal | None,
) -> None:
    owner = _new_user("stale-derived-values")
    portfolio = _new_portfolio(owner, "stale-derived-values")
    row = _new_transaction(
        portfolio,
        known=known,
        estimated_cost=estimated_cost,
        cost_variance=Decimal("55"),
        cost_variance_pct=5.5,
    )

    result = TransactionRepository().update_transaction_costs(
        row.pk,
        actor_user_id=owner.pk,
        commission=Decimal("12"),
    )

    assert result is not None
    assert result["cost_variance"] is None
    assert result["cost_variance_pct"] is None
    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert persisted.cost_variance is None
    assert persisted.cost_variance_pct is None


def test_zero_estimate_keeps_nonzero_absolute_variance_and_null_fraction() -> None:
    owner = _new_user("zero-estimate")
    portfolio = _new_portfolio(owner, "zero-estimate")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("5"), Decimal("2"), Decimal("3"), Decimal("1")),
        known=(True, True, True, True),
        estimated_cost=Decimal("0"),
        cost_variance=Decimal("99"),
        cost_variance_pct=9.9,
    )

    result = TransactionRepository().update_transaction_costs(
        row.pk,
        actor_user_id=owner.pk,
        commission=Decimal("12"),
    )

    assert result is not None
    assert result["cost_variance"] == Decimal("18")
    assert result["cost_variance_pct"] is None
    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert persisted.cost_variance == Decimal("18")
    assert persisted.cost_variance_pct is None


def test_missing_and_foreign_owner_updates_return_none_without_ledger_changes() -> None:
    owner = _new_user("owner-denial")
    foreign_owner = _new_user("foreign-owner-denial")
    owned_portfolio = _new_portfolio(owner, "owner-denial")
    foreign_portfolio = _new_portfolio(foreign_owner, "foreign-owner-denial")
    owned_row = _new_transaction(owned_portfolio)
    foreign_row = _new_transaction(foreign_portfolio)
    rows_before = {
        row.pk: _cost_state(row) for row in TransactionModel._default_manager.order_by("pk")
    }
    repository = TransactionRepository()

    foreign_result = repository.update_transaction_costs(
        foreign_row.pk,
        actor_user_id=owner.pk,
        commission=Decimal("99"),
    )
    missing_result = repository.update_transaction_costs(
        max(rows_before) + 1_000_000,
        actor_user_id=owner.pk,
        commission=Decimal("99"),
    )

    assert foreign_result is None
    assert missing_result is None
    assert TransactionModel._default_manager.count() == len(rows_before)
    rows_after = {
        row.pk: _cost_state(row) for row in TransactionModel._default_manager.order_by("pk")
    }
    assert rows_after == rows_before
    assert PortfolioModel._default_manager.get(pk=foreign_portfolio.pk).user_id == foreign_owner.pk
    assert PortfolioModel._default_manager.get(pk=owned_portfolio.pk).user_id == owner.pk
    assert owned_row.pk in rows_after


def test_analysis_repository_filters_by_trade_time_not_import_time() -> None:
    owner = _new_user("trade-time-window")
    other_owner = _new_user("trade-time-other-owner")
    portfolio = _new_portfolio(owner, "trade-time-window")
    other_portfolio = _new_portfolio(other_owner, "trade-time-other-owner")
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
    imported_recently_but_traded_before_window = _new_transaction(
        portfolio,
        traded_at=datetime(2025, 12, 31, 10, 0, tzinfo=UTC),
    )
    imported_before_window_but_traded_recently = _new_transaction(
        portfolio,
        traded_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
    )
    exactly_at_window_start = _new_transaction(
        portfolio,
        traded_at=since,
    )
    exactly_at_window_end = _new_transaction(
        portfolio,
        traded_at=until,
    )
    future_transaction = _new_transaction(
        portfolio,
        traded_at=until + timedelta(seconds=1),
    )
    foreign_row = _new_transaction(
        other_portfolio,
        traded_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
    )
    TransactionModel._default_manager.filter(
        pk=imported_recently_but_traded_before_window.pk
    ).update(created_at=datetime(2026, 8, 1, tzinfo=UTC))
    TransactionModel._default_manager.filter(
        pk=imported_before_window_but_traded_recently.pk
    ).update(created_at=datetime(2025, 1, 1, tzinfo=UTC))
    TransactionModel._default_manager.filter(pk=exactly_at_window_start.pk).update(
        created_at=datetime(2025, 1, 2, tzinfo=UTC)
    )

    records = TransactionRepository().list_user_transaction_costs(
        owner.pk,
        since_date=since,
        until_date=until,
    )

    returned_ids = {record["id"] for record in records}
    assert returned_ids == {
        imported_before_window_but_traded_recently.pk,
        exactly_at_window_start.pk,
        exactly_at_window_end.pk,
    }
    assert imported_recently_but_traded_before_window.pk not in returned_ids
    assert future_transaction.pk not in returned_ids
    assert foreign_row.pk not in returned_ids


def test_post_save_failure_rolls_back_repository_sql_update() -> None:
    owner = _new_user("post-save-rollback")
    portfolio = _new_portfolio(owner, "post-save-rollback")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("5"), Decimal("2"), Decimal("3"), Decimal("1")),
        known=(True, True, True, True),
        estimated_cost=Decimal("10"),
        cost_variance=Decimal("-77"),
        cost_variance_pct=-7.7,
    )
    before = _cost_state(row)

    def fail_after_database_save(
        sender: type[TransactionModel],
        instance: TransactionModel,
        created: bool,
        **kwargs: object,
    ) -> None:
        """Raise only after Django has emitted post_save for the update SQL."""

        del sender, instance, kwargs
        assert not created
        raise RuntimeError("abort after transaction row save")

    dispatch_uid = "ash-fee-repository-post-save-failure-private"
    post_save.connect(
        fail_after_database_save,
        sender=TransactionModel,
        weak=False,
        dispatch_uid=dispatch_uid,
    )
    try:
        with pytest.raises(RuntimeError, match="abort after transaction row save"):
            TransactionRepository().update_transaction_costs(
                row.pk,
                actor_user_id=owner.pk,
                commission=Decimal("12"),
            )
    finally:
        post_save.disconnect(dispatch_uid=dispatch_uid, sender=TransactionModel)

    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert _cost_state(persisted) == before


def _pg_blocking_pids(waiter_pid: int) -> tuple[int, ...]:
    """Read PostgreSQL's actual lock blockers for one waiting backend."""

    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT pg_blocking_pids(%s)", [waiter_pid])
        result = cursor.fetchone()
    assert result is not None
    return tuple(int(pid) for pid in result[0])


def test_postgres_owner_change_while_waiting_is_rechecked_under_lock() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks and pg_blocking_pids")

    owner = _new_user("pg-owner-race")
    replacement_owner = _new_user("pg-new-owner-race")
    portfolio = _new_portfolio(owner, "pg-owner-race")
    row = _new_transaction(portfolio)
    before = _cost_state(row)
    worker_pid_queue: Queue[int] = Queue()

    def attempt_update() -> TransactionCostRecord | None:
        """Run the real repository call with bounded lock and statement waits."""

        close_old_connections()
        worker_connection = connections["default"]
        try:
            with worker_connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '6000ms'")
                cursor.execute("SET statement_timeout = '9000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                pid_row = cursor.fetchone()
            assert pid_row is not None
            worker_pid_queue.put(int(pid_row[0]))
            return TransactionRepository().update_transaction_costs(
                row.pk,
                actor_user_id=owner.pk,
                commission=Decimal("99"),
            )
        finally:
            worker_connection.close()

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="ash-fee-owner-race-repository-update",
    ) as executor:
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                main_pid_row = cursor.fetchone()
            assert main_pid_row is not None
            main_pid = int(main_pid_row[0])
            locked_portfolio = PortfolioModel._default_manager.select_for_update().get(
                pk=portfolio.pk
            )
            locked_portfolio.user_id = replacement_owner.pk
            locked_portfolio.save(update_fields=["user"])

            future = executor.submit(attempt_update)
            worker_pid = worker_pid_queue.get(timeout=5)
            assert worker_pid != main_pid
            deadline = time.monotonic() + 5
            blocker_pids: tuple[int, ...] = ()
            while time.monotonic() < deadline and not future.done():
                blocker_pids = _pg_blocking_pids(worker_pid)
                if main_pid in blocker_pids:
                    break
                time.sleep(0.02)

            assert main_pid in blocker_pids, (
                "repository contender never appeared in pg_blocking_pids; "
                f"last blockers were {blocker_pids}"
            )

        result = future.result(timeout=10)
    assert result is None
    assert PortfolioModel._default_manager.get(pk=portfolio.pk).user_id == replacement_owner.pk
    assert _cost_state(TransactionModel._default_manager.get(pk=row.pk)) == before


def _new_position(portfolio: PortfolioModel, asset_code: str) -> PositionModel:
    """Create one real position row for the repository's relationship checks."""

    return PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=10.0,
        avg_cost=Decimal("9.0000"),
        current_price=Decimal("9.5000"),
        market_value=Decimal("95.00"),
        unrealized_pnl=Decimal("5.00"),
        unrealized_pnl_pct=5.0,
    )


def _new_transaction_record(
    portfolio: PortfolioModel,
    position: PositionModel | None = None,
) -> NewTransactionRecord:
    """Build one fully typed valid repository input without invoking API code."""

    return NewTransactionRecord(
        actor_user_id=portfolio.user_id,
        portfolio_id=portfolio.pk,
        position_id=position.pk if position is not None else None,
        action="buy",
        asset_code=position.asset_code if position is not None else "600000.SH",
        shares=10.0,
        price=Decimal("9.5000"),
        notional=Decimal("95.00"),
        notes="native PostgreSQL lock-order fixture",
        traded_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        commission=None,
        slippage=None,
        stamp_duty=None,
        transfer_fee=None,
    )


def _run_pg_repository_operation(
    operation: Callable[[], object],
    worker_pid_queue: Queue[int],
) -> object:
    """Run a real repository call on its own bounded PostgreSQL connection."""

    close_old_connections()
    worker_connection = connections["default"]
    try:
        with worker_connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '6000ms'")
            cursor.execute("SET statement_timeout = '9000ms'")
            cursor.execute("SELECT pg_backend_pid()")
            pid_row = cursor.fetchone()
        assert pid_row is not None
        worker_pid_queue.put(int(pid_row[0]))
        return operation()
    finally:
        worker_connection.close()


def _pg_main_backend_pid() -> int:
    """Return the calling connection's real PostgreSQL backend PID."""

    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        pid_row = cursor.fetchone()
    assert pid_row is not None
    return int(pid_row[0])


def _wait_for_pg_block_or_completion(
    worker_pid: int,
    main_pid: int,
    future: Future[object],
) -> tuple[int, ...]:
    """Wait for an observed blocker or completed repository call, with a bound."""

    deadline = time.monotonic() + 5
    blocker_pids: tuple[int, ...] = ()
    while time.monotonic() < deadline:
        blocker_pids = _pg_blocking_pids(worker_pid)
        if main_pid in blocker_pids or future.done():
            return blocker_pids
        time.sleep(0.02)
    return blocker_pids


def _finish_pg_worker(
    executor: ThreadPoolExecutor,
    future: Future[object] | None,
) -> None:
    """Join the worker only after the surrounding main transaction has released locks."""

    if future is not None:
        try:
            future.result(timeout=10)
        except Exception:
            pass
    executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize(
    ("same_owner", "expected_error"),
    [
        pytest.param(False, AuthorizationError, id="foreign-owner-position"),
        pytest.param(True, InvalidInputError, id="same-owner-wrong-portfolio"),
    ],
)
def test_postgres_invalid_position_rejection_does_not_wait_on_other_portfolio(
    same_owner: bool,
    expected_error: type[Exception],
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks and pg_blocking_pids")

    owner = _new_user("pg-position-owner")
    other_owner = owner if same_owner else _new_user("pg-position-other-owner")
    target_portfolio = _new_portfolio(owner, "pg-position-target")
    other_portfolio = _new_portfolio(other_owner, "pg-position-other")
    position = _new_position(other_portfolio, "600000.SH")
    record = _new_transaction_record(target_portfolio, position)
    worker_pid_queue: Queue[int] = Queue()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ash-pg-position-denial")
    future: Future[object] | None = None
    try:
        with transaction.atomic():
            main_pid = _pg_main_backend_pid()
            PortfolioModel._default_manager.select_for_update().get(pk=other_portfolio.pk)
            future = executor.submit(
                _run_pg_repository_operation,
                lambda: TransactionRepository().create_transaction(record),
                worker_pid_queue,
            )
            worker_pid = worker_pid_queue.get(timeout=5)
            assert worker_pid != main_pid
            blockers = _wait_for_pg_block_or_completion(worker_pid, main_pid, future)
            assert main_pid not in blockers, (
                "invalid position classification waited on its unrelated owning portfolio; "
                f"blockers were {blockers}"
            )
            assert (
                future.done()
            ), "repository did not finish while the other portfolio stayed locked"
            with pytest.raises(expected_error):
                future.result(timeout=1)
            assert not TransactionModel._default_manager.filter(portfolio=target_portfolio).exists()
    finally:
        _finish_pg_worker(executor, future)


def test_postgres_cost_waits_for_parent_before_locking_ledger() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks, NOWAIT and pg_blocking_pids")

    owner = _new_user("pg-cost-order")
    portfolio = _new_portfolio(owner, "pg-cost-order")
    row = _new_transaction(portfolio)
    worker_pid_queue: Queue[int] = Queue()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ash-pg-cost-order")
    future: Future[object] | None = None
    try:
        with transaction.atomic():
            main_pid = _pg_main_backend_pid()
            PortfolioModel._default_manager.select_for_update().get(pk=portfolio.pk)
            future = executor.submit(
                _run_pg_repository_operation,
                lambda: TransactionRepository().update_transaction_costs(
                    row.pk,
                    actor_user_id=owner.pk,
                    commission=Decimal("99"),
                ),
                worker_pid_queue,
            )
            worker_pid = worker_pid_queue.get(timeout=5)
            assert worker_pid != main_pid
            blockers = _wait_for_pg_block_or_completion(worker_pid, main_pid, future)
            assert main_pid in blockers, (
                "cost update did not wait on its locked parent before returning; "
                f"blockers were {blockers}"
            )

            ledger_lock_acquired = False
            try:
                with transaction.atomic():
                    TransactionModel._default_manager.select_for_update(nowait=True).get(pk=row.pk)
                ledger_lock_acquired = True
            except DatabaseError:
                ledger_lock_acquired = False
            assert (
                ledger_lock_acquired
            ), "cost update locked the ledger before waiting for its parent"
    finally:
        _finish_pg_worker(executor, future)

    assert future is not None
    result = future.result(timeout=1)
    assert isinstance(result, dict)
    assert result["id"] == row.pk
    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert persisted.commission == Decimal("99.00")
    assert persisted.commission_known is True


@pytest.mark.parametrize(
    "locked_reference",
    [
        pytest.param("portfolio", id="parent-key-share"),
        pytest.param("position", id="position-key-share"),
    ],
)
def test_postgres_create_completes_while_referenced_row_key_share_is_held(
    locked_reference: str,
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row locks and pg_blocking_pids")

    owner = _new_user(f"pg-create-key-share-{locked_reference}")
    portfolio = _new_portfolio(owner, f"pg-create-key-share-{locked_reference}")
    position = _new_position(portfolio, "600000.SH") if locked_reference == "position" else None
    record = _new_transaction_record(portfolio, position)
    locked_model = PositionModel if position is not None else PortfolioModel
    locked_row_id = position.pk if position is not None else portfolio.pk
    table_name = connections["default"].ops.quote_name(locked_model._meta.db_table)
    worker_pid_queue: Queue[int] = Queue()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ash-pg-create-key-share")
    future: Future[object] | None = None
    try:
        with transaction.atomic():
            main_pid = _pg_main_backend_pid()
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    f"SELECT id FROM {table_name} WHERE id = %s FOR KEY SHARE",
                    [locked_row_id],
                )
                assert cursor.fetchone() is not None
            future = executor.submit(
                _run_pg_repository_operation,
                lambda: TransactionRepository().create_transaction(record),
                worker_pid_queue,
            )
            worker_pid = worker_pid_queue.get(timeout=5)
            assert worker_pid != main_pid
            blockers = _wait_for_pg_block_or_completion(worker_pid, main_pid, future)
            assert main_pid not in blockers, (
                f"valid create blocked on a KEY SHARE lock for {locked_reference}; "
                f"blockers were {blockers}"
            )
            assert future.done(), "valid create did not complete while KEY SHARE remained held"
            result = future.result(timeout=1)
            assert isinstance(result, TransactionRecord)
            assert result.portfolio_id == portfolio.pk
            assert result.position_id == (position.pk if position is not None else None)
            assert TransactionModel._default_manager.filter(pk=result.id).exists()
    finally:
        _finish_pg_worker(executor, future)


@pytest.mark.parametrize(
    "field_name",
    ["commission", "slippage", "stamp_duty", "transfer_fee"],
)
def test_each_individual_fee_accepts_decimal_field_upper_bound(field_name: str) -> None:
    owner = _new_user("single-fee-upper-bound")
    portfolio = _new_portfolio(owner, "single-fee-upper-bound")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
        known=(True, True, True, True),
        estimated_cost=Decimal("0"),
        cost_variance=Decimal("12.34"),
        cost_variance_pct=12.34,
    )
    maximum_fee = Decimal("99999999.99")

    result = TransactionRepository().update_transaction_costs(
        row.pk,
        actor_user_id=owner.pk,
        **{field_name: maximum_fee},
    )

    assert result is not None
    persisted = TransactionModel._default_manager.get(pk=row.pk)
    expected_fees = tuple(
        maximum_fee if name == field_name else Decimal("0")
        for name in ("commission", "slippage", "stamp_duty", "transfer_fee")
    )
    assert _actual_amounts(persisted) == expected_fees
    assert _known_states(persisted) == (True, True, True, True)
    assert persisted.cost_variance == Decimal("99999999.99")
    assert persisted.cost_variance_pct is None


def test_variance_overflow_is_rejected_without_changing_persisted_cost_state() -> None:
    owner = _new_user("variance-overflow")
    portfolio = _new_portfolio(owner, "variance-overflow")
    row = _new_transaction(
        portfolio,
        fees=(Decimal("5"), Decimal("2"), Decimal("0"), Decimal("0")),
        known=(True, False, True, True),
        estimated_cost=Decimal("0"),
        cost_variance=Decimal("123.45"),
        cost_variance_pct=12.345,
    )
    before = _cost_state(row)

    with pytest.raises(InvalidInputError):
        TransactionRepository().update_transaction_costs(
            row.pk,
            actor_user_id=owner.pk,
            commission=Decimal("99999999.99"),
            slippage=Decimal("0.01"),
        )

    persisted = TransactionModel._default_manager.get(pk=row.pk)
    assert _actual_amounts(persisted) == (
        Decimal("5"),
        Decimal("2"),
        Decimal("0"),
        Decimal("0"),
    )
    assert _known_states(persisted) == (True, False, True, True)
    assert _cost_state(persisted) == before


@pytest.mark.parametrize(
    ("input_fees", "expected_storage", "expected_known", "expected_projected"),
    [
        pytest.param(
            (None, None, None),
            (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
            (False, False, False, False),
            (None, None, None, None),
            id="all-import-fees-unknown",
        ),
        pytest.param(
            (Decimal("0"), Decimal("0"), Decimal("0")),
            (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
            (True, False, True, True),
            (Decimal("0"), None, Decimal("0"), Decimal("0")),
            id="explicit-zero-is-known-but-imported-slippage-is-not",
        ),
        pytest.param(
            (Decimal("1.25"), Decimal("0.80"), Decimal("0.05")),
            (Decimal("1.25"), Decimal("0"), Decimal("0.80"), Decimal("0.05")),
            (True, False, True, True),
            (Decimal("1.25"), None, Decimal("0.80"), Decimal("0.05")),
            id="positive-imported-fees-do-not-qualify-slippage",
        ),
        pytest.param(
            (Decimal("0.50"), None, Decimal("0")),
            (Decimal("0.50"), Decimal("0"), Decimal("0"), Decimal("0")),
            (True, False, False, True),
            (Decimal("0.50"), None, None, Decimal("0")),
            id="mixed-import-fees-preserve-unknown-states",
        ),
    ],
)
def test_manual_trade_import_persists_fee_availability_and_canonical_projection(
    input_fees: tuple[Decimal | None, Decimal | None, Decimal | None],
    expected_storage: FeeAmounts,
    expected_known: FeeStates,
    expected_projected: tuple[
        Decimal | None,
        Decimal | None,
        Decimal | None,
        Decimal | None,
    ],
) -> None:
    owner = _new_user("manual-import-fee-state")
    portfolio = _new_portfolio(owner, "manual-import-fee-state")
    batch = BrokerTradeImportBatchModel._default_manager.create(
        user=owner,
        portfolio=portfolio,
        broker_name="Synthetic import source",
        source_filename="synthetic-fees.csv",
        file_hash=uuid4().hex,
        total_rows=1,
        preview_rows=[{"source_row": 3, "kind": "synthetic"}],
    )
    traded_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    raw_payload = {"source_row": 3, "commission": "synthetic"}
    external_trade_id = f"manual-{uuid4().hex}"
    broker_trade_key = uuid4().hex

    imported = ManualTradeSyncRepository().create_imported_transaction(
        portfolio=portfolio,
        action="buy",
        asset_code="600000.SH",
        shares=10.0,
        price=Decimal("8.25"),
        commission=input_fees[0],
        stamp_duty=input_fees[1],
        transfer_fee=input_fees[2],
        traded_at=traded_at,
        notes="Synthetic repository boundary case",
        broker_name="Synthetic import source",
        external_trade_id=external_trade_id,
        broker_trade_key=broker_trade_key,
        raw_payload=raw_payload,
        import_batch=batch,
    )

    persisted = TransactionModel._default_manager.get(pk=imported.pk)
    assert _actual_amounts(persisted) == expected_storage
    assert _known_states(persisted) == expected_known
    assert persisted.traded_at == traded_at
    assert persisted.broker_name == "Synthetic import source"
    assert persisted.external_trade_id == external_trade_id
    assert persisted.broker_trade_key == broker_trade_key
    assert persisted.raw_payload == raw_payload
    assert persisted.import_batch_id == batch.pk

    canonical = TransactionRepository().get_user_transaction(owner.pk, imported.pk)
    assert canonical is not None
    assert (
        canonical.commission,
        canonical.slippage,
        canonical.stamp_duty,
        canonical.transfer_fee,
    ) == expected_projected
    assert (
        canonical.commission_known,
        canonical.slippage_known,
        canonical.stamp_duty_known,
        canonical.transfer_fee_known,
    ) == expected_known
    assert canonical.traded_at == traded_at
    assert canonical.broker_name == "Synthetic import source"
    assert canonical.external_trade_id == external_trade_id
    assert canonical.broker_trade_key == broker_trade_key
    assert canonical.import_batch_id == batch.pk
