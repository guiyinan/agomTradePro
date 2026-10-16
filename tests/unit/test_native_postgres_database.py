"""Unit checks for the isolated Native PostgreSQL session fixture helper."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest

import tests.support.isolated_schema as isolated_schema_module
from tests.support import native_postgres_database as native_db
from tests.support.isolated_schema import ModelType


class _Cursor:
    """Minimal cursor returning a configured current_database() result."""

    def __init__(self, database_name: str, blocker: _Blocker) -> None:
        self.database_name = database_name
        self.blocker = blocker
        self.sql: str | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        assert self.blocker.active, "SQL ran while Django's database blocker was active"
        self.sql = sql

    def fetchone(self) -> tuple[str]:
        assert self.sql == "SELECT current_database()"
        return (self.database_name,)


class _Connection:
    """Tiny PostgreSQL connection stand-in for setup lifecycle tests."""

    alias = "default"
    vendor = "postgresql"

    def __init__(self, *, name: str, test_name: object, actual_name: str) -> None:
        self.blocker = _Blocker()
        self.settings_dict: dict[str, object] = {
            "NAME": name,
            "TEST": {"NAME": test_name, "MIGRATE": True},
        }
        self.cursor_value = _Cursor(actual_name, self.blocker)

    @contextmanager
    def cursor(self) -> Iterator[_Cursor]:
        yield self.cursor_value


class _Blocker:
    """Provide the public unblock context used by pytest-django."""

    def __init__(self) -> None:
        self.active = False

    @contextmanager
    def unblock(self):
        assert not self.active
        self.active = True
        try:
            yield
        finally:
            self.active = False


@pytest.fixture(autouse=True)
def _reset_shared_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep module-level shared fixture coordination isolated per unit test."""

    monkeypatch.setattr(native_db, "_ACTIVE_SETUP", None)


def _open_session(
    connection: _Connection,
    *,
    reuse_db: bool = False,
    create_db: bool = False,
    use_migrations: bool = True,
):
    """Enter the helper with the small fake runtime used by this module."""

    return native_db.native_postgres_database_session(
        database=cast(native_db.DatabaseConnection, connection),
        blocker=cast(native_db.DjangoDbBlocker, connection.blocker),
        source_database_name="ash_quality_native",
        use_migrations=use_migrations,
        reuse_db=reuse_db,
        create_db=create_db,
        verbosity=0,
    )


def test_setup_uses_only_default_and_restores_public_migrate_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup is alias-scoped, honors no-migrations, and restores TEST.MIGRATE."""

    connection = _Connection(
        name="ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="test_ash_quality_native",
    )
    setup_calls: list[dict[str, object]] = []
    teardown_calls: list[object] = []

    def setup_databases(**kwargs: object) -> list[tuple[object, str, bool]]:
        setup_calls.append(kwargs)
        assert connection.settings_dict["TEST"] == {
            "NAME": "test_ash_quality_native",
            "MIGRATE": False,
        }
        connection.settings_dict["NAME"] = "test_ash_quality_native"
        return [(object(), "test_ash_quality_native", True)]

    monkeypatch.setattr(native_db, "setup_databases", setup_databases)
    monkeypatch.setattr(
        native_db, "teardown_databases", lambda db_cfg, **_kwargs: teardown_calls.append(db_cfg)
    )

    with _open_session(connection, use_migrations=False) as expected_name:
        assert expected_name == "test_ash_quality_native"
        with connection.blocker.unblock():
            native_db.assert_native_postgres_test_database(
                expected_name=expected_name,
                database=cast(native_db.DatabaseConnection, connection),
            )

    assert setup_calls == [
        {
            "verbosity": 0,
            "interactive": False,
            "aliases": {"default"},
            "serialized_aliases": set(),
            "keepdb": False,
        }
    ]
    assert connection.settings_dict["TEST"] == {"NAME": "test_ash_quality_native", "MIGRATE": True}
    assert len(teardown_calls) == 1


@pytest.mark.parametrize("test_name", [None, "", "ash_quality_native"])
def test_setup_rejects_missing_or_source_database_test_name_before_setup(
    monkeypatch: pytest.MonkeyPatch,
    test_name: object,
) -> None:
    """An implicit or source-identical TEST.NAME is rejected before setup."""

    connection = _Connection(
        name="ash_quality_native", test_name=test_name, actual_name="ash_quality_native"
    )
    setup_calls: list[object] = []
    monkeypatch.setattr(native_db, "setup_databases", lambda **_kwargs: setup_calls.append(True))

    with pytest.raises(native_db.NativeTestDatabaseConfigurationError):
        with _open_session(connection):
            pytest.fail("invalid test database configuration must not yield")

    assert setup_calls == []


def test_existing_test_connection_is_sql_verified_and_never_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-active test connection is reused without another setup call."""

    connection = _Connection(
        name="test_ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="test_ash_quality_native",
    )
    setup_calls: list[object] = []
    teardown_calls: list[object] = []
    monkeypatch.setattr(native_db, "setup_databases", lambda **_kwargs: setup_calls.append(True))
    monkeypatch.setattr(
        native_db, "teardown_databases", lambda *_args, **_kwargs: teardown_calls.append(True)
    )

    with _open_session(connection):
        with connection.blocker.unblock():
            assert_native = native_db.assert_native_postgres_test_database(
                expected_name="test_ash_quality_native",
                database=cast(native_db.DatabaseConnection, connection),
            )
        assert assert_native == "test_ash_quality_native"

    assert setup_calls == []
    assert teardown_calls == []


def test_create_db_overrides_reuse_for_setup_but_keeps_database_after_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--create-db` recreates the test DB while reuse mode retains it at teardown."""

    connection = _Connection(
        name="ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="test_ash_quality_native",
    )
    setup_calls: list[dict[str, object]] = []
    teardown_calls: list[object] = []

    def setup_databases(**kwargs: object) -> list[tuple[object, str, bool]]:
        setup_calls.append(kwargs)
        connection.settings_dict["NAME"] = "test_ash_quality_native"
        return [(object(), "test_ash_quality_native", True)]

    monkeypatch.setattr(native_db, "setup_databases", setup_databases)
    monkeypatch.setattr(
        native_db, "teardown_databases", lambda *_args, **_kwargs: teardown_calls.append(True)
    )

    with _open_session(connection, reuse_db=True, create_db=True):
        pass

    assert setup_calls[0]["keepdb"] is False
    assert teardown_calls == []


def test_setup_failure_restores_migrate_setting_and_does_not_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup error restores the public Django TEST.MIGRATE setting."""

    connection = _Connection(
        name="ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="test_ash_quality_native",
    )
    monkeypatch.setattr(
        native_db,
        "setup_databases",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("setup failed")),
    )
    teardown_calls: list[object] = []
    monkeypatch.setattr(
        native_db, "teardown_databases", lambda *_args, **_kwargs: teardown_calls.append(True)
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        with _open_session(connection, use_migrations=False):
            pass

    assert connection.settings_dict["TEST"] == {"NAME": "test_ash_quality_native", "MIGRATE": True}
    assert teardown_calls == []


def test_setup_rejects_database_sql_mismatch_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup whose actual PostgreSQL database differs cannot reach test cleanup."""

    connection = _Connection(
        name="ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="ash_quality_native",
    )

    def setup_databases(**_kwargs: object) -> list[tuple[object, str, bool]]:
        connection.settings_dict["NAME"] = "test_ash_quality_native"
        return [(object(), "test_ash_quality_native", True)]

    monkeypatch.setattr(native_db, "setup_databases", setup_databases)

    with pytest.raises(native_db.NativeTestDatabaseMismatchError):
        with _open_session(connection):
            pytest.fail("wrong SQL database must not reach test writes")


def test_reused_setup_is_shared_and_teardown_waits_for_last_fixture_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two module wrappers share one setup and release its lease exactly once."""

    connection = _Connection(
        name="ash_quality_native",
        test_name="test_ash_quality_native",
        actual_name="test_ash_quality_native",
    )
    setup_calls: list[object] = []
    teardown_calls: list[object] = []

    def setup_databases(**_kwargs: object) -> list[tuple[object, str, bool]]:
        setup_calls.append(True)
        connection.settings_dict["NAME"] = "test_ash_quality_native"
        return [(object(), "test_ash_quality_native", True)]

    monkeypatch.setattr(native_db, "setup_databases", setup_databases)
    monkeypatch.setattr(
        native_db, "teardown_databases", lambda *_args, **_kwargs: teardown_calls.append(True)
    )

    with _open_session(connection):
        with _open_session(connection):
            assert len(setup_calls) == 1
            assert teardown_calls == []
        assert teardown_calls == []

    assert len(setup_calls) == 1
    assert teardown_calls == [True]


def test_schema_cleanup_guard_failure_prevents_clearing_and_dropping_owned_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target-database drift guard runs before isolated-schema cleanup starts."""

    class _Meta:
        db_table = "component_owned_table"

    class _Model:
        _meta = _Meta()

    class _Introspection:
        def table_names(self) -> list[str]:
            return []

    class _SchemaEditor:
        def __init__(self) -> None:
            self.created: list[type[object]] = []
            self.deleted: list[type[object]] = []

        def __enter__(self) -> _SchemaEditor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def create_model(self, model: type[object]) -> None:
            self.created.append(model)

        def delete_model(self, model: type[object]) -> None:
            self.deleted.append(model)

    class _SchemaConnection:
        def __init__(self) -> None:
            self.introspection = _Introspection()
            self.editor = _SchemaEditor()

        def schema_editor(self) -> _SchemaEditor:
            return self.editor

    schema_connection = _SchemaConnection()
    clear_calls: list[tuple[type[object], ...]] = []
    monkeypatch.setattr(isolated_schema_module, "connection", schema_connection)
    monkeypatch.setattr(
        isolated_schema_module,
        "_clear_rows",
        lambda model_types, _existing_tables: clear_calls.append(model_types),
    )

    def reject_cleanup() -> None:
        raise RuntimeError("wrong target database")

    with pytest.raises(RuntimeError, match="wrong target database"):
        with isolated_schema_module.isolated_schema(
            (cast(ModelType, _Model),), before_cleanup=reject_cleanup
        ):
            pass

    assert clear_calls == [(cast(ModelType, _Model),)]
    assert schema_connection.editor.created == [cast(type[object], _Model)]
    assert schema_connection.editor.deleted == []
