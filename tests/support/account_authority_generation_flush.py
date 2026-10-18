"""Preserve the migration-owned authority clock during isolated test cleanup."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.management.color import Style
from django.db import connection
from django.db.backends.base.operations import BaseDatabaseOperations

from tests.support.native_postgres_database import assert_native_postgres_test_database

_SOURCE_DATABASE_NAME = str(connection.settings_dict["NAME"])


@pytest.fixture(scope="module", autouse=True)
def preserve_account_authority_generation(
    record_testsuite_property: Callable[[str, object], None],
) -> Iterator[None]:
    """Flush business rows while retaining the existing authority clock and ACLs."""
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
        assert tables.count("account_authority_generation") == 1
        selected = [table for table in tables if table != "account_authority_generation"]
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
                assert active_path != Path(_SOURCE_DATABASE_NAME).resolve()
                assert (
                    active_path.parent
                    == (Path(tempfile.gettempdir()) / "agomtradepro-test-databases").resolve()
                )
                assert active_path.name == f"test_db_{os.getpid()}.sqlite3"
        with operations.connection.cursor() as cursor:
            cursor.execute("SELECT singleton, generation FROM account_authority_generation")
            rows: list[tuple[Any, ...]] = cursor.fetchall()
        assert len(rows) == 1 and rows[0][0] == 1
        value = rows[0][1]
        assert isinstance(value, int) and not isinstance(value, bool) and value >= 0
        return value

    def guarded_execute_flush(operations: BaseDatabaseOperations, sql_list: list[str]) -> None:
        """Prove normal cleanup preserves the existing monotonically increasing row."""
        if id(operations) not in pending:
            original_execute_flush(operations, sql_list)
            return
        pending.remove(id(operations))
        before = generation(operations)
        original_execute_flush(operations, sql_list)
        after = generation(operations)
        assert after >= before
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
