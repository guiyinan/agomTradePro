"""Session-scoped Native PostgreSQL test database setup for component suites."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import RLock
from types import TracebackType
from typing import Protocol, cast

import pytest
from django.db import connection as django_connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test.utils import setup_databases, teardown_databases
from pytest_django.plugin import DjangoDbBlocker


class NativeTestDatabaseConfigurationError(RuntimeError):
    """Raised when a Native component has no explicit isolated test database."""


class NativeTestDatabaseMismatchError(RuntimeError):
    """Raised when Django's active PostgreSQL connection misses TEST.NAME."""


class _Cursor(Protocol):
    """Small cursor surface needed to verify the active PostgreSQL database."""

    def __enter__(self) -> _Cursor: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def execute(self, sql: str) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class DatabaseConnection(Protocol):
    """Structural subset of Django's configured default database wrapper."""

    alias: str
    vendor: str
    settings_dict: MutableMapping[str, object]

    def cursor(self) -> AbstractContextManager[_Cursor]: ...


DatabaseSetupConfig = list[tuple[BaseDatabaseWrapper, str, bool]]


@dataclass
class _ActiveSetup:
    """One process-wide setup lease shared by the two Native component modules."""

    database_name: str
    setup_config: DatabaseSetupConfig | None
    created_by_helper: bool
    reuse_database: bool
    lease_count: int


_DATABASE_SETUP_LOCK = RLock()
_ACTIVE_SETUP: _ActiveSetup | None = None
_DEFAULT_CONNECTION = cast(DatabaseConnection, django_connection)
_DEFAULT_SOURCE_DATABASE_NAME_VALUE = _DEFAULT_CONNECTION.settings_dict.get("NAME")
_DEFAULT_SOURCE_DATABASE_NAME = (
    _DEFAULT_SOURCE_DATABASE_NAME_VALUE
    if isinstance(_DEFAULT_SOURCE_DATABASE_NAME_VALUE, str)
    else None
)


def _test_database_settings(database: DatabaseConnection) -> MutableMapping[str, object]:
    """Return Django's mutable TEST settings after checking their shape."""

    raw_test_settings = database.settings_dict.get("TEST")
    if not isinstance(raw_test_settings, MutableMapping):
        raise NativeTestDatabaseConfigurationError(
            "The default PostgreSQL database requires an explicit TEST configuration."
        )
    return cast(MutableMapping[str, object], raw_test_settings)


def _explicit_test_database_name(database: DatabaseConnection) -> str:
    """Return a nonblank, explicit Django TEST.NAME without deriving a fallback."""

    test_name = _test_database_settings(database).get("NAME")
    if not isinstance(test_name, str) or not test_name or test_name.strip() != test_name:
        raise NativeTestDatabaseConfigurationError(
            "The default PostgreSQL database requires an explicit nonblank TEST.NAME."
        )
    return test_name


def _read_current_database_name(database: DatabaseConnection) -> str:
    """Read PostgreSQL's actual database identity through a read-only SQL query."""

    with database.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row is None or not row or not isinstance(row[0], str):
        raise NativeTestDatabaseMismatchError(
            "PostgreSQL did not return a current database name for the Native test guard."
        )
    return row[0]


def assert_native_postgres_test_database(
    *,
    expected_name: str | None = None,
    database: DatabaseConnection = _DEFAULT_CONNECTION,
) -> str:
    """Require Django settings and PostgreSQL SQL to identify the same TEST.NAME."""

    if database.vendor != "postgresql":
        raise NativeTestDatabaseConfigurationError(
            "The Native calendar component requires PostgreSQL."
        )
    if database.alias != "default":
        raise NativeTestDatabaseConfigurationError(
            "The Native calendar component only supports the default database alias."
        )

    configured_test_name = _explicit_test_database_name(database)
    target_name = configured_test_name if expected_name is None else expected_name
    if target_name != configured_test_name:
        raise NativeTestDatabaseConfigurationError(
            "The requested Native database does not match the configured TEST.NAME."
        )
    source_name = _DEFAULT_SOURCE_DATABASE_NAME
    if source_name is not None and target_name == source_name:
        raise NativeTestDatabaseConfigurationError(
            "The configured PostgreSQL TEST.NAME must differ from the source database name."
        )
    if database.settings_dict.get("NAME") != target_name:
        raise NativeTestDatabaseMismatchError(
            "Django's active connection name does not match the configured TEST.NAME."
        )

    actual_name = _read_current_database_name(database)
    if actual_name != target_name:
        raise NativeTestDatabaseMismatchError(
            "PostgreSQL current_database() does not match the configured TEST.NAME."
        )
    return target_name


def _acquire_database_setup(
    *,
    database: DatabaseConnection,
    blocker: DjangoDbBlocker,
    source_database_name: str | None,
    use_migrations: bool,
    reuse_db: bool,
    create_db: bool,
    verbosity: int,
) -> _ActiveSetup:
    """Set up or safely reuse the one explicit default PostgreSQL test database."""

    global _ACTIVE_SETUP

    if database.vendor != "postgresql":
        raise NativeTestDatabaseConfigurationError(
            "The Native calendar component requires PostgreSQL."
        )
    if database.alias != "default":
        raise NativeTestDatabaseConfigurationError(
            "The Native calendar component only supports the default database alias."
        )
    target_name = _explicit_test_database_name(database)
    source_name = source_database_name
    if source_name is not None and target_name == source_name:
        raise NativeTestDatabaseConfigurationError(
            "The configured PostgreSQL TEST.NAME must differ from the source database name."
        )

    with _DATABASE_SETUP_LOCK:
        if _ACTIVE_SETUP is not None:
            if _ACTIVE_SETUP.database_name != target_name:
                raise NativeTestDatabaseConfigurationError(
                    "A different Native test database setup is already active."
                )
            with blocker.unblock():
                assert_native_postgres_test_database(expected_name=target_name, database=database)
            _ACTIVE_SETUP.lease_count += 1
            return _ACTIVE_SETUP

        current_configured_name = database.settings_dict.get("NAME")
        if current_configured_name == target_name:
            # pytest-django or another module already activated this test DB.
            with blocker.unblock():
                assert_native_postgres_test_database(expected_name=target_name, database=database)
            _ACTIVE_SETUP = _ActiveSetup(
                database_name=target_name,
                setup_config=None,
                created_by_helper=False,
                reuse_database=reuse_db,
                lease_count=1,
            )
            return _ACTIVE_SETUP

        if not isinstance(current_configured_name, str) or not current_configured_name:
            raise NativeTestDatabaseConfigurationError(
                "The default PostgreSQL source database name is unavailable."
            )
        test_settings = _test_database_settings(database)
        had_migrate_setting = "MIGRATE" in test_settings
        original_migrate_setting = test_settings.get("MIGRATE")
        if not use_migrations:
            test_settings["MIGRATE"] = False
        try:
            with blocker.unblock():
                setup_config = cast(
                    DatabaseSetupConfig,
                    setup_databases(
                        verbosity=verbosity,
                        interactive=False,
                        aliases={"default"},
                        serialized_aliases=set(),
                        keepdb=reuse_db and not create_db,
                    ),
                )
        finally:
            if had_migrate_setting:
                test_settings["MIGRATE"] = original_migrate_setting
            else:
                test_settings.pop("MIGRATE", None)

        with blocker.unblock():
            assert_native_postgres_test_database(expected_name=target_name, database=database)
        _ACTIVE_SETUP = _ActiveSetup(
            database_name=target_name,
            setup_config=setup_config,
            created_by_helper=True,
            reuse_database=reuse_db,
            lease_count=1,
        )
        return _ACTIVE_SETUP


def _release_database_setup(
    *,
    state: _ActiveSetup,
    blocker: DjangoDbBlocker,
    verbosity: int,
) -> None:
    """Release one module's setup lease and teardown only a helper-owned DB."""

    global _ACTIVE_SETUP

    with _DATABASE_SETUP_LOCK:
        if _ACTIVE_SETUP is not state or state.lease_count < 1:
            raise NativeTestDatabaseConfigurationError(
                "The Native PostgreSQL test database setup lease is inconsistent."
            )
        state.lease_count -= 1
        if state.lease_count:
            return
        _ACTIVE_SETUP = None
        if not state.created_by_helper or state.reuse_database:
            return
        if state.setup_config is None:
            raise NativeTestDatabaseConfigurationError(
                "A helper-owned Native database setup has no teardown configuration."
            )
        with blocker.unblock():
            teardown_databases(state.setup_config, verbosity=verbosity)


@contextmanager
def native_postgres_database_session(
    *,
    database: DatabaseConnection,
    blocker: DjangoDbBlocker,
    source_database_name: str | None,
    use_migrations: bool,
    reuse_db: bool,
    create_db: bool,
    verbosity: int,
) -> Iterator[str]:
    """Share one verified PostgreSQL test DB setup across Native component modules."""

    state = _acquire_database_setup(
        database=database,
        blocker=blocker,
        source_database_name=source_database_name,
        use_migrations=use_migrations,
        reuse_db=reuse_db,
        create_db=create_db,
        verbosity=verbosity,
    )
    try:
        yield state.database_name
    finally:
        _release_database_setup(state=state, blocker=blocker, verbosity=verbosity)


@pytest.fixture(scope="session", name="native_postgres_test_database")
def native_postgres_test_database(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker: DjangoDbBlocker,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> Iterator[str]:
    """Expose the explicit Native test database without pytest-django's empty alias set."""

    del django_test_environment, django_db_modify_db_settings
    with native_postgres_database_session(
        database=_DEFAULT_CONNECTION,
        blocker=django_db_blocker,
        source_database_name=_DEFAULT_SOURCE_DATABASE_NAME,
        use_migrations=django_db_use_migrations,
        reuse_db=django_db_keepdb,
        create_db=django_db_createdb,
        verbosity=request.config.option.verbose,
    ) as database_name:
        yield database_name
