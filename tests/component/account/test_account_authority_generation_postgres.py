"""PostgreSQL contracts for Account authority generation coverage and fencing."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from queue import Queue
from threading import Event
from time import monotonic, sleep
from typing import cast

import pytest
from django.apps import apps
from django.db import DatabaseError, close_old_connections, connections, transaction

from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationCoverageError,
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    lock_account_authority_generation_fence,
    read_account_authority_generation_proof,
    verify_account_authority_generation_coverage,
)
from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from tests.component.simulated_trading.test_simulated_account_row_source_v2_repository import (
    _append as _append_simulated_source,
)
from tests.component.simulated_trading.test_simulated_account_row_source_v2_repository import (
    _source as _simulated_source,
)

pytest_plugins = [
    "tests.component.account.test_owner_tenant_authority_v3_fresh_v5_parents_postgres"
]
_SCHEMA_FUNCTIONS = import_module("apps.account.migrations.0065_account_authority_generation")
_SIMULATED_SOURCE_TABLE = "public.simulated_account_row_source_v2_ledger"
_GENERATION_TABLE = "public.account_authority_generation"
_EXPECTED_TABLES: tuple[str, ...] = (
    "account_actor_authority_source_v3_ledger",
    "account_actor_authority_source_v3_root_lock",
    "account_allocated_physical_row_observation_v3_ledger",
    "account_auth_context_source_v3_anchor",
    "account_auth_context_source_v3_ledger",
    "account_owner_assignment_evidence_v5_ledger",
    "account_owner_assignment_provenance_receipt_v5_ledger",
    "account_owner_assignment_subject_v5_ledger",
    "account_owner_tenant_authority_v3_ledger",
    "account_owner_tenant_authority_v3_revocation_ledger",
    "account_physical_row_observation_v2_ledger",
    "account_rbac_authority_source_v3_anchor",
    "account_rbac_authority_source_v3_ledger",
    "account_single_owner_authority_policy_v1",
    "account_user_authority_source_v3_anchor",
    "account_user_authority_source_v3_ledger",
    "canonical_account_creation_allocation_ledger",
    "canonical_account_creation_binding_ledger",
    "canonical_account_creation_binding_v2_ledger",
    "canonical_account_creation_consumption_claim_ledger",
    "canonical_account_ownership_reobservation_v1_ledger",
    "simulated_account_row_source_v2_ledger",
)


@pytest.fixture
def generation_alias(owner_alias: str) -> Iterator[str]:
    """Install the production migration operations over the isolated 22-table schema."""

    connection = connections[owner_alias]
    with connection.schema_editor() as editor:
        editor.create_model(AccountAuthorityGenerationModel)
    try:
        with connection.schema_editor() as editor:
            _SCHEMA_FUNCTIONS.seed_generation_row(apps, editor)
            _SCHEMA_FUNCTIONS.install_source_triggers(apps, editor)
        yield owner_alias
    finally:
        with connection.schema_editor() as editor:
            _SCHEMA_FUNCTIONS.remove_source_triggers(apps, editor)
            editor.delete_model(AccountAuthorityGenerationModel)


def test_coverage_verifier_requires_exactly_22_enabled_source_triggers(
    generation_alias: str,
) -> None:
    """Expose the exact runtime 22-table closure and fail closed on a missing trigger."""

    coverage = verify_account_authority_generation_coverage(using=generation_alias)
    assert coverage.source_tables == _EXPECTED_TABLES
    assert coverage.generation == 0
    connection = connections[generation_alias]
    with connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER acct_auth_gen_truncate ON public.account_owner_tenant_authority_v3_ledger"
        )
    with pytest.raises(AccountAuthorityGenerationCoverageError):
        verify_account_authority_generation_coverage(using=generation_alias)
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TRIGGER acct_auth_gen_truncate
            BEFORE TRUNCATE ON public.account_owner_tenant_authority_v3_ledger
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.account_authority_generation_bump()
            """)
        cursor.execute(
            "ALTER TABLE public.account_owner_tenant_authority_v3_ledger "
            "ENABLE ALWAYS TRIGGER acct_auth_gen_truncate"
        )
    with pytest.raises(DatabaseError):
        with transaction.atomic(using=generation_alias):
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {_GENERATION_TABLE} WHERE singleton = 1")
                cursor.execute(
                    "UPDATE public.account_owner_tenant_authority_v3_ledger "
                    "SET id = id WHERE id = %s",
                    [-1],
                )
    assert verify_account_authority_generation_coverage(using=generation_alias).generation == 0
    with pytest.raises(AccountAuthorityGenerationUnavailable):
        read_account_authority_generation_proof(using=generation_alias)
    with transaction.atomic(using=generation_alias):
        with pytest.raises(AccountAuthorityGenerationUnavailable):
            read_account_authority_generation_proof(using=generation_alias)
    with transaction.atomic(using=generation_alias):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        proof = read_account_authority_generation_proof(using=generation_alias)
        with pytest.raises(AccountAuthorityGenerationUnavailable):
            lock_account_authority_generation_fence(proof, using=generation_alias)


def test_statement_triggers_count_once_and_rollback_with_source_changes(
    generation_alias: str,
) -> None:
    """Prove multi-row, zero-row, rollback, and TRUNCATE statement semantics."""

    repository = DjangoSimulatedAccountRowSourceV2Repository(using=generation_alias)
    first = _simulated_source()
    second = _simulated_source(
        source_version="mutation-2",
        row_updated_at=first.row_updated_at + timedelta(minutes=1),
        observed_at=first.observed_at + timedelta(minutes=1),
        recorded_at=first.recorded_at + timedelta(minutes=1),
        raw_observation_supersedes_content_hash=first.raw_observation_content_hash,
        supersedes_content_hash=first.content_hash,
    )
    _append_simulated_source(repository, first)
    _append_simulated_source(repository, second)
    connection = connections[generation_alias]
    before = _generation(generation_alias)
    with connection.cursor() as cursor:
        cursor.execute(f"""
            UPDATE {_SIMULATED_SOURCE_TABLE}
               SET raw_binding_seal = raw_binding_seal
             WHERE id IN (
                 SELECT id FROM {_SIMULATED_SOURCE_TABLE} ORDER BY id LIMIT 2
             )
            """)
    assert _generation(generation_alias) == before + 1

    before = _generation(generation_alias)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {_SIMULATED_SOURCE_TABLE} SET id = id WHERE id = %s",
            [-1],
        )
    assert _generation(generation_alias) == before + 1

    before = _generation(generation_alias)
    with pytest.raises(RuntimeError, match="rollback source statement"):
        with transaction.atomic(using=generation_alias):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {_SIMULATED_SOURCE_TABLE} SET id = id WHERE id = %s",
                    [-1],
                )
            assert _generation(generation_alias) == before + 1
            raise RuntimeError("rollback source statement")
    assert _generation(generation_alias) == before

    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {_SIMULATED_SOURCE_TABLE}")
    assert _generation(generation_alias) == before + 1


def test_direct_sql_zero_row_update_is_covered_on_all_22_tables(
    generation_alias: str,
) -> None:
    """Prove direct SQL reaches every fixed source table's statement trigger."""

    for table_name in _EXPECTED_TABLES:
        before = _generation(generation_alias)
        with connections[generation_alias].cursor() as cursor:
            cursor.execute(
                f'UPDATE public."{table_name}" SET id = id WHERE id = %s',
                [-1],
            )
        assert _generation(generation_alias) == before + 1, table_name


def test_generation_fence_waits_for_source_writer_and_serializes_after_commit(
    generation_alias: str,
) -> None:
    """Hold the RC fence while a direct source writer blocks on the generation row."""

    repository = DjangoSimulatedAccountRowSourceV2Repository(using=generation_alias)
    record = _append_simulated_source(repository, _simulated_source())
    source_id = record.source.source_id
    with connections[generation_alias].cursor() as cursor:
        cursor.execute(
            f"SELECT id FROM {_SIMULATED_SOURCE_TABLE} WHERE source_id = %s",
            [source_id],
        )
        source_row = cast(tuple[object, ...] | None, cursor.fetchone())
    assert source_row is not None and type(source_row[0]) is int
    source_row_id = source_row[0]
    competing_alias = "account_authority_generation_writer"
    if competing_alias in connections.databases:
        raise AssertionError("test writer alias already exists")
    connections.databases[competing_alias] = deepcopy(connections.databases[generation_alias])
    started = Event()
    backend_pids: Queue[int] = Queue()
    try:
        proof = _read_rr_proof(generation_alias)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=generation_alias):
                assert (
                    lock_account_authority_generation_fence(
                        proof,
                        using=generation_alias,
                    )
                    == proof.generation
                )
                future = executor.submit(
                    _direct_source_writer,
                    competing_alias,
                    source_row_id,
                    started,
                    backend_pids,
                )
                assert started.wait(timeout=5)
                backend_pid = backend_pids.get(timeout=5)
                assert _wait_for_lock_wait(generation_alias, backend_pid)
                assert not future.done()
            assert future.result(timeout=10) == proof.generation + 1
        with pytest.raises(AccountAuthorityGenerationChanged):
            with transaction.atomic(using=generation_alias):
                lock_account_authority_generation_fence(proof, using=generation_alias)

        with connections[generation_alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.account_user_authority_source_v3_anchor
                    (source_id, root_claim_hash, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                ["authority-generation-user-anchor", "a" * 64],
            )
            user_anchor_row = cast(tuple[object, ...] | None, cursor.fetchone())
            cursor.execute(
                """
                INSERT INTO public.account_auth_context_source_v3_anchor
                    (source_id, root_claim_hash, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                ["authority-generation-auth-anchor", "b" * 64],
            )
            auth_anchor_row = cast(tuple[object, ...] | None, cursor.fetchone())
        assert user_anchor_row is not None and type(user_anchor_row[0]) is int
        assert auth_anchor_row is not None and type(auth_anchor_row[0]) is int
        generation_before_writes = _generation(generation_alias)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=generation_alias):
                with connections[generation_alias].cursor() as cursor:
                    cursor.execute(
                        "UPDATE public.account_user_authority_source_v3_anchor "
                        "SET created_at = created_at WHERE id = %s",
                        [user_anchor_row[0]],
                    )
                source_writer = executor.submit(
                    _direct_anchor_writer,
                    competing_alias,
                    auth_anchor_row[0],
                    started,
                    backend_pids,
                )
                assert started.wait(timeout=5)
                backend_pid = backend_pids.get(timeout=5)
                assert _wait_for_lock_wait(generation_alias, backend_pid)
                with connections[generation_alias].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '3s'")
                    cursor.execute(
                        "UPDATE public.account_auth_context_source_v3_anchor "
                        "SET created_at = created_at WHERE id = %s",
                        [auth_anchor_row[0]],
                    )
                assert not source_writer.done()
            assert source_writer.result(timeout=10) == generation_before_writes + 3
    finally:
        connections[competing_alias].close()
        connections.databases.pop(competing_alias, None)


def _generation(using: str) -> int:
    """Read the transaction-visible generation value for one test alias."""

    with connections[using].cursor() as cursor:
        cursor.execute(f"SELECT generation FROM {_GENERATION_TABLE} WHERE singleton = 1")
        row = cast(tuple[object, ...] | None, cursor.fetchone())
    if row is None or type(row[0]) is not int:
        raise AssertionError("generation singleton row is unavailable")
    return row[0]


def _read_rr_proof(using: str) -> AccountAuthorityGenerationProof:
    """Read the proof in the same transaction mode required by a future full scan."""

    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_account_authority_generation_proof(using=using)


def _direct_source_writer(
    using: str,
    source_row_id: int,
    started: Event,
    backend_pids: Queue[int],
) -> int:
    """Update one source row and return the generation after the waiting commit."""

    close_old_connections()
    try:
        connection = connections[using]
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cast(tuple[object, ...] | None, cursor.fetchone())
                if row is None or type(row[0]) is not int:
                    raise AssertionError("writer PID was not returned")
                backend_pids.put(row[0])
                started.set()
                cursor.execute(
                    f"UPDATE {_SIMULATED_SOURCE_TABLE} "
                    "SET raw_binding_seal = raw_binding_seal WHERE id = %s",
                    [source_row_id],
                )
        return _generation(using)
    finally:
        connections[using].close()


def _direct_anchor_writer(
    using: str,
    anchor_row_id: int,
    started: Event,
    backend_pids: Queue[int],
) -> int:
    """Issue a second-table DML statement and report its committed generation."""

    close_old_connections()
    try:
        connection = connections[using]
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cast(tuple[object, ...] | None, cursor.fetchone())
                if row is None or type(row[0]) is not int:
                    raise AssertionError("anchor writer PID was not returned")
                backend_pids.put(row[0])
                started.set()
                cursor.execute(
                    "UPDATE public.account_auth_context_source_v3_anchor "
                    "SET created_at = created_at WHERE id = %s",
                    [anchor_row_id],
                )
        return _generation(using)
    finally:
        connections[using].close()


def _wait_for_lock_wait(using: str, backend_pid: int) -> bool:
    """Wait until PostgreSQL reports that the writer is blocked on the fence row."""

    deadline = monotonic() + 5
    while monotonic() < deadline:
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type FROM pg_catalog.pg_stat_activity WHERE pid = %s",
                [backend_pid],
            )
            row = cast(tuple[object, ...] | None, cursor.fetchone())
        if row is not None and row[0] == "Lock":
            return True
        sleep(0.02)
    return False
