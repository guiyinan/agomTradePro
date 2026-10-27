"""Preserve the authority-generation singleton across isolated test database flushes."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import NoReturn

import pytest
from django.core.management.color import Style
from django.db import connection
from django.db.backends.base.operations import BaseDatabaseOperations
from django.test import TestCase, TransactionTestCase

from tests.support.native_postgres_database import assert_native_postgres_test_database

_CLOCK_TABLE = "account_authority_generation"
_SOURCE_DATABASE_NAME = str(connection.settings_dict["NAME"])
_SQLITE_ENGINE = "django.db.backends.sqlite3"
_DJANGO_DB_MARKER_POSITIONAL_OPTIONS = (
    "transaction",
    "reset_sequences",
    "databases",
    "serialized_rollback",
    "available_apps",
)


def _uses_default_database(databases: object) -> bool:
    """Return whether pytest-django's database selection includes ``default``."""
    if databases is None or databases == "__all__":
        return True
    if isinstance(databases, str):
        return databases == "default"
    if isinstance(databases, Iterable):
        return "default" in databases
    return True


def _is_nonserialized_transactional_item(item: pytest.Item) -> bool:
    """Identify default-database test items whose teardown performs a normal flush."""
    test_class = getattr(item, "cls", None)
    if isinstance(test_class, type) and issubclass(test_class, TransactionTestCase):
        if issubclass(test_class, TestCase):
            return False
        return _uses_default_database(getattr(test_class, "databases", None)) and not bool(
            getattr(test_class, "serialized_rollback", False)
        )

    fixture_names = set(getattr(item, "fixturenames", ()))
    marker = item.get_closest_marker("django_db")
    options: dict[str, object] = {}
    if marker is not None:
        options.update(zip(_DJANGO_DB_MARKER_POSITIONAL_OPTIONS, marker.args, strict=False))
        options.update(marker.kwargs)

    transactional = bool(options.get("transaction", False)) or bool(
        options.get("reset_sequences", False)
    )
    transactional = transactional or bool(
        fixture_names & {"transactional_db", "django_db_reset_sequences", "live_server"}
    )
    serialized_rollback = bool(options.get("serialized_rollback", False)) or (
        "django_db_serialized_rollback" in fixture_names
    )
    return (
        transactional
        and not serialized_rollback
        and _uses_default_database(options.get("databases"))
    )


def _order_sqlite_transactional_items(items: list[pytest.Item], *, default_engine: object) -> None:
    """Keep SQLite rollback-emulation tests ahead of ordinary transactional flushes."""
    if default_engine != _SQLITE_ENGINE:
        return
    items.sort(key=_is_nonserialized_transactional_item)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run ordinary default-SQLite transaction tests after serialized rollback tests."""
    _order_sqlite_transactional_items(
        items,
        default_engine=connection.settings_dict.get("ENGINE"),
    )


@dataclass(frozen=True)
class _PendingFlush:
    """Bind one protected SQL flush to its exact generated statements."""

    statements: tuple[str, ...]
    generation: int


def _reject(message: str) -> NoReturn:
    """Fail closed without repairing or exposing database contents."""
    raise RuntimeError(message)


def _assert_test_database_identity(
    operations: BaseDatabaseOperations,
    source_database_name: str,
) -> None:
    """Require a verified isolated default test database before inspection."""
    database = operations.connection
    if database.alias != "default":
        _reject("authority-generation guard received a non-default database connection")
    if database.vendor == "postgresql":
        assert_native_postgres_test_database(database=database)
        return
    if database.vendor != "sqlite":
        _reject("authority-generation guard received an unsupported database backend")

    active_name = database.settings_dict.get("NAME")
    if not isinstance(active_name, str) or not active_name:
        _reject("SQLite test database name is missing")
    if active_name != database.creation._get_test_db_name():
        _reject("active SQLite database is not Django's test database")

    in_memory = active_name == ":memory:" or (
        active_name.startswith("file:memorydb_") and "mode=memory" in active_name
    )
    if in_memory:
        return

    test_settings = database.settings_dict.get("TEST")
    if not isinstance(test_settings, dict):
        _reject("SQLite TEST settings are missing")
    configured_name = test_settings.get("NAME")
    if not isinstance(configured_name, str) or not configured_name:
        _reject("SQLite TEST.NAME is missing")

    active_path = Path(active_name).resolve()
    configured_path = Path(configured_name).resolve()
    if active_path != configured_path:
        _reject("active SQLite path differs from TEST.NAME")
    if active_path == Path(source_database_name).resolve():
        _reject("active SQLite path is the source database")

    temp_root = Path(tempfile.gettempdir())
    expected_parent = (temp_root / "agomtradepro-test-databases").resolve()
    if active_path.parent != expected_parent:
        _reject("active SQLite path is outside the isolated test directory")
    if active_path.name != f"test_db_{os.getpid()}.sqlite3":
        _reject("active SQLite filename is not bound to this process")


def _read_generation(operations: BaseDatabaseOperations) -> int:
    """Read exactly one valid seeded singleton; never create or repair it."""
    with operations.connection.cursor() as cursor:
        cursor.execute("SELECT singleton, generation FROM account_authority_generation")
        rows: list[tuple[object, ...]] = list(cursor.fetchall())

    if len(rows) != 1:
        _reject("authority-generation table must contain exactly one row")
    singleton, generation = rows[0]
    if isinstance(singleton, bool) or not isinstance(singleton, int) or singleton != 1:
        _reject("authority-generation singleton key is invalid")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        _reject("authority-generation value is invalid")
    return generation


@contextmanager
def _install_sqlite_flush_guard(
    operations_class: type[BaseDatabaseOperations],
    source_database_name: str,
) -> Iterator[list[tuple[int, int]]]:
    """Install the narrow test seam and restore both Django flush methods."""
    original_sql_flush = operations_class.sql_flush
    original_execute_flush = operations_class.execute_sql_flush
    pending: dict[int, _PendingFlush] = {}
    observations: list[tuple[int, int]] = []
    lock = RLock()

    def guarded_sql_flush(
        operations: BaseDatabaseOperations,
        style: Style,
        tables: list[str],
        *,
        reset_sequences: bool = False,
        allow_cascade: bool = False,
    ) -> list[str]:
        """Exclude only one explicit clock-table request on default SQLite."""
        with lock:
            operation_id = id(operations)
            if operation_id in pending:
                _reject("previous protected sql_flush has no matching execute")

            database = operations.connection
            if database.vendor not in {"sqlite", "postgresql"} or database.alias != "default":
                return original_sql_flush(
                    operations,
                    style,
                    tables,
                    reset_sequences=reset_sequences,
                    allow_cascade=allow_cascade,
                )

            clock_count = tables.count(_CLOCK_TABLE)
            if clock_count == 0:
                return original_sql_flush(
                    operations,
                    style,
                    tables,
                    reset_sequences=reset_sequences,
                    allow_cascade=allow_cascade,
                )
            if clock_count != 1:
                _reject("flush request must contain the authority clock exactly once")

            _assert_test_database_identity(operations, source_database_name)
            generation = _read_generation(operations)
            business_tables = [table for table in tables if table != _CLOCK_TABLE]
            statements = original_sql_flush(
                operations,
                style,
                business_tables,
                reset_sequences=reset_sequences,
                allow_cascade=allow_cascade,
            )
            if any(_CLOCK_TABLE in statement for statement in statements):
                _reject("generated flush SQL still targets the authority clock")
            if statements:
                pending[operation_id] = _PendingFlush(
                    statements=tuple(statements), generation=generation
                )
            return statements

    def guarded_execute_flush(operations: BaseDatabaseOperations, sql_list: list[str]) -> None:
        """Execute the paired business flush and verify the clock is monotonic."""
        with lock:
            pending_flush = pending.pop(id(operations), None)
            if pending_flush is None:
                original_execute_flush(operations, sql_list)
                return
            if tuple(sql_list) != pending_flush.statements:
                _reject("execute_sql_flush does not match its protected sql_flush")

            _assert_test_database_identity(operations, source_database_name)
            before = _read_generation(operations)
            if before < pending_flush.generation:
                _reject("authority generation decreased before flush execution")

            original_execute_flush(operations, sql_list)

            _assert_test_database_identity(operations, source_database_name)
            after = _read_generation(operations)
            if after < before:
                _reject("authority generation decreased during flush execution")
            observations.append((before, after))

    operations_class.sql_flush = guarded_sql_flush
    operations_class.execute_sql_flush = guarded_execute_flush
    try:
        yield observations
    finally:
        operations_class.sql_flush = original_sql_flush
        operations_class.execute_sql_flush = original_execute_flush
        with lock:
            unfinished_flushes = len(pending)
            pending.clear()
        if unfinished_flushes:
            _reject("protected sql_flush was not followed by execute_sql_flush")


@pytest.fixture(scope="session", autouse=True)
def preserve_authority_generation_during_sqlite_flush(
    record_testsuite_property: Callable[[str, object], None],
) -> Iterator[None]:
    """Guard isolated default-SQLite/PostgreSQL flushes that include the clock."""
    if connection.vendor not in {"sqlite", "postgresql"}:
        yield
        return

    with _install_sqlite_flush_guard(type(connection.ops), _SOURCE_DATABASE_NAME) as observations:
        try:
            yield
        finally:
            property_name = (
                "sqlite_authority_generation_flushes"
                if connection.vendor == "sqlite"
                else "postgresql_authority_generation_flushes"
            )
            record_testsuite_property(property_name, json.dumps(observations))
