"""Preserve the migration-owned authority clock during isolated test cleanup."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.conf import settings
from django.db import connection

from tests.support.native_postgres_database import assert_native_postgres_test_database

if TYPE_CHECKING:
    from django.core.management.color import Style
    from django.db.backends.base.operations import BaseDatabaseOperations


def _configured_source_database_name() -> str | None:
    """Read the configured source name without initializing a database backend."""

    database_settings: object = settings.DATABASES
    if not isinstance(database_settings, Mapping):
        return None
    default_settings: object = database_settings.get("default")
    if not isinstance(default_settings, Mapping):
        return None
    source_name = default_settings.get("NAME")
    if source_name is None:
        return None
    return str(source_name)


_SOURCE_DATABASE_NAME = _configured_source_database_name()
_AUTHORITY_TABLE = "account_authority_generation"


def _flush_tables_without_authority_generation(tables: list[str]) -> list[str]:
    """Allow restricted app sets to omit the singleton, but reject duplicate entries."""

    count = tables.count(_AUTHORITY_TABLE)
    if count > 1:
        raise AssertionError(
            "Django requested duplicate flush entries for the authority singleton."
        )
    return [table for table in tables if table != _AUTHORITY_TABLE]


def _generation_from_rows(rows: list[tuple[Any, ...]]) -> int:
    """Require exactly one existing singleton row and a valid nonnegative counter."""

    if len(rows) != 1 or rows[0][0] != 1:
        raise AssertionError("The authority singleton must exist exactly once during flush checks.")
    value = rows[0][1]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AssertionError("The authority singleton generation must be a nonnegative integer.")
    return value


def _assert_generation_non_decreasing(before: int, after: int) -> None:
    """Allow source triggers to bump the counter, but never allow it to go backward."""

    if after < before:
        raise AssertionError("The authority singleton generation decreased during flush.")


def _read_authority_generation(operations: BaseDatabaseOperations) -> int:
    """Read the physical singleton; a missing table or row is a hard test failure."""

    with operations.connection.cursor() as cursor:
        cursor.execute("SELECT singleton, generation FROM account_authority_generation")
        rows: list[tuple[Any, ...]] = cursor.fetchall()
    return _generation_from_rows(rows)


@pytest.fixture(scope="module", autouse=True)
def preserve_account_authority_generation(
    record_testsuite_property: Callable[[str, object], None],
) -> Iterator[None]:
    """Flush business rows while retaining the existing authority clock and ACLs."""
    source_database_name = _SOURCE_DATABASE_NAME
    if source_database_name is None:
        raise RuntimeError("Django setup did not capture the source database name.")

    if connection.vendor not in {"postgresql", "sqlite"}:
        yield
        return

    operations_class = type(connection.ops)
    original_sql_flush = operations_class.sql_flush
    original_execute_flush = operations_class.execute_sql_flush
    pending: set[int] = set()
    observations: list[tuple[int, int]] = []

    def guarded_sql_flush(
        operations: BaseDatabaseOperations,
        style: Style,
        tables: list[str],
        *,
        reset_sequences: bool = False,
        allow_cascade: bool = False,
    ) -> list[str]:
        """Exclude only the migration singleton, leaving all source triggers active."""
        assert operations.connection.alias == "default"
        selected = _flush_tables_without_authority_generation(tables)
        pending.add(id(operations))
        statements = original_sql_flush(
            operations,
            style,
            selected,
            reset_sequences=reset_sequences,
            allow_cascade=allow_cascade,
        )
        assert all("account_authority_generation" not in statement for statement in statements)
        return statements

    def generation(operations: BaseDatabaseOperations) -> int:
        """Read the actual seeded singleton without repairing absent state."""
        database = operations.connection
        if database.vendor == "postgresql":
            assert_native_postgres_test_database(database=database)
        else:
            assert database.vendor == "sqlite"
            active_name = str(database.settings_dict["NAME"])
            assert active_name == database.creation._get_test_db_name()
            in_memory = active_name == ":memory:" or (
                active_name.startswith("file:memorydb_") and "mode=memory" in active_name
            )
            if not in_memory:
                test_settings = database.settings_dict["TEST"]
                configured_name = test_settings.get("NAME")
                assert isinstance(configured_name, str) and configured_name
                active_path = Path(active_name).resolve()
                assert active_path == Path(configured_name).resolve()
                assert active_path != Path(source_database_name).resolve()
                assert (
                    active_path.parent
                    == (Path(tempfile.gettempdir()) / "agomtradepro-test-databases").resolve()
                )
                assert active_path.name == f"test_db_{os.getpid()}.sqlite3"
        return _read_authority_generation(operations)

    def guarded_execute_flush(operations: BaseDatabaseOperations, sql_list: list[str]) -> None:
        """Prove normal cleanup preserves the singleton's monotonic generation contract."""
        if id(operations) not in pending:
            original_execute_flush(operations, sql_list)
            return
        pending.remove(id(operations))
        before = generation(operations)
        original_execute_flush(operations, sql_list)
        after = generation(operations)
        _assert_generation_non_decreasing(before, after)
        observations.append((before, after))

    operations_class.sql_flush = guarded_sql_flush
    operations_class.execute_sql_flush = guarded_execute_flush
    try:
        yield
    finally:
        operations_class.sql_flush = original_sql_flush
        operations_class.execute_sql_flush = original_execute_flush
        record_testsuite_property("authority_generation_flushes", json.dumps(observations))
        print(f"Authority singleton preserved across {connection.vendor} flushes: {observations}")
