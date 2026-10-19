"""Contract tests for the SQLite authority-generation flush wrapper."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import cast

import pytest
from django.core.management.color import Style, no_style
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.operations import BaseDatabaseOperations

from ..support.sqlite_authority_generation_flush import (
    _install_sqlite_flush_guard,
)

_CLOCK_TABLE = "account_authority_generation"
_BUSINESS_TABLE = "sample_business_rows"


class _FakeCreation:
    """Expose Django's test-database name lookup for the isolated seam."""

    def __init__(self, name: str) -> None:
        self.name = name

    def _get_test_db_name(self) -> str:
        return self.name


class _FakeCursor:
    """Return only the explicitly configured in-memory clock rows."""

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        return False

    def execute(self, sql: str) -> None:
        if sql != f"SELECT singleton, generation FROM {_CLOCK_TABLE}":
            raise AssertionError("unexpected query in fake cursor")
        self.connection.query_count += 1

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.connection.clock_rows)


class _FakeConnection:
    """Model only database identity and rows used by the wrapper contract."""

    def __init__(
        self,
        *,
        name: str,
        test_name: str,
        vendor: str = "sqlite",
        alias: str = "default",
        clock_rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.vendor = vendor
        self.alias = alias
        self.settings_dict: dict[str, object] = {
            "NAME": name,
            "TEST": {"NAME": test_name},
        }
        self.creation = _FakeCreation(test_name)
        self.clock_rows = clock_rows if clock_rows is not None else [(1, 8)]
        self.business_rows = 2
        self.query_count = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


class _FakeOperations(BaseDatabaseOperations):
    """Implement a tiny in-memory flush target without opening a database."""

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = cast(BaseDatabaseWrapper, connection)
        self.fake_connection = connection
        self.sql_calls: list[list[str]] = []
        self.sql_options: list[tuple[bool, bool]] = []
        self.execute_calls: list[list[str]] = []
        self.fail_execution = False
        self.generation_after_flush: int | None = None

    def sql_flush(
        self,
        style: Style,
        tables: list[str],
        *,
        reset_sequences: bool = False,
        allow_cascade: bool = False,
    ) -> list[str]:
        self.sql_calls.append(list(tables))
        self.sql_options.append((reset_sequences, allow_cascade))
        return [f"DELETE FROM {table}" for table in tables]

    def execute_sql_flush(self, sql_list: list[str]) -> None:
        self.execute_calls.append(list(sql_list))
        if self.fail_execution:
            raise RuntimeError("synthetic flush failure")
        for statement in sql_list:
            if statement == f"DELETE FROM {_BUSINESS_TABLE}":
                self.fake_connection.business_rows = 0
            elif statement == f"DELETE FROM {_CLOCK_TABLE}":
                self.fake_connection.clock_rows.clear()
        if self.generation_after_flush is not None:
            self.fake_connection.clock_rows = [(1, self.generation_after_flush)]


def _make_operations(
    case_root: Path,
    *,
    clock_rows: list[tuple[object, ...]] | None = None,
    vendor: str = "sqlite",
    alias: str = "default",
) -> tuple[_FakeOperations, str]:
    """Build a fake operations object with the exact isolated path shape."""
    test_path = (
        Path(tempfile.gettempdir())
        / "agomtradepro-test-databases"
        / f"test_db_{os.getpid()}.sqlite3"
    )
    source_path = case_root / "source.sqlite3"
    database = _FakeConnection(
        name=str(test_path),
        test_name=str(test_path),
        vendor=vendor,
        alias=alias,
        clock_rows=clock_rows,
    )
    return _FakeOperations(database), str(source_path)


def test_no_clock_other_alias_and_other_backend_are_passthrough(
    tmp_path: Path,
) -> None:
    """Only a default SQLite request naming the clock enters the guard."""
    cases = (
        ("sqlite", "default", [_BUSINESS_TABLE]),
        ("sqlite", "analytics", [_CLOCK_TABLE, _BUSINESS_TABLE]),
        ("postgresql", "default", [_CLOCK_TABLE, _BUSINESS_TABLE]),
    )
    for vendor, alias, tables in cases:
        operations, source = _make_operations(
            tmp_path / f"{vendor}-{alias}", vendor=vendor, alias=alias
        )
        with _install_sqlite_flush_guard(type(operations), source):
            statements = operations.sql_flush(no_style(), tables)
            operations.execute_sql_flush(statements)
        assert operations.sql_calls == [tables]
        assert operations.execute_calls == [statements]
        assert operations.fake_connection.query_count == 0


def test_missing_clock_row_is_not_inspected_when_partial_flush_omits_table(
    tmp_path: Path,
) -> None:
    """Partial flushes without the clock remain the original backend operation."""
    operations, source = _make_operations(tmp_path, clock_rows=[])
    with _install_sqlite_flush_guard(type(operations), source):
        statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE])
        operations.execute_sql_flush(statements)
    assert operations.sql_calls == [[_BUSINESS_TABLE]]
    assert operations.fake_connection.clock_rows == []
    assert operations.fake_connection.query_count == 0


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(1, 8), (1, 9)],
        [(True, 8)],
        [(1, True)],
        [(1, -1)],
    ],
)
def test_invalid_or_missing_clock_fails_before_sql_generation(
    tmp_path: Path,
    rows: list[tuple[object, ...]],
) -> None:
    """Missing, duplicated, boolean, and negative singleton state is rejected."""
    operations, source = _make_operations(tmp_path, clock_rows=rows)
    with _install_sqlite_flush_guard(type(operations), source):
        with pytest.raises(RuntimeError):
            operations.sql_flush(no_style(), [_CLOCK_TABLE, _BUSINESS_TABLE])
    assert operations.sql_calls == []
    assert operations.fake_connection.clock_rows == rows
    assert operations.fake_connection.query_count == 1


@pytest.mark.parametrize("invalid_identity", ["source", "outside", "wrong-name"])
def test_invalid_database_identity_fails_before_sql_generation(
    tmp_path: Path,
    invalid_identity: str,
) -> None:
    """A targeted flush cannot proceed under a source or misbound test path."""
    operations, source = _make_operations(tmp_path)
    database = operations.fake_connection
    if invalid_identity == "source":
        source = str(Path(database.settings_dict["NAME"]))
    elif invalid_identity == "outside":
        outside = tmp_path / "outside.sqlite3"
        database.settings_dict["NAME"] = str(outside)
        database.creation.name = str(outside)
        database.settings_dict["TEST"] = {"NAME": str(outside)}
    else:
        database.settings_dict["TEST"] = {"NAME": str(tmp_path / "other.sqlite3")}

    with _install_sqlite_flush_guard(type(operations), source):
        with pytest.raises(RuntimeError):
            operations.sql_flush(no_style(), [_CLOCK_TABLE, _BUSINESS_TABLE])
    assert operations.sql_calls == []
    assert operations.fake_connection.query_count == 0


def test_duplicate_clock_table_request_fails_before_sql_generation(
    tmp_path: Path,
) -> None:
    """A duplicate clock request is rejected rather than partially filtered."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source):
        with pytest.raises(RuntimeError):
            operations.sql_flush(no_style(), [_CLOCK_TABLE, _CLOCK_TABLE])
    assert operations.sql_calls == []
    assert operations.fake_connection.query_count == 0


def test_business_rows_are_flushed_and_clock_generation_is_preserved(
    tmp_path: Path,
) -> None:
    """The guard removes only the clock table and validates monotonic state."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source) as observations:
        statements = operations.sql_flush(
            no_style(),
            [_BUSINESS_TABLE, _CLOCK_TABLE],
            reset_sequences=True,
            allow_cascade=True,
        )
        assert operations.sql_calls == [[_BUSINESS_TABLE]]
        assert statements == [f"DELETE FROM {_BUSINESS_TABLE}"]
        operations.execute_sql_flush(statements)

    assert operations.fake_connection.business_rows == 0
    assert operations.fake_connection.clock_rows == [(1, 8)]
    assert operations.sql_options == [(True, True)]
    assert operations.fake_connection.query_count == 3
    assert observations == [(8, 8)]


def test_empty_flush_has_no_stale_pending_state(tmp_path: Path) -> None:
    """Clock-only requests do not pair an empty SQL list with a later execute."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source) as observations:
        statements = operations.sql_flush(no_style(), [_CLOCK_TABLE])
        assert statements == []
        operations.execute_sql_flush(statements)
        next_statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE])
        operations.execute_sql_flush(next_statements)

    assert operations.execute_calls == [[], [f"DELETE FROM {_BUSINESS_TABLE}"]]
    assert operations.fake_connection.query_count == 1
    assert observations == []


def test_flush_exception_clears_pending_state(tmp_path: Path) -> None:
    """An underlying execution error cannot poison the next flush operation."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source):
        statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        operations.fail_execution = True
        with pytest.raises(RuntimeError, match="synthetic flush failure"):
            operations.execute_sql_flush(statements)

        operations.fail_execution = False
        operations.execute_sql_flush([f"DELETE FROM {_BUSINESS_TABLE}"])
        next_statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        operations.execute_sql_flush(next_statements)
    assert operations.fake_connection.clock_rows == [(1, 8)]


def test_duplicate_pending_flush_is_rejected_and_original_pair_remains_valid(
    tmp_path: Path,
) -> None:
    """A second sql_flush cannot overwrite the first pending execute pair."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source):
        statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        with pytest.raises(RuntimeError, match="no matching execute"):
            operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        operations.execute_sql_flush(statements)
    assert operations.fake_connection.business_rows == 0
    assert operations.fake_connection.clock_rows == [(1, 8)]


def test_generation_decrease_fails_after_flush_and_clears_pending(
    tmp_path: Path,
) -> None:
    """A post-flush generation regression is reported and cannot poison reuse."""
    operations, source = _make_operations(tmp_path)
    with _install_sqlite_flush_guard(type(operations), source):
        statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        operations.generation_after_flush = 7
        with pytest.raises(RuntimeError, match="decreased during flush"):
            operations.execute_sql_flush(statements)

        operations.generation_after_flush = None
        operations.execute_sql_flush([f"DELETE FROM {_BUSINESS_TABLE}"])
    assert operations.fake_connection.clock_rows == [(1, 7)]


def test_existing_module_filter_nests_without_double_guard(
    tmp_path: Path,
) -> None:
    """The legacy module wrapper filters first; the session wrapper passes through."""
    operations, source = _make_operations(tmp_path)
    operations_class = type(operations)
    module_pending: set[int] = set()

    with _install_sqlite_flush_guard(operations_class, source) as observations:
        session_sql_flush = operations_class.sql_flush
        session_execute_flush = operations_class.execute_sql_flush

        def module_sql_flush(
            wrapped: BaseDatabaseOperations,
            style: Style,
            tables: list[str],
            *,
            reset_sequences: bool = False,
            allow_cascade: bool = False,
        ) -> list[str]:
            if tables.count(_CLOCK_TABLE) == 1:
                module_pending.add(id(wrapped))
                filtered = [table for table in tables if table != _CLOCK_TABLE]
                return session_sql_flush(
                    wrapped,
                    style,
                    filtered,
                    reset_sequences=reset_sequences,
                    allow_cascade=allow_cascade,
                )
            return session_sql_flush(
                wrapped,
                style,
                tables,
                reset_sequences=reset_sequences,
                allow_cascade=allow_cascade,
            )

        def module_execute_flush(wrapped: BaseDatabaseOperations, sql_list: list[str]) -> None:
            if id(wrapped) in module_pending:
                module_pending.remove(id(wrapped))
            session_execute_flush(wrapped, sql_list)

        operations_class.sql_flush = module_sql_flush
        operations_class.execute_sql_flush = module_execute_flush
        statements = operations.sql_flush(no_style(), [_BUSINESS_TABLE, _CLOCK_TABLE])
        operations.execute_sql_flush(statements)

    assert not module_pending
    assert operations.fake_connection.business_rows == 0
    assert operations.fake_connection.clock_rows == [(1, 8)]
    assert operations.fake_connection.query_count == 0
    assert observations == []


def test_nested_legacy_clock_only_noop_remains_owned_by_outer_fixture(
    tmp_path: Path,
) -> None:
    """The session wrapper does not arm or clear a legacy wrapper's own no-op mark."""
    operations, source = _make_operations(tmp_path)
    operations_class = type(operations)
    module_pending: set[int] = set()

    with _install_sqlite_flush_guard(operations_class, source) as observations:
        session_sql_flush = operations_class.sql_flush

        def module_sql_flush(
            wrapped: BaseDatabaseOperations,
            style: Style,
            tables: list[str],
            *,
            reset_sequences: bool = False,
            allow_cascade: bool = False,
        ) -> list[str]:
            if tables.count(_CLOCK_TABLE) == 1:
                module_pending.add(id(wrapped))
                filtered = [table for table in tables if table != _CLOCK_TABLE]
                return session_sql_flush(
                    wrapped,
                    style,
                    filtered,
                    reset_sequences=reset_sequences,
                    allow_cascade=allow_cascade,
                )
            return session_sql_flush(
                wrapped,
                style,
                tables,
                reset_sequences=reset_sequences,
                allow_cascade=allow_cascade,
            )

        operations_class.sql_flush = module_sql_flush
        statements = operations.sql_flush(no_style(), [_CLOCK_TABLE])

    assert statements == []
    assert module_pending == {id(operations)}
    assert operations.fake_connection.query_count == 0
    assert observations == []
