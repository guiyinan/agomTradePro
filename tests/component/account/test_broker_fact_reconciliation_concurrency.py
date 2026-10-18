"""Two PostgreSQL connections must preserve exactly one fact and balance delta."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from time import monotonic, sleep

import pytest
from django.contrib.auth.models import User
from django.db import connection, connections, transaction

from apps.account.application.manual_trade_sync import ManualTradeImportUseCase
from apps.account.infrastructure.models import PortfolioModel, TransactionModel
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
