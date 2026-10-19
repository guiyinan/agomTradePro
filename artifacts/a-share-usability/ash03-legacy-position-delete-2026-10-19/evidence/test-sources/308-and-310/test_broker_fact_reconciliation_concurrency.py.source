"""Two PostgreSQL connections must preserve exactly one fact and balance delta."""

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from typing import cast

import pytest
from django.contrib.auth.models import User
from django.db import close_old_connections, connection, connections, transaction
from django.db.models import Q

from apps.account.application import portfolio_api_services
from apps.account.application.manual_trade_sync import ManualTradeImportUseCase
from apps.account.application.portfolio_api_contracts import LegacyPositionRecord
from apps.account.infrastructure import models as account_models
from apps.account.infrastructure.models import (
    PortfolioModel,
    TransactionModel,
)
from apps.simulated_trading.infrastructure import models as ledger_models
from tests.component.account.test_broker_trade_baseline_reconciliation import (
    NoopMatcher,
    _args,
    _content,
)
from tests.component.account.test_broker_trade_baseline_reconciliation import (
    baseline_book as baseline_book,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("first_decision", ["pending", "excluded"])
def test_concurrent_confirmation_waits_and_projects_one_exact_broker_fact(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    record_property: Callable[[str, object], None],
    first_decision: str,
) -> None:
    """Observe a real waiter/blocker pair, then verify terminal duplicate replay."""
    if connection.vendor != "postgresql":
        pytest.skip("Two-connection broker reconciliation proof requires PostgreSQL")
    owner, portfolio, position = baseline_book
    arguments = _args(owner, portfolio, _content())
    preview = ManualTradeImportUseCase(execution_matcher=NoopMatcher()).preview(**arguments)
    arguments.update(
        baseline_decision=first_decision,
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )
    competing = _args(owner, portfolio, b"\xef\xbb\xbf" + _content())
    competing_preview = ManualTradeImportUseCase(execution_matcher=NoopMatcher()).preview(
        **competing
    )
    competing.update(
        baseline_decision="excluded",
        expected_fact_set_fingerprint=competing_preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=competing_preview.expected_balance_fingerprint,
    )
    assert sha256(arguments["content"]).digest() != sha256(competing["content"]).digest()
    first_ready = Event()
    allow_commit = Event()
    second_connected = Event()
    backend_pids: dict[str, int] = {}

    def confirm_in_connection(*, first: bool) -> object:
        database = connections["default"]
        try:
            with database.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pids["first" if first else "second"] = int(cursor.fetchone()[0])
            if not first:
                second_connected.set()
            with transaction.atomic():
                result = ManualTradeImportUseCase(execution_matcher=NoopMatcher()).confirm(
                    **(arguments if first else competing)
                )
                if first:
                    first_ready.set()
                    assert allow_commit.wait(10), "Root did not release first transaction"
            return result
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future: Future[object] = executor.submit(confirm_in_connection, first=True)
        second_future: Future[object] | None = None
        try:
            assert first_ready.wait(
                10
            ), "First connection did not finish import inside its transaction"
            second_future = executor.submit(confirm_in_connection, first=False)
            assert second_connected.wait(10), "Second PostgreSQL connection did not open"
            observed_blockers: list[int] = []
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [backend_pids["second"]])
                    observed_blockers = list(cursor.fetchone()[0])
                if backend_pids["first"] in observed_blockers:
                    break
                if second_future.done():
                    second_future.result()
                    break
                sleep(0.01)
            assert backend_pids["first"] != backend_pids["second"]
            assert backend_pids["first"] in observed_blockers
            record_property("postgresql_blocker_backend_pid", backend_pids["first"])
            record_property("postgresql_waiter_backend_pid", backend_pids["second"])
            record_property("postgresql_observed_blocking_pids", observed_blockers)
            record_property("competing_source_file_hashes_differ", True)
        finally:
            allow_commit.set()
        first_result = first_future.result(timeout=12)
        assert second_future is not None
        second_result = second_future.result(timeout=12)

    assert first_result.facts_saved_count == 1
    assert second_result.facts_saved_count == 0
    assert second_result.duplicate_facts_reused_count == 1
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    assert fact.import_batch_id == first_result.batch_id
    assert fact.import_batch_id != second_result.batch_id
    assert fact.broker_reconciliation_state == "projected"
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1
    position.refresh_from_db()
    assert position.quantity == 60
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )
    assert (
        ledger_models.LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="transaction",
            source_id=fact.pk,
            target_table="simulated_trade",
        ).count()
        == 1
    )


def _closed_source_for_mapped_position(
    *, portfolio: PortfolioModel, target: ledger_models.PositionModel
) -> account_models.PositionModel:
    """Close the mapped legacy source and ensure its key differs from the target id."""

    assert target.pk is not None
    mapping = ledger_models.LedgerMigrationMapModel._default_manager.get(
        source_app="account",
        source_table="position",
        target_table="simulated_position",
        target_id=target.pk,
    )
    source = account_models.PositionModel._default_manager.get(pk=mapping.source_id)
    if source.pk == target.pk:
        source_values: dict[str, object] = {
            "portfolio": portfolio,
            "asset_code": source.asset_code,
            "category_id": source.category_id,
            "currency_id": source.currency_id,
            "asset_class": source.asset_class,
            "region": source.region,
            "cross_border": source.cross_border,
            "shares": source.shares,
            "avg_cost": source.avg_cost,
            "current_price": source.current_price,
            "market_value": source.market_value,
            "unrealized_pnl": source.unrealized_pnl,
            "unrealized_pnl_pct": source.unrealized_pnl_pct,
            "source": source.source,
            "source_id": source.source_id,
        }
        source.delete()
        source = account_models.PositionModel._default_manager.create(**source_values)
        assert source.pk is not None
        mapping.source_id = source.pk
        mapping.save(update_fields=["source_id"])

    source.is_closed = True
    source.closed_at = source.opened_at
    source.save(update_fields=["is_closed", "closed_at"])
    assert source.pk is not None and source.pk != target.pk
    return source


def _mapped_position_snapshot(
    *,
    account_id: int,
    asset_code: str,
    portfolio_id: int,
    source_id: int,
    target_id: int,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    """Read position rows, relevant source maps, and account trades in full."""

    legacy_rows = tuple(
        account_models.PositionModel._default_manager.filter(portfolio_id=portfolio_id)
        .filter(Q(pk=source_id) | Q(asset_code=asset_code))
        .order_by("pk")
        .values()
    )
    unified_rows = tuple(
        ledger_models.PositionModel._default_manager.filter(account_id=account_id)
        .filter(Q(pk=target_id) | Q(asset_code=asset_code))
        .order_by("pk")
        .values()
    )
    source_maps = tuple(
        ledger_models.LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="position",
            target_table="simulated_position",
        )
        .filter(Q(source_id=source_id) | Q(target_id=target_id))
        .order_by("pk")
        .values()
    )
    trades = tuple(
        ledger_models.SimulatedTradeModel._default_manager.filter(account_id=account_id)
        .order_by("pk")
        .values()
    )
    return legacy_rows, unified_rows, source_maps, trades


def _wait_for_parent_lock_wait(*, holder_pid: int, waiter_pid: int, waiter: Future[None]) -> str:
    """Observe the real delete backend waiting on the portfolio parent row."""

    deadline = monotonic() + 6.0
    last_wait_event: str | None = None
    last_query = ""
    last_blockers: tuple[int, ...] = ()
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT wait_event_type, query, pg_blocking_pids(pid) "
                "FROM pg_stat_activity WHERE pid = %s",
                [waiter_pid],
            )
            row = cursor.fetchone()
        if row is not None:
            last_wait_event = row[0]
            last_query = str(row[1])
            last_blockers = tuple(int(pid) for pid in row[2])
            query_lower = last_query.lower()
            if (
                last_wait_event == "Lock"
                and holder_pid in last_blockers
                and "portfolio" in query_lower
                and "for update" in query_lower
            ):
                return last_query
        if waiter.done():
            break
        sleep(0.02)
    raise AssertionError(
        "delete backend did not wait on the locked portfolio parent row; "
        f"wait_event={last_wait_event!r}, blockers={last_blockers!r}, "
        f"query={last_query!r}"
    )


@pytest.mark.django_db(transaction=True)
def test_closed_source_read_serializes_real_delete_on_native_postgres(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    """A real mapped read holds its parent scope until a second connection deletes."""

    if connection.vendor != "postgresql":
        pytest.skip("two-connection closed-position deletion proof requires PostgreSQL")
    assert_native_postgres_test_database()

    owner, portfolio, target = baseline_book
    assert portfolio.pk is not None and owner.pk is not None and target.pk is not None
    source = _closed_source_for_mapped_position(portfolio=portfolio, target=target)
    assert source.pk is not None
    source_id = int(source.pk)
    target_id = int(target.pk)
    account_id = int(target.account_id)
    initial = _mapped_position_snapshot(
        account_id=account_id,
        asset_code=target.asset_code,
        portfolio_id=int(portfolio.pk),
        source_id=source_id,
        target_id=target_id,
    )

    repository = portfolio_api_services._portfolio_api_repo()
    monkeypatch.setattr(
        portfolio_api_services,
        "_portfolio_api_repo",
        lambda: repository,
    )
    original_parent_transaction = cast(
        Callable[..., AbstractContextManager[LegacyPositionRecord | None]],
        repository.legacy_sync_transaction,
    )
    parent_entered: list[bool] = []
    delete_started = Event()
    worker_pids: list[int] = []
    delete_futures: list[Future[None]] = []
    state_after_a_inside_lock: list[
        tuple[
            tuple[dict[str, object], ...],
            tuple[dict[str, object], ...],
            tuple[dict[str, object], ...],
            tuple[dict[str, object], ...],
        ]
    ] = []
    holder_pids: list[int] = []

    def _delete_on_second_connection() -> None:
        """Run the actual application delete on a fresh thread-local connection."""

        close_old_connections()
        worker_connection = connections["default"]
        try:
            with worker_connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10000ms'")
                cursor.execute("SET statement_timeout = '20000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                pid_row = cursor.fetchone()
            assert pid_row is not None
            worker_pids.append(int(pid_row[0]))
            delete_started.set()
            with transaction.atomic():
                portfolio_api_services.delete_position(
                    user_id=int(owner.pk),
                    position_id=target_id,
                )
        finally:
            worker_connection.close()

    @contextmanager
    def _coordinate_parent_scope(
        **kwargs: object,
    ) -> Iterator[LegacyPositionRecord | None]:
        with original_parent_transaction(**kwargs) as locked_source:
            is_first_parent = not parent_entered
            if is_first_parent:
                parent_entered.append(True)
                assert connections["default"].in_atomic_block
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    holder_row = cursor.fetchone()
                assert holder_row is not None
                holder_pids.append(int(holder_row[0]))

                source_under_lock = locked_source
                if source_under_lock is None:
                    source_under_lock = repository.get_legacy_position_by_id(source_id)
                assert source_under_lock is not None and source_under_lock.is_closed
                delete_futures.append(executor.submit(_delete_on_second_connection))
                assert delete_started.wait(timeout=5), "delete worker did not open its connection"
                waiter_pid = worker_pids[0]
                assert waiter_pid != holder_pids[0]
                waiting_query = _wait_for_parent_lock_wait(
                    holder_pid=holder_pids[0],
                    waiter_pid=waiter_pid,
                    waiter=delete_futures[0],
                )
                assert (
                    _mapped_position_snapshot(
                        account_id=account_id,
                        asset_code=target.asset_code,
                        portfolio_id=int(portfolio.pk),
                        source_id=source_id,
                        target_id=target_id,
                    )
                    == initial
                )
                record_property("closed_source_parent_lock_holder_pid", holder_pids[0])
                record_property("closed_source_delete_waiter_pid", waiter_pid)
                record_property("closed_source_delete_wait_query", waiting_query)

            yield locked_source

            if is_first_parent:
                state_after_a_inside_lock.append(
                    _mapped_position_snapshot(
                        account_id=account_id,
                        asset_code=target.asset_code,
                        portfolio_id=int(portfolio.pk),
                        source_id=source_id,
                        target_id=target_id,
                    )
                )

    monkeypatch.setattr(repository, "legacy_sync_transaction", _coordinate_parent_scope)

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="closed-position-delete",
    ) as executor:
        try:
            _context, payload = portfolio_api_services.get_position_payload(
                user_id=int(owner.pk),
                position_id=source_id,
            )
        finally:
            if delete_futures:
                delete_futures[0].result(timeout=15)

    assert parent_entered == [True]
    assert len(holder_pids) == len(worker_pids) == len(delete_futures) == 1
    assert len(state_after_a_inside_lock) == 1
    assert state_after_a_inside_lock[0] == initial
    assert payload["id"] == target_id
    assert payload["shares"] == pytest.approx(float(target.quantity))
    assert _mapped_position_snapshot(
        account_id=account_id,
        asset_code=target.asset_code,
        portfolio_id=int(portfolio.pk),
        source_id=source_id,
        target_id=target_id,
    ) == ((), (), (), ())
