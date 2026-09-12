"""Concurrent requests through the actual production creation orchestrator."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import Event
from time import monotonic, sleep

from django.db import connections

from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration import canonical_account_creation as orchestration
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.component.account.test_canonical_creation_orchestration_postgres import (
    _counts,
    _reject_default,
)
from tests.unit.simulated_trading.test_canonical_account_creation_request import _request
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)


def test_concurrent_identical_requests_commit_one_graph_and_replay_the_winner(
    creation_chain_alias, monkeypatch
):
    alias = creation_chain_alias
    user, _ = _new_user(alias)
    request = replace(_request(), user_id=user.pk)
    settings = _settings()
    first_alias = "evid07_creation_first"
    second_alias = "evid07_creation_second"
    first_locked = Event()
    release_first = Event()
    second_connected = Event()
    backend_ids = {}
    original_transaction = orchestration.account_creation_transaction

    @contextmanager
    def coordinated_transaction(*, using, user_id):
        with original_transaction(using=using, user_id=user_id):
            if using == first_alias:
                first_locked.set()
                assert release_first.wait(60), "test did not release the first creator"
            yield

    def create(using):
        connection = connections[using]
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '180s'")
                cursor.execute("SET statement_timeout = '180s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_ids[using] = cursor.fetchone()[0]
            if using == second_alias:
                second_connected.set()
            with connections["default"].execute_wrapper(_reject_default):
                return orchestration.create_canonical_account(
                    request=request, using=using, settings=settings
                )
        finally:
            connection.close()

    for worker_alias in (first_alias, second_alias):
        assert worker_alias not in connections.databases
        connections.databases[worker_alias] = deepcopy(connections.databases[alias])
    monkeypatch.setattr(orchestration, "account_creation_transaction", coordinated_transaction)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                first = pool.submit(create, first_alias)
                assert first_locked.wait(30), "first creator did not hold the user lock"
                second = pool.submit(create, second_alias)
                assert second_connected.wait(30), "second creator did not connect"
                blocked = False
                deadline = monotonic() + 30
                while monotonic() < deadline:
                    with connections[alias].cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [backend_ids[second_alias]])
                        blocked = backend_ids[first_alias] in cursor.fetchone()[0]
                    if blocked:
                        break
                    sleep(0.05)
                assert blocked, "second creator was not observed waiting for the first transaction"
                release_first.set()
                first_result = first.result(timeout=300)
                second_result = second.result(timeout=300)
            finally:
                release_first.set()
        assert not first_result.replayed and second_result.replayed
        assert first_result.account.account_id == second_result.account.account_id
        assert first_result.binding == second_result.binding
        assert SimulatedAccountModel.objects.using(alias).count() == 1
        assert _counts(alias) == [1, 1, 1, 1, 1, 1, 0, 1]
    finally:
        release_first.set()
        for worker_alias in (first_alias, second_alias):
            connections.databases.pop(worker_alias, None)
