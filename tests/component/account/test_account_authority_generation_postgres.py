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
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, close_old_connections, connections, transaction

from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationChanged,
    AccountAuthorityGenerationCoverageError,
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    caller_owned_account_authority_generation_fence,
    lock_account_authority_generation_fence,
    read_account_authority_generation_proof,
    verify_account_authority_generation_coverage,
    verify_account_authority_generation_runtime_acl,
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
_LOCK_FUNCTION_MIGRATION = import_module(
    "apps.account.migrations.0066_account_authority_generation_lock"
)
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
    generation_owner = f"acct_auth_owner_{uuid4().hex}"
    quoted_generation_owner = connection.ops.quote_name(generation_owner)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_namespace AS namespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          namespace.nspacl,
                          pg_catalog.acldefault('n', namespace.nspowner)
                      )
                  ) AS acl
                 WHERE namespace.nspname = 'public'
                   AND acl.grantee = 0
                   AND acl.privilege_type = 'CREATE'
            )
            """)
        public_create_row = cast(tuple[object, ...] | None, cursor.fetchone())
    if public_create_row is None or type(public_create_row[0]) is not bool:
        raise AssertionError("public schema ACL catalog row is malformed")
    public_had_create = public_create_row[0]
    with connection.cursor() as cursor:
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    with connection.schema_editor() as editor:
        editor.create_model(AccountAuthorityGenerationModel)
    try:
        with connection.schema_editor() as editor:
            _SCHEMA_FUNCTIONS.seed_generation_row(apps, editor)
            _SCHEMA_FUNCTIONS.install_source_triggers(apps, editor)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE ROLE {quoted_generation_owner} "
                    "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
                )
                cursor.execute(f"GRANT CREATE ON SCHEMA public TO {quoted_generation_owner}")
                cursor.execute(
                    f"ALTER TABLE {_GENERATION_TABLE} OWNER TO {quoted_generation_owner}"
                )
            _LOCK_FUNCTION_MIGRATION.install_generation_lock_function(apps, editor)
        yield owner_alias
    finally:
        with connection.schema_editor() as editor:
            _LOCK_FUNCTION_MIGRATION.remove_generation_lock_function(apps, editor)
            _SCHEMA_FUNCTIONS.remove_source_triggers(apps, editor)
            editor.delete_model(AccountAuthorityGenerationModel)
        with connection.cursor() as cursor:
            cursor.execute(f"DROP OWNED BY {quoted_generation_owner}")
            cursor.execute(f"DROP ROLE {quoted_generation_owner}")
            if public_had_create:
                cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")


@pytest.fixture
def migrator_alias(generation_alias: str) -> Iterator[str]:
    """Connect as a NOINHERIT migrator that can SET ROLE to the generation owner."""

    connection = connections[generation_alias]
    migrator_role = f"acct_auth_migrator_{uuid4().hex}"
    quoted_migrator = connection.ops.quote_name(migrator_role)
    password = uuid4().hex
    alias = "account_authority_generation_migrator"
    if alias in connections.databases:
        raise AssertionError("test migrator alias already exists")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT owner_role.rolname
              FROM pg_catalog.pg_class AS generation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = generation.relnamespace
              JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = generation.relowner
             WHERE namespace.nspname = 'public'
               AND generation.relname = 'account_authority_generation'
            """)
        owner_row = cast(tuple[object, ...] | None, cursor.fetchone())
        if owner_row is None or type(owner_row[0]) is not str:
            raise AssertionError("generation owner role is unavailable")
        generation_owner = owner_row[0]
        quoted_generation_owner = connection.ops.quote_name(generation_owner)
        cursor.execute(
            f"CREATE ROLE {quoted_migrator} LOGIN PASSWORD '{password}' "
            "NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE"
        )
        cursor.execute(
            f"GRANT {quoted_generation_owner} TO {quoted_migrator} " "WITH INHERIT FALSE, SET TRUE"
        )
    migrator_settings = cast(dict[str, object], deepcopy(connection.settings_dict))
    migrator_settings["USER"] = migrator_role
    migrator_settings["PASSWORD"] = password
    migrator_settings["CONN_MAX_AGE"] = 0
    connections.databases[alias] = migrator_settings  # type: ignore[assignment]
    migrator_connection = connections[alias]
    try:
        migrator_connection.ensure_connection()
        yield alias
    finally:
        migrator_connection.close()
        del connections[alias]
        connections.databases.pop(alias, None)
        with connection.cursor() as cursor:
            cursor.execute(f"REVOKE {quoted_generation_owner} FROM {quoted_migrator}")
            cursor.execute(f"DROP OWNED BY {quoted_migrator}")
            cursor.execute(f"DROP ROLE {quoted_migrator}")


@pytest.fixture
def runtime_alias(generation_alias: str) -> Iterator[str]:
    """Connect as a distinct runtime login with generation SELECT and wrapper EXECUTE."""

    connection = connections[generation_alias]
    role_name = f"acct_auth_runtime_{uuid4().hex}"
    quoted_role = connection.ops.quote_name(role_name)
    password = uuid4().hex
    alias = "account_authority_generation_runtime"
    if alias in connections.databases:
        raise AssertionError("test runtime alias already exists")
    source_tables = ", ".join(f'public."{table_name}"' for table_name in _EXPECTED_TABLES)
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE ROLE {quoted_role} LOGIN PASSWORD '{password}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE"
        )
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_role}")
        cursor.execute(f"GRANT SELECT ON TABLE {_GENERATION_TABLE} TO {quoted_role}")
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION public.account_authority_generation_lock() "
            f"TO {quoted_role}"
        )
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {source_tables} TO {quoted_role}"
        )
        cursor.execute(
            """
            SELECT sequence_namespace.nspname, sequence_relation.relname
              FROM pg_catalog.pg_class AS source_relation
              JOIN pg_catalog.pg_namespace AS source_namespace
                ON source_namespace.oid = source_relation.relnamespace
              JOIN pg_catalog.pg_attribute AS source_id
                ON source_id.attrelid = source_relation.oid
               AND source_id.attname = 'id'
               AND source_id.attnum > 0
              JOIN pg_catalog.pg_depend AS dependency
                ON dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
               AND dependency.refobjid = source_relation.oid
               AND dependency.refobjsubid = source_id.attnum
               AND dependency.deptype IN ('a', 'i')
              JOIN pg_catalog.pg_class AS sequence_relation
                ON sequence_relation.oid = dependency.objid
               AND sequence_relation.relkind = 'S'
              JOIN pg_catalog.pg_namespace AS sequence_namespace
                ON sequence_namespace.oid = sequence_relation.relnamespace
             WHERE source_namespace.nspname = 'public'
               AND source_relation.relname::text = ANY(%s::text[])
            """,
            [list(_EXPECTED_TABLES)],
        )
        sequences = cast(list[tuple[object, ...]], cursor.fetchall())
        for sequence in sequences:
            schema_name, sequence_name = sequence
            if type(schema_name) is not str or type(sequence_name) is not str:
                raise AssertionError("source sequence catalog row is malformed")
            cursor.execute(
                f"GRANT USAGE ON SEQUENCE "
                f"{connection.ops.quote_name(schema_name)}."
                f"{connection.ops.quote_name(sequence_name)} TO {quoted_role}"
            )
    runtime_settings = cast(dict[str, object], deepcopy(connection.settings_dict))
    runtime_settings["USER"] = role_name
    runtime_settings["PASSWORD"] = password
    runtime_settings["CONN_MAX_AGE"] = 0
    connections.databases[alias] = runtime_settings  # type: ignore[assignment]
    runtime_connection = connections[alias]
    try:
        runtime_connection.ensure_connection()
        yield alias
    finally:
        runtime_connection.close()
        del connections[alias]
        connections.databases.pop(alias, None)
        with connection.cursor() as cursor:
            cursor.execute(f"DROP OWNED BY {quoted_role}")
            cursor.execute(f"DROP ROLE {quoted_role}")


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


def test_runtime_lock_wrapper_enforces_minimum_generation_acl(
    generation_alias: str,
    runtime_alias: str,
    migrator_alias: str,
) -> None:
    """Allow a read-only runtime role to lock through its owner-owned wrapper only."""

    connection = connections[runtime_alias]
    proof = _read_rr_proof(runtime_alias)
    with pytest.raises(AccountAuthorityGenerationCoverageError, match="ACL contract"):
        verify_account_authority_generation_runtime_acl(using=generation_alias)

    with connections[runtime_alias].schema_editor() as editor:
        with pytest.raises(RuntimeError, match="without function-owner role"):
            _LOCK_FUNCTION_MIGRATION.remove_generation_lock_function(apps, editor)

    migrator_connection = connections[migrator_alias]
    with migrator_connection.cursor() as cursor:
        cursor.execute("""
            SELECT session_role.rolsuper,
                   pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
                   pg_catalog.pg_has_role(
                       session_user,
                       generation.relowner,
                       'SET'
                   ),
                   owner_role.rolcanlogin,
                   owner_role.rolsuper
              FROM pg_catalog.pg_class AS generation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = generation.relnamespace
              JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = generation.relowner
              JOIN pg_catalog.pg_roles AS session_role
                ON session_role.rolname = session_user
             WHERE namespace.nspname = 'public'
               AND generation.relname = 'account_authority_generation'
            """)
        migrator_contract = cast(tuple[object, ...] | None, cursor.fetchone())
    assert migrator_contract == (False, False, True, False, False)
    with migrator_connection.schema_editor() as editor:
        _LOCK_FUNCTION_MIGRATION.remove_generation_lock_function(apps, editor)
    with migrator_connection.schema_editor() as editor:
        _LOCK_FUNCTION_MIGRATION.install_generation_lock_function(apps, editor)
    with pytest.raises(AccountAuthorityGenerationCoverageError, match="ACL contract"):
        verify_account_authority_generation_runtime_acl(using=runtime_alias)
    runtime_connection = connections[runtime_alias]
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        runtime_row = cast(tuple[object, ...] | None, cursor.fetchone())
    if runtime_row is None or type(runtime_row[0]) is not str:
        raise AssertionError("runtime login role identity is unavailable")
    quoted_runtime_role = connections[generation_alias].ops.quote_name(runtime_row[0])
    with connections[generation_alias].cursor() as cursor:
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION public.account_authority_generation_lock() "
            f"TO {quoted_runtime_role}"
        )
    verify_account_authority_generation_runtime_acl(using=runtime_alias)

    with transaction.atomic(using=runtime_alias):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT function.prosecdef,
                       function.proconfig,
                       table_owner.oid = function.proowner,
                       NOT table_owner.rolcanlogin,
                       NOT table_owner.rolsuper,
                       pg_catalog.has_table_privilege(
                           current_user, generation.oid, 'SELECT'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation.oid, 'UPDATE'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation.oid, 'TRUNCATE'
                       ),
                       pg_catalog.has_function_privilege(
                           current_user, function.oid, 'EXECUTE'
                       ),
                       pg_catalog.has_function_privilege(
                           current_user, bump_function.oid, 'EXECUTE'
                       ),
                       pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
                       EXISTS (
                           SELECT 1
                             FROM pg_catalog.aclexplode(
                                 COALESCE(
                                     function.proacl,
                                     pg_catalog.acldefault('f', function.proowner)
                                 )
                             ) AS acl
                            WHERE acl.grantee = 0
                              AND acl.privilege_type = 'EXECUTE'
                       )
                  FROM pg_catalog.pg_class AS generation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = generation.relnamespace
                  JOIN pg_catalog.pg_roles AS table_owner
                    ON table_owner.oid = generation.relowner
                  CROSS JOIN pg_catalog.pg_proc AS bump_function
                  CROSS JOIN pg_catalog.pg_proc AS function
                 WHERE namespace.nspname = 'public'
                   AND generation.relname = 'account_authority_generation'
                   AND function.oid = pg_catalog.to_regprocedure(
                       'public.account_authority_generation_lock()'
                   )
                   AND bump_function.oid = pg_catalog.to_regprocedure(
                       'public.account_authority_generation_bump()'
                   )
                """)
            catalog_row = cast(tuple[object, ...] | None, cursor.fetchone())
        assert catalog_row == (
            True,
            ["search_path=pg_catalog"],
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
        )
        verify_account_authority_generation_runtime_acl(using=runtime_alias)

        with pytest.raises(DatabaseError):
            with transaction.atomic(using=runtime_alias):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {_GENERATION_TABLE} SET generation = generation + 1 "
                        "WHERE singleton = 1"
                    )
        with pytest.raises(DatabaseError):
            with transaction.atomic(using=runtime_alias):
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT generation FROM {_GENERATION_TABLE} "
                        "WHERE singleton = 1 FOR SHARE"
                    )

        assert (
            lock_account_authority_generation_fence(
                proof,
                using=runtime_alias,
            )
            == proof.generation
        )

    owner_connection = connections[generation_alias]
    with owner_connection.cursor() as cursor:
        cursor.execute("""
            SELECT owner_role.rolname
              FROM pg_catalog.pg_class AS generation
              JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = generation.relowner
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = generation.relnamespace
             WHERE namespace.nspname = 'public'
               AND generation.relname = 'account_authority_generation'
            """)
        owner_row = cast(tuple[object, ...] | None, cursor.fetchone())
    with connections[runtime_alias].cursor() as cursor:
        cursor.execute("SELECT current_user")
        runtime_row = cast(tuple[object, ...] | None, cursor.fetchone())
    if (
        owner_row is None
        or runtime_row is None
        or type(owner_row[0]) is not str
        or type(runtime_row[0]) is not str
    ):
        raise AssertionError("runtime or generation owner role identity is unavailable")
    owner_role = owner_row[0]
    runtime_role = runtime_row[0]
    quoted_owner = owner_connection.ops.quote_name(owner_role)
    quoted_runtime = owner_connection.ops.quote_name(runtime_role)
    with owner_connection.cursor() as cursor:
        cursor.execute(f"GRANT {quoted_owner} TO {quoted_runtime}")
    try:
        with transaction.atomic(using=runtime_alias):
            with pytest.raises(AccountAuthorityGenerationCoverageError, match="ACL contract"):
                verify_account_authority_generation_runtime_acl(using=runtime_alias)
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {quoted_owner}")
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege("
                    "current_user, 'public.account_authority_generation', 'UPDATE')"
                )
                escalation_row = cast(tuple[object, ...] | None, cursor.fetchone())
            assert escalation_row == (True,)
    finally:
        with owner_connection.cursor() as cursor:
            cursor.execute(f"REVOKE {quoted_owner} FROM {quoted_runtime}")


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
    runtime_alias: str,
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
    connections.databases[competing_alias] = deepcopy(connections.databases[runtime_alias])
    started = Event()
    backend_pids: Queue[int] = Queue()
    try:
        proof = _read_rr_proof(runtime_alias)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic(using=runtime_alias):
                assert (
                    lock_account_authority_generation_fence(
                        proof,
                        using=runtime_alias,
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
            with transaction.atomic(using=runtime_alias):
                lock_account_authority_generation_fence(proof, using=runtime_alias)

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


def test_two_generation_fences_coexist_and_each_blocks_source_writer(
    generation_alias: str,
    runtime_alias: str,
) -> None:
    """Allow two final readers together while either held fence blocks source DML."""

    competing_alias = "account_authority_generation_second_fence"
    if competing_alias in connections.databases:
        raise AssertionError("test fence alias already exists")
    connections.databases[competing_alias] = deepcopy(connections[runtime_alias].settings_dict)
    first_proof = _read_rr_proof(runtime_alias)
    second_proof = _read_rr_proof(competing_alias)
    second_entered = Event()
    release_second = Event()
    writer_started = Event()
    backend_pids: Queue[int] = Queue()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            with transaction.atomic(using=runtime_alias):
                with connections[runtime_alias].cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
                with caller_owned_account_authority_generation_fence(
                    first_proof, using=runtime_alias
                ) as first_generation:
                    assert first_generation == first_proof.generation
                    second_fence = executor.submit(
                        _hold_generation_fence,
                        competing_alias,
                        second_proof,
                        second_entered,
                        release_second,
                    )
                    assert second_entered.wait(timeout=5)

                    writer = executor.submit(
                        _direct_zero_row_source_writer,
                        competing_alias,
                        writer_started,
                        backend_pids,
                    )
                    assert writer_started.wait(timeout=5)
                    backend_pid = backend_pids.get(timeout=5)
                    assert _wait_for_lock_wait(generation_alias, backend_pid)
                    assert not writer.done()

                    release_second.set()
                    assert second_fence.result(timeout=10) == first_proof.generation
                    assert not writer.done()
                assert not writer.done()
            assert writer.result(timeout=10) == first_proof.generation + 1
    finally:
        release_second.set()
        connections[competing_alias].close()
        connections.databases.pop(competing_alias, None)


def test_generation_context_rejects_same_transaction_source_write_and_rolls_back(
    generation_alias: str,
    runtime_alias: str,
) -> None:
    """Detect an in-fence source trigger bump and mark the caller transaction rollback-only."""

    proof = _read_rr_proof(runtime_alias)
    with pytest.raises(AccountAuthorityGenerationChanged, match="inside the caller fence"):
        with transaction.atomic(using=runtime_alias):
            with connections[runtime_alias].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            with caller_owned_account_authority_generation_fence(proof, using=runtime_alias):
                with connections[runtime_alias].cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {_SIMULATED_SOURCE_TABLE} SET id = id WHERE id = %s",
                        [-1],
                    )
                assert _generation(runtime_alias) == proof.generation + 1

    assert _generation(generation_alias) == proof.generation


def test_generation_context_rejects_raw_commit_and_new_xid_on_same_connection(
    generation_alias: str,
    runtime_alias: str,
) -> None:
    """Detect a caller bypassing Django atomic with psycopg COMMIT on the same socket."""

    proof = _read_rr_proof(runtime_alias)
    connection = connections[runtime_alias]
    with pytest.raises(AccountAuthorityGenerationUnavailable, match="transaction identity changed"):
        with transaction.atomic(using=runtime_alias):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            with caller_owned_account_authority_generation_fence(proof, using=runtime_alias):
                raw_connection = connection.connection
                if raw_connection is None:
                    raise AssertionError("Django physical connection is unavailable")
                raw_connection.commit()
                with raw_connection.cursor() as cursor:
                    cursor.execute("SELECT 1")


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


def _hold_generation_fence(
    using: str,
    proof: AccountAuthorityGenerationProof,
    entered: Event,
    release: Event,
) -> int:
    """Hold one independent caller-owned share fence until the test releases it."""

    close_old_connections()
    try:
        with transaction.atomic(using=using):
            with connections[using].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            with caller_owned_account_authority_generation_fence(proof, using=using) as generation:
                entered.set()
                if not release.wait(timeout=10):
                    raise AssertionError("test did not release the second generation fence")
                return generation
    finally:
        connections[using].close()


def _direct_zero_row_source_writer(
    using: str,
    started: Event,
    backend_pids: Queue[int],
) -> int:
    """Bump the source generation with zero-row DML after any held fences release."""

    close_old_connections()
    try:
        with transaction.atomic(using=using):
            with connections[using].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cast(tuple[object, ...] | None, cursor.fetchone())
                if row is None or type(row[0]) is not int:
                    raise AssertionError("writer backend PID was not returned")
                backend_pids.put(row[0])
                started.set()
                cursor.execute(
                    f"UPDATE {_SIMULATED_SOURCE_TABLE} SET id = id WHERE id = %s",
                    [-1],
                )
        return _generation(using)
    finally:
        connections[using].close()


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
