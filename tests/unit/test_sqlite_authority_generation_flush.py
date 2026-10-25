"""Contract tests for the SQLite authority-generation flush wrapper."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from django.core.management.color import Style, no_style
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.operations import BaseDatabaseOperations

from tests.component.conftest import (
    _COMPONENT_JUNIT_PROPERTIES_KEY,
    _component_junit_sink,
    _component_worker_sqlite_test_path,
    _record_component_testsuite_property,
    _replay_component_testsuite_properties,
    django_db_modify_db_settings_xdist_suffix,
    pytest_sessionstart,
    pytest_testnodedown,
    record_testsuite_property,
)

from ..support.sqlite_authority_generation_flush import (
    _install_sqlite_flush_guard,
    _order_sqlite_transactional_items,
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


class _FakeCollectionMarker:
    """Expose only the positional and keyword fields read from a pytest marker."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs


class _FakeCollectionItem:
    """Model the item fields used by the SQLite ordering hook."""

    def __init__(
        self,
        name: str,
        *,
        marker: _FakeCollectionMarker | None = None,
        fixturenames: tuple[str, ...] = (),
        cls: type[object] | None = None,
    ) -> None:
        self.name = name
        self.marker = marker
        self.fixturenames = fixturenames
        self.cls = cls

    def get_closest_marker(self, name: str) -> _FakeCollectionMarker | None:
        return self.marker if name == "django_db" else None


def test_sqlite_transaction_order_is_stable_and_only_applies_to_sqlite() -> None:
    """Sort flush-capable default-SQLite cases last without changing test membership."""
    from django.test import TestCase, TransactionTestCase

    class OrdinaryTransactionCase(TransactionTestCase):
        pass

    class SerializedTransactionCase(TransactionTestCase):
        serialized_rollback = True

    class AtomicTestCase(TestCase):
        pass

    items = [
        _FakeCollectionItem("ordinary-marker", marker=_FakeCollectionMarker(transaction=True)),
        _FakeCollectionItem("plain-db-fixture", fixturenames=("db",)),
        _FakeCollectionItem(
            "serialized-positional-marker",
            marker=_FakeCollectionMarker(True, False, None, True),
        ),
        _FakeCollectionItem("live-server-fixture", fixturenames=("live_server",)),
        _FakeCollectionItem(
            "reset-sequences-marker",
            marker=_FakeCollectionMarker(False, True),
        ),
        _FakeCollectionItem(
            "other-database-marker",
            marker=_FakeCollectionMarker(transaction=True, databases=("analytics",)),
        ),
        _FakeCollectionItem(
            "serialized-fixtures",
            fixturenames=("transactional_db", "django_db_serialized_rollback"),
        ),
        _FakeCollectionItem("ordinary-unittest", cls=OrdinaryTransactionCase),
        _FakeCollectionItem("atomic-unittest", cls=AtomicTestCase),
        _FakeCollectionItem("serialized-unittest", cls=SerializedTransactionCase),
        _FakeCollectionItem(
            "default-in-multi-database-marker",
            marker=_FakeCollectionMarker(transaction=True, databases=("analytics", "default")),
        ),
        _FakeCollectionItem(
            "reset-sequences-fixture",
            fixturenames=("django_db_reset_sequences",),
        ),
    ]
    original = list(items)
    pytest_items = cast(list[pytest.Item], items)

    _order_sqlite_transactional_items(
        pytest_items,
        default_engine="django.db.backends.postgresql",
    )
    assert items == original

    _order_sqlite_transactional_items(
        pytest_items,
        default_engine="django.db.backends.sqlite3",
    )
    assert [item.name for item in items] == [
        "plain-db-fixture",
        "serialized-positional-marker",
        "other-database-marker",
        "serialized-fixtures",
        "atomic-unittest",
        "serialized-unittest",
        "ordinary-marker",
        "live-server-fixture",
        "reset-sequences-marker",
        "ordinary-unittest",
        "default-in-multi-database-marker",
        "reset-sequences-fixture",
    ]
    assert len(items) == len(original)


def _component_database_settings(
    temporary_directory: Path,
    *,
    process_id: int = 614,
    worker_id: str = "gw0",
    source_name: str | None = None,
) -> dict[str, object]:
    """Build only the pytest-django settings shape consumed by the path validator."""
    base_path = (
        temporary_directory / "agomtradepro-test-databases" / f"test_db_{process_id}.sqlite3"
    )
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": source_name or str(temporary_directory / "source.sqlite3"),
        "TEST": {"NAME": f"{base_path}_{worker_id}"},
    }


@pytest.mark.parametrize("worker_id", ["master", "gw-1", "gw01", "gw0/../gw1", "gw0_gw0"])
def test_component_sqlite_path_rejects_malformed_or_repeated_worker_suffix(
    tmp_path: Path,
    worker_id: str,
) -> None:
    """Only one canonical xdist worker suffix is accepted."""
    settings = _component_database_settings(tmp_path, worker_id=worker_id)
    with pytest.raises(pytest.UsageError, match="worker ID is malformed"):
        _component_worker_sqlite_test_path(
            settings,
            database_alias="default",
            worker_id=worker_id,
            process_id=614,
            temporary_directory=tmp_path,
        )


def test_component_sqlite_path_restores_only_the_exact_pid_worker_path(
    tmp_path: Path,
) -> None:
    """A valid pytest-django suffix maps back to the current worker's PID path."""
    settings = _component_database_settings(tmp_path)
    expected = tmp_path / "agomtradepro-test-databases" / "test_db_614.sqlite3"
    assert _component_worker_sqlite_test_path(
        settings,
        database_alias="default",
        worker_id="gw0",
        process_id=614,
        temporary_directory=tmp_path,
    ) == str(expected)


@pytest.mark.parametrize(
    ("case", "process_id"),
    [
        ("wrong-pid", 615),
        ("wrong-parent", 614),
        ("source-alias", 614),
        ("path-traversal", 614),
        ("repeated-suffix", 614),
    ],
)
def test_component_sqlite_path_rejects_plausible_suffix_with_wrong_identity(
    tmp_path: Path,
    case: str,
    process_id: int,
) -> None:
    """A suffix alone cannot bless a wrong parent, PID, source, or traversal path."""
    settings = _component_database_settings(tmp_path)
    base_path = tmp_path / "agomtradepro-test-databases" / "test_db_614.sqlite3"
    if case == "wrong-parent":
        settings["TEST"] = {"NAME": str(tmp_path / "other" / "test_db_614.sqlite3_gw0")}
    elif case == "source-alias":
        settings["NAME"] = str(base_path)
    elif case == "path-traversal":
        settings["TEST"] = {
            "NAME": str(
                tmp_path
                / "agomtradepro-test-databases"
                / ".."
                / "outside"
                / "test_db_614.sqlite3_gw0"
            )
        }
    elif case == "repeated-suffix":
        settings["TEST"] = {"NAME": f"{base_path}_gw0_gw0"}

    with pytest.raises(pytest.UsageError):
        _component_worker_sqlite_test_path(
            settings,
            database_alias="default",
            worker_id="gw0",
            process_id=process_id,
            temporary_directory=tmp_path,
        )


def _component_sqlite_worker_fixture_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    worker_id: str = "gw0",
) -> tuple[dict[str, object], SimpleNamespace, pytest.FixtureRequest, int, Path]:
    """Build one config and settings mapping without creating a database."""
    import django.conf

    temporary_directory = Path(tempfile.gettempdir())
    process_id = os.getpid()
    database_settings = _component_database_settings(
        temporary_directory,
        process_id=process_id,
        worker_id=worker_id,
        source_name=str(tmp_path / "source.sqlite3"),
    )
    monkeypatch.setattr(
        django.conf,
        "settings",
        SimpleNamespace(DATABASES={"default": database_settings}),
    )
    config = SimpleNamespace(workerinput={"workerid": worker_id}, stash={})
    request = cast(pytest.FixtureRequest, SimpleNamespace(config=config))
    return database_settings, config, request, process_id, temporary_directory


def test_component_database_fixture_is_idempotent_for_same_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A duplicate fixture layer may reuse only this config's validated path."""
    database_settings, _, request, process_id, temporary_directory = (
        _component_sqlite_worker_fixture_context(monkeypatch, tmp_path)
    )
    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    expected_path = (
        temporary_directory / "agomtradepro-test-databases" / (f"test_db_{process_id}.sqlite3")
    )

    fixture_body(None, request)
    assert database_settings["TEST"] == {"NAME": str(expected_path)}
    fixture_body(None, request)
    assert database_settings["TEST"] == {"NAME": str(expected_path)}


def test_component_database_fixture_accepts_token_bound_post_setup_database_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Django's verified test NAME swap remains bound to the original worker token."""
    import django.db

    from tests.support import xdist_worker_contracts

    database_settings, config, request, _, _ = _component_sqlite_worker_fixture_context(
        monkeypatch, tmp_path
    )
    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    fixture_body(None, request)
    binding = config.stash[xdist_worker_contracts._SQLITE_WORKER_PATH_BINDING_KEY]
    raw_restored_test_path = database_settings["TEST"]["NAME"]
    assert isinstance(raw_restored_test_path, str)
    database_settings["NAME"] = binding.restored_test_path
    connection = SimpleNamespace(
        alias="default",
        settings_dict=database_settings,
        creation=SimpleNamespace(_get_test_db_name=lambda: binding.restored_test_path),
    )
    monkeypatch.setattr(django.db, "connections", {"default": connection})

    fixture_body(None, request)

    assert database_settings["NAME"] == binding.restored_test_path
    assert database_settings["TEST"] == {"NAME": raw_restored_test_path}
    assert (
        xdist_worker_contracts.normalized_path(raw_restored_test_path) == binding.restored_test_path
    )
    assert config.stash[xdist_worker_contracts._SQLITE_WORKER_PATH_BINDING_KEY] == binding


@pytest.mark.parametrize(
    "mutation", ["wrong-alias", "different-settings-object", "wrong-test-db-name"]
)
def test_component_database_fixture_rejects_unverified_post_setup_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    """The same test path is insufficient without the bound default connection."""
    import django.db

    from tests.support import xdist_worker_contracts

    database_settings, config, request, _, _ = _component_sqlite_worker_fixture_context(
        monkeypatch, tmp_path
    )
    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    fixture_body(None, request)
    binding = config.stash[xdist_worker_contracts._SQLITE_WORKER_PATH_BINDING_KEY]
    database_settings["NAME"] = binding.restored_test_path
    connection_settings = database_settings
    alias = "default"
    test_database_name = binding.restored_test_path
    if mutation == "wrong-alias":
        alias = "analytics"
    elif mutation == "different-settings-object":
        connection_settings = dict(database_settings)
    elif mutation == "wrong-test-db-name":
        test_database_name = str(tmp_path / "other-test.sqlite3")
    else:
        raise AssertionError(f"unexpected mutation: {mutation}")
    connection = SimpleNamespace(
        alias=alias,
        settings_dict=connection_settings,
        creation=SimpleNamespace(_get_test_db_name=lambda: test_database_name),
    )
    monkeypatch.setattr(django.db, "connections", {"default": connection})

    with pytest.raises(pytest.UsageError):
        fixture_body(None, request)


@pytest.mark.parametrize("mutation", ["engine", "worker-input"])
def test_component_database_fixture_rejects_identity_loss_after_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    """An existing token prevents SQLite-engine and worker-input bypasses."""
    database_settings, config, request, _, _ = _component_sqlite_worker_fixture_context(
        monkeypatch, tmp_path
    )
    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    fixture_body(None, request)
    if mutation == "engine":
        database_settings["ENGINE"] = "django.db.backends.postgresql"
    elif mutation == "worker-input":
        config.workerinput = None
    else:
        raise AssertionError(f"unexpected mutation: {mutation}")

    with pytest.raises(pytest.UsageError):
        fixture_body(None, request)


@pytest.mark.parametrize("mutation", ["worker-id", "pid", "source", "path", "tempdir"])
def test_component_database_fixture_rejects_identity_or_path_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    """A token cannot authorize a changed worker, source, temp root, or test path."""
    database_settings, config, request, process_id, _ = _component_sqlite_worker_fixture_context(
        monkeypatch, tmp_path
    )
    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    fixture_body(None, request)

    if mutation == "worker-id":
        config.workerinput["workerid"] = "gw1"
    elif mutation == "pid":
        monkeypatch.setattr(os, "getpid", lambda: process_id + 1)
    elif mutation == "source":
        database_settings["NAME"] = str(tmp_path / "other-source.sqlite3")
    elif mutation == "path":
        database_settings["TEST"] = {"NAME": str(tmp_path / "forged.sqlite3")}
    elif mutation == "tempdir":
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "other-temp"))
    else:
        raise AssertionError(f"unexpected mutation: {mutation}")

    with pytest.raises(pytest.UsageError):
        fixture_body(None, request)


def test_component_database_fixture_requires_worker_suffix_before_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unsuffixed path cannot establish the once-token without prior validation."""
    database_settings, _, request, process_id, temporary_directory = (
        _component_sqlite_worker_fixture_context(monkeypatch, tmp_path)
    )
    base_path = (
        temporary_directory / "agomtradepro-test-databases" / (f"test_db_{process_id}.sqlite3")
    )
    database_settings["TEST"] = {"NAME": str(base_path)}

    with pytest.raises(pytest.UsageError, match="exact PID and worker suffix"):
        django_db_modify_db_settings_xdist_suffix.__wrapped__(None, request)


def test_component_database_fixture_passes_through_serial_and_postgres_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The component override leaves serial and non-SQLite database settings untouched."""
    import django.conf

    fixture_body = django_db_modify_db_settings_xdist_suffix.__wrapped__
    serial_request = cast(
        pytest.FixtureRequest,
        SimpleNamespace(config=SimpleNamespace(workerinput=None, stash=pytest.Stash())),
    )
    assert fixture_body(None, serial_request) is None

    postgres_settings = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "source_database",
        "TEST": {"NAME": "test_source_database_gw0"},
    }
    monkeypatch.setattr(
        django.conf,
        "settings",
        SimpleNamespace(DATABASES={"default": postgres_settings}),
    )
    worker_request = cast(
        pytest.FixtureRequest,
        SimpleNamespace(
            config=SimpleNamespace(workerinput={"workerid": "gw0"}, stash=pytest.Stash())
        ),
    )
    assert fixture_body(None, worker_request) is None
    assert postgres_settings == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "source_database",
        "TEST": {"NAME": "test_source_database_gw0"},
    }


def test_component_sqlite_path_rejects_non_default_alias(tmp_path: Path) -> None:
    """The path override cannot be reused to broaden another database alias."""
    settings = _component_database_settings(tmp_path)
    with pytest.raises(pytest.UsageError, match="default alias"):
        _component_worker_sqlite_test_path(
            settings,
            database_alias="analytics",
            worker_id="gw0",
            process_id=614,
            temporary_directory=tmp_path,
        )


class _FakeComponentConfig:
    """Expose only the xdist and JUnit configuration used by the property bridge."""

    def __init__(
        self,
        *,
        workerinput: dict[str, object] | None,
        workeroutput: dict[str, object] | None,
        xmlpath: str | None,
        plugins: list[object] | None = None,
    ) -> None:
        if workerinput is not None:
            self.workerinput = workerinput
        if workeroutput is not None:
            self.workeroutput = workeroutput
        self.xmlpath = xmlpath
        self.pluginmanager = _FakePluginManager(plugins or [])

    def getoption(self, name: str, default: object = None) -> object:
        assert name == "xmlpath"
        return self.xmlpath if self.xmlpath is not None else default


class _FakePluginManager:
    """Return only the explicit plugins supplied by a contract test."""

    def __init__(self, plugins: list[object]) -> None:
        self._plugins = set(plugins)

    def get_plugins(self) -> set[object]:
        return self._plugins


class _FakeComponentRequest:
    """Provide only the pytest request attribute read by the property bridge."""

    def __init__(self, config: _FakeComponentConfig) -> None:
        self.config = config


def test_component_junit_bridge_preserves_duplicate_properties_and_string_values(
    tmp_path: Path,
) -> None:
    """Workers retain repeated suite properties for pytest's actual LogXML sink."""
    from _pytest.junitxml import LogXML

    xml_sink = LogXML.__new__(LogXML)
    xml_sink.global_properties = []
    config = _FakeComponentConfig(
        workerinput={"workerid": "gw0"},
        workeroutput={},
        xmlpath=str(tmp_path / "component.xml"),
        plugins=[xml_sink],
    )
    request = cast(pytest.FixtureRequest, _FakeComponentRequest(config))
    delegated: list[tuple[str, object]] = []

    def original_recorder(name: str, value: object) -> None:
        delegated.append((name, value))

    pytest_sessionstart(cast(pytest.Session, SimpleNamespace(config=config)))
    worker_recorder = _record_component_testsuite_property(request, original_recorder)
    worker_recorder("authority_generation", 8)
    worker_recorder("authority_generation", 9)

    assert delegated == [("authority_generation", 8), ("authority_generation", 9)]
    assert config.workeroutput == {
        _COMPONENT_JUNIT_PROPERTIES_KEY: [
            ("authority_generation", "8"),
            ("authority_generation", "9"),
        ]
    }

    sink = _component_junit_sink(cast(pytest.Config, config))
    assert sink is xml_sink
    _replay_component_testsuite_properties(config.workeroutput, sink)
    assert xml_sink.global_properties == [
        ("authority_generation", "8"),
        ("authority_generation", "9"),
    ]


def test_component_junit_worker_sessionstart_initializes_empty_property_buffer(
    tmp_path: Path,
) -> None:
    """A healthy XML worker always sends an explicit property list, even when idle."""
    config = _FakeComponentConfig(
        workerinput={"workerid": "gw0"},
        workeroutput={},
        xmlpath=str(tmp_path / "component.xml"),
    )
    pytest_sessionstart(cast(pytest.Session, SimpleNamespace(config=config)))

    assert config.workeroutput == {_COMPONENT_JUNIT_PROPERTIES_KEY: []}


def test_component_junit_bridge_rejects_missing_or_duplicate_master_sink(
    tmp_path: Path,
) -> None:
    """Requested JUnit output requires exactly one built-in writer."""
    from _pytest.junitxml import LogXML

    empty_config = _FakeComponentConfig(
        workerinput=None,
        workeroutput=None,
        xmlpath=str(tmp_path / "component.xml"),
    )
    with pytest.raises(pytest.UsageError, match="single LogXML sink"):
        _component_junit_sink(cast(pytest.Config, empty_config))

    first_sink = LogXML.__new__(LogXML)
    second_sink = LogXML.__new__(LogXML)
    duplicate_config = _FakeComponentConfig(
        workerinput=None,
        workeroutput=None,
        xmlpath=str(tmp_path / "component.xml"),
        plugins=[first_sink, second_sink],
    )
    with pytest.raises(pytest.UsageError, match="single LogXML sink"):
        _component_junit_sink(cast(pytest.Config, duplicate_config))


def test_component_junit_bridge_rejects_missing_and_malformed_worker_rows(
    tmp_path: Path,
) -> None:
    """An enabled sink rejects omitted buffers and malformed serialized rows."""
    from _pytest.junitxml import LogXML

    sink = LogXML.__new__(LogXML)
    sink.global_properties = []
    with pytest.raises(pytest.UsageError, match="omitted its initialized"):
        _replay_component_testsuite_properties({}, sink)
    with pytest.raises(pytest.UsageError, match="entry is malformed"):
        _replay_component_testsuite_properties(
            {_COMPONENT_JUNIT_PROPERTIES_KEY: [("authority_generation", 8)]},
            sink,
        )

    _replay_component_testsuite_properties({_COMPONENT_JUNIT_PROPERTIES_KEY: []}, sink)
    assert sink.global_properties == []


def test_component_junit_bridge_fails_closed_without_requested_sink() -> None:
    """A captured worker property cannot disappear when JUnit output was requested."""
    with pytest.raises(pytest.UsageError, match="without a master sink"):
        _replay_component_testsuite_properties(
            {_COMPONENT_JUNIT_PROPERTIES_KEY: [("authority_generation", "8")]},
            None,
        )


def test_component_junit_bridge_keeps_no_xml_recorder_unchanged() -> None:
    """Serial and no-JUnit execution returns pytest's original recorder unchanged."""
    config = _FakeComponentConfig(
        workerinput=None,
        workeroutput=None,
        xmlpath=None,
    )
    request = cast(pytest.FixtureRequest, _FakeComponentRequest(config))

    def original_recorder(name: str, value: object) -> None:
        del name, value

    assert _record_component_testsuite_property(request, original_recorder) is original_recorder
    _replay_component_testsuite_properties({}, None)


def test_api_migrations_plugin_reexports_the_shared_worker_contract() -> None:
    """Both test areas register the same hooks, fixture and JUnit sink state."""
    from tests.support import api_migrations_xdist, xdist_worker_contracts

    assert api_migrations_xdist.pytest_sessionstart is pytest_sessionstart
    assert api_migrations_xdist.pytest_sessionstart.__globals__ is xdist_worker_contracts.__dict__
    assert api_migrations_xdist.pytest_testnodedown is pytest_testnodedown
    assert api_migrations_xdist.django_db_modify_db_settings_xdist_suffix is (
        django_db_modify_db_settings_xdist_suffix
    )
    assert api_migrations_xdist.record_testsuite_property is record_testsuite_property
