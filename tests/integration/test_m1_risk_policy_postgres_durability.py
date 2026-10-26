"""Native PostgreSQL proof for committed M1 revision immutability."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import (
    DEFAULT_DB_ALIAS,
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    router,
    transaction,
)
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.exceptions import IrreversibleError
from django.utils import timezone
from pytest_django.plugin import DjangoDbBlocker

from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

_migration = importlib.import_module(
    "apps.risk_center.migrations.0012_m1_rebalance_risk_policy_immutable"
)
_ActorId = int | str | UUID

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="committed durability and reverse-lock proof requires PostgreSQL",
)


@dataclass(frozen=True)
class _RevisionSchema:
    """Identify the one test-owned schema and synthetic actor row."""

    name: str
    actor_id: _ActorId
    test_database_name: str


@dataclass(frozen=True)
class _InsertAttempt:
    """Keep only non-sensitive connection and result facts from a worker insert."""

    backend_pid: int
    inserted: bool
    sqlstate: str | None


@pytest.fixture
def isolated_revision_schema(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[_RevisionSchema]:
    """Create one guarded M1 table in an owned schema inside the verified test DB."""

    database = connections[DEFAULT_DB_ALIAS]
    assert database.vendor == "postgresql"
    with django_db_blocker.unblock():
        test_database_name = assert_native_postgres_test_database(expected_name=django_db_setup)
    assert test_database_name == django_db_setup
    schema = _RevisionSchema(
        name=f"m1_revision_test_{uuid4().hex[:20]}",
        actor_id=1,
        test_database_name=test_database_name,
    )
    quote = database.ops.quote_name
    schema_created = False

    try:
        with django_db_blocker.unblock():
            database.ensure_connection()
            with database.cursor() as cursor:
                cursor.execute(f"CREATE SCHEMA {quote(schema.name)}")
            schema_created = True
            with database.cursor() as cursor:
                cursor.execute(f"SET search_path TO {quote(schema.name)}")

            schema = _create_synthetic_actor_table(database, schema)
            assert router.allow_migrate_model(DEFAULT_DB_ALIAS, M1RebalanceRiskPolicyRevisionModel)
            with database.schema_editor() as schema_editor:
                assert schema_editor.connection.alias == DEFAULT_DB_ALIAS
                schema_editor.create_model(M1RebalanceRiskPolicyRevisionModel)
                _migration.install_revision_immutability(django_apps, schema_editor)

        yield schema
    finally:
        if schema_created:
            with django_db_blocker.unblock():
                database.ensure_connection()
                assert_native_postgres_test_database(expected_name=schema.test_database_name)
                with database.cursor() as cursor:
                    cursor.execute("RESET search_path")
                    cursor.execute(f"DROP SCHEMA {quote(schema.name)} CASCADE")


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use the shared explicit Native PostgreSQL database for this module."""

    return native_postgres_test_database


def _create_synthetic_actor_table(
    database: BaseDatabaseWrapper,
    schema: _RevisionSchema,
) -> _RevisionSchema:
    """Create only the configured auth PK target needed by the revision FK."""

    user_model = get_user_model()
    user_table_name = user_model._meta.db_table
    if "." in user_table_name:
        raise AssertionError("The isolated PostgreSQL schema expects an unqualified auth table.")
    primary_key = user_model._meta.pk
    primary_key_type = primary_key.db_type(database)
    if not primary_key_type:
        raise AssertionError("The configured auth primary key has no PostgreSQL database type.")

    internal_type = primary_key.get_internal_type()
    if internal_type in {"AutoField", "BigAutoField", "SmallAutoField"}:
        actor_id: _ActorId = 1
    elif internal_type == "UUIDField":
        actor_id = uuid4()
    elif internal_type in {"CharField", "SlugField"}:
        actor_id = f"m1-test-{uuid4().hex}"
    else:
        raise AssertionError(
            f"Unsupported auth primary key type for this isolated test: {internal_type}"
        )

    quote = database.ops.quote_name
    user_table = quote(user_table_name)
    user_pk = quote(primary_key.column)
    with database.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {user_table} ({user_pk} {primary_key_type} PRIMARY KEY)")
        cursor.execute(f"INSERT INTO {user_table} ({user_pk}) VALUES (%s)", [actor_id])
    return _RevisionSchema(
        name=schema.name,
        actor_id=actor_id,
        test_database_name=schema.test_database_name,
    )


def _revision_values(*, actor_id: _ActorId, version: UUID) -> dict[str, object]:
    """Return a valid new M1 revision payload for a raw insert test."""

    now = timezone.now()
    return {
        "risk_policy_version": version,
        "account_id": 987654321,
        "actor_id": actor_id,
        "effective_from": now + timedelta(minutes=5),
        "effective_until": now + timedelta(days=1),
        "known_at": now,
        "reason": "Owner approved this explicit M1 risk version.",
        "max_single_position_state": "applicable",
        "max_single_position_pct": Decimal("19.000"),
        "max_single_position_reason": None,
        "max_total_position_state": "applicable",
        "max_total_position_pct": Decimal("90.000"),
        "max_total_position_reason": None,
        "max_stop_loss_state": "applicable",
        "max_stop_loss_pct": Decimal("7.000"),
        "max_stop_loss_reason": None,
        "source_snapshot_schema_version": "m1-risk-source-v1",
        "source_snapshot": json.dumps({"account_id": 987654321}),
        "risk_falsification_schema_version": "m1-risk-falsification-v1",
        "risk_falsification_rules": json.dumps({"status": "not_evaluated"}),
    }


def _insert_revision_raw(
    database: BaseDatabaseWrapper,
    *,
    actor_id: _ActorId,
    version: UUID,
) -> None:
    """Insert one valid revision through SQL, bypassing ORM creation safeguards."""

    values = _revision_values(actor_id=actor_id, version=version)
    quote = database.ops.quote_name
    table = quote(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
    columns = ", ".join(quote(column) for column in values)
    placeholders = ", ".join(
        "%s::jsonb" if column in {"source_snapshot", "risk_falsification_rules"} else "%s"
        for column in values
    )
    with database.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )


def _backend_pid(database: BaseDatabaseWrapper) -> int:
    """Return the current PostgreSQL backend identity for lock evidence."""

    with database.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is int
    return cast(int, row[0])


def _read_revision_on_independent_connection(
    database: BaseDatabaseWrapper,
    schema: _RevisionSchema,
    version: UUID,
) -> tuple[int, str, str, str]:
    """Read the committed row from a second PostgreSQL backend."""

    reader = database.copy(alias=f"m1_revision_reader_{uuid4().hex[:12]}")
    try:
        quote = reader.ops.quote_name
        table = quote(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
        with reader.cursor() as cursor:
            cursor.execute(f"SET search_path TO {quote(schema.name)}")
            cursor.execute(
                "SELECT pg_backend_pid(), current_database(), risk_policy_version::text, reason "
                f"FROM {table} WHERE risk_policy_version = %s",
                [version],
            )
            row = cursor.fetchone()
        assert row is not None and len(row) == 4
        assert type(row[0]) is int
        assert isinstance(row[1], str)
        assert isinstance(row[2], str)
        assert isinstance(row[3], str)
        return cast(tuple[int, str, str, str], row)
    finally:
        reader.close()


def _driver_sqlstate(error: DatabaseError) -> str | None:
    """Read a database driver's stable SQLSTATE without exposing raw diagnostics."""

    cause = error.__cause__
    if cause is None:
        return None
    for attribute in ("sqlstate", "pgcode"):
        value = getattr(cause, attribute, None)
        if isinstance(value, str):
            return value
    return None


def test_committed_revision_survives_independent_read_and_raw_mutation_attempts(
    isolated_revision_schema: _RevisionSchema,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """Prove commit visibility and active database guards across separate sessions."""

    database = connections[DEFAULT_DB_ALIAS]
    quote = database.ops.quote_name
    table = quote(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
    version = uuid4()

    with django_db_blocker.unblock():
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            _insert_revision_raw(
                database,
                actor_id=isolated_revision_schema.actor_id,
                version=version,
            )

        primary_pid = _backend_pid(database)
        reader_pid, database_name, stored_version, reason = (
            _read_revision_on_independent_connection(
                database,
                isolated_revision_schema,
                version,
            )
        )
        assert reader_pid != primary_pid
        assert database_name == isolated_revision_schema.test_database_name
        assert stored_version == str(version)
        assert reason == "Owner approved this explicit M1 risk version."

        with pytest.raises(DatabaseError):
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                with database.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {table} SET reason = %s WHERE risk_policy_version = %s",
                        ["Raw SQL changed committed history.", version],
                    )
        with pytest.raises(DatabaseError):
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                with database.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM {table} WHERE risk_policy_version = %s",
                        [version],
                    )
        with pytest.raises(DatabaseError):
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                with database.cursor() as cursor:
                    cursor.execute(f"TRUNCATE TABLE {table}")

        with pytest.raises(IrreversibleError, match="audit history"):
            with database.schema_editor() as schema_editor:
                _migration.remove_revision_immutability(django_apps, schema_editor)

        with pytest.raises(DatabaseError):
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                with database.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {table} SET reason = %s WHERE risk_policy_version = %s",
                        ["A failed reverse removed a guard.", version],
                    )

        reader_pid_after, database_name_after, stored_version_after, reason_after = (
            _read_revision_on_independent_connection(database, isolated_revision_schema, version)
        )
        assert reader_pid_after != primary_pid
        assert database_name_after == isolated_revision_schema.test_database_name
        assert stored_version_after == str(version)
        assert reason_after == "Owner approved this explicit M1 risk version."


def _insert_after_reverse_starts(
    schema: _RevisionSchema,
    connected: Event,
    backend_pids: list[int],
) -> _InsertAttempt:
    """Try one valid insert from a fresh backend while reverse holds its table lock."""

    close_old_connections()
    database = connections[DEFAULT_DB_ALIAS]
    try:
        quote = database.ops.quote_name
        with database.cursor() as cursor:
            cursor.execute(f"SET search_path TO {quote(schema.name)}")
            cursor.execute("SET lock_timeout = '8000ms'")
            cursor.execute("SELECT current_database(), pg_backend_pid()")
            identity_row = cursor.fetchone()
        assert identity_row is not None and len(identity_row) == 2
        assert identity_row[0] == schema.test_database_name
        assert type(identity_row[1]) is int
        backend_pid = cast(int, identity_row[1])
        backend_pids.append(backend_pid)
        connected.set()
        try:
            _insert_revision_raw(database, actor_id=schema.actor_id, version=uuid4())
        except DatabaseError as error:
            return _InsertAttempt(
                backend_pid=backend_pid,
                inserted=False,
                sqlstate=_driver_sqlstate(error),
            )
        return _InsertAttempt(backend_pid=backend_pid, inserted=True, sqlstate=None)
    finally:
        database.close()


def _wait_for_reverse_table_lock(
    database: BaseDatabaseWrapper,
    *,
    holder_pid: int,
    waiter_pid: int,
    future: Future[_InsertAttempt],
) -> None:
    """Require PostgreSQL to report the second backend blocked on the M1 insert."""

    table_name = M1RebalanceRiskPolicyRevisionModel._meta.db_table.lower()
    deadline = monotonic() + 6.0
    last_wait_event: str | None = None
    last_query = ""
    last_blockers: tuple[int, ...] = ()
    while monotonic() < deadline:
        with database.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT wait_event_type, query, pg_blocking_pids(pid) "
                "FROM pg_stat_activity WHERE pid = %s",
                [waiter_pid],
            )
            row = cursor.fetchone()
        if row is not None and len(row) == 3:
            wait_event_value, query_value, blockers_value = row
            last_wait_event = wait_event_value if isinstance(wait_event_value, str) else None
            last_query = query_value if isinstance(query_value, str) else ""
            if isinstance(blockers_value, (list, tuple)):
                last_blockers = tuple(int(pid) for pid in blockers_value)
            query_lower = last_query.lstrip().lower()
            if (
                last_wait_event == "Lock"
                and query_lower.startswith("insert ")
                and table_name in query_lower
                and holder_pid in last_blockers
            ):
                return
        if future.done():
            finished = future.result()
            raise AssertionError(
                "The insert completed before the reverse migration held its table lock: "
                f"{finished!r}"
            )
        sleep(0.02)
    raise AssertionError(
        "The M1 insert did not wait behind reverse migration; "
        f"wait_event={last_wait_event!r}, blockers={last_blockers!r}, query={last_query!r}"
    )


def test_empty_reverse_holds_lock_until_revision_table_is_dropped(
    isolated_revision_schema: _RevisionSchema,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """Prevent a new row from racing the empty-history reverse check."""

    database = connections[DEFAULT_DB_ALIAS]
    table = database.ops.quote_name(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
    with django_db_blocker.unblock():
        with database.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
            assert cursor.fetchone() is None

        connected = Event()
        backend_pids: list[int] = []
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="m1-revision-reverse"
        ) as executor:
            with database.schema_editor() as schema_editor:
                holder_pid = _backend_pid(database)
                _migration.remove_revision_immutability(django_apps, schema_editor)
                future: Future[_InsertAttempt] = executor.submit(
                    _insert_after_reverse_starts,
                    isolated_revision_schema,
                    connected,
                    backend_pids,
                )
                assert connected.wait(
                    timeout=5
                ), "The independent PostgreSQL backend did not connect."
                assert len(backend_pids) == 1
                waiter_pid = backend_pids[0]
                assert waiter_pid != holder_pid
                _wait_for_reverse_table_lock(
                    database,
                    holder_pid=holder_pid,
                    waiter_pid=waiter_pid,
                    future=future,
                )
                schema_editor.delete_model(M1RebalanceRiskPolicyRevisionModel)

            insert_attempt = future.result(timeout=10)
            assert insert_attempt.backend_pid == waiter_pid
            assert insert_attempt.inserted is False
            assert insert_attempt.sqlstate == "42P01"
            with database.cursor() as cursor:
                cursor.execute(
                    "SELECT to_regclass(%s)", [M1RebalanceRiskPolicyRevisionModel._meta.db_table]
                )
                assert cursor.fetchone() == (None,)
