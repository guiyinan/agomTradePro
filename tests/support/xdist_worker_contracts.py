"""Shared xdist contracts for test database isolation and JUnit properties.

This module deliberately imports no Django or application modules at import time.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import NamedTuple, Protocol, cast

import pytest

_SQLITE_ENGINE = "django.db.backends.sqlite3"
_WORKER_ID_PATTERN = re.compile(r"gw(?:0|[1-9][0-9]*)\Z")
JUNIT_PROPERTIES_KEY = "agomtradepro_component_testsuite_properties"


class JUnitPropertySink(Protocol):
    """Expose the one pytest JUnit method used by the worker bridge."""

    def add_global_property(self, name: str, value: object) -> None:
        """Append one property to pytest's suite-level JUnit output."""


_JUNIT_SINK: JUnitPropertySink | None = None


class _SQLiteWorkerPathBinding(NamedTuple):
    """Bind duplicate fixture layers to one validated worker database path."""

    database_alias: str
    engine: str
    worker_id: str
    process_id: int
    source_path: str
    temporary_directory: str
    suffixed_test_path: str
    restored_test_path: str


class _SQLiteTestDatabaseCreation(Protocol):
    """Expose the Django test-database name method missing from its stubs."""

    def _get_test_db_name(self) -> str:
        """Return the configured name of the active test database."""
        ...


_SQLITE_WORKER_PATH_BINDING_KEY: pytest.StashKey[_SQLiteWorkerPathBinding] = pytest.StashKey()


def normalized_path(value: str | Path) -> str:
    """Return a platform-normalized absolute filesystem path."""
    return os.path.normcase(str(Path(value).resolve()))


def worker_sqlite_test_path(
    database_settings: Mapping[str, object],
    *,
    database_alias: object,
    worker_id: object,
    process_id: object,
    temporary_directory: str | Path,
) -> str:
    """Validate pytest-django's exact worker suffix and return this PID's SQLite path."""
    if database_alias != "default":
        raise pytest.UsageError("SQLite worker path is only valid for the default alias")
    if database_settings.get("ENGINE") != _SQLITE_ENGINE:
        raise pytest.UsageError("worker path validation requires SQLite")
    if not isinstance(worker_id, str) or _WORKER_ID_PATTERN.fullmatch(worker_id) is None:
        raise pytest.UsageError("SQLite worker ID is malformed")
    if type(process_id) is not int or process_id <= 0:
        raise pytest.UsageError("SQLite worker PID is invalid")

    test_settings = database_settings.get("TEST")
    if not isinstance(test_settings, Mapping):
        raise pytest.UsageError("SQLite worker TEST settings are missing")
    worker_test_name = test_settings.get("NAME")
    source_name = database_settings.get("NAME")
    if not isinstance(worker_test_name, str) or not isinstance(source_name, str):
        raise pytest.UsageError("SQLite source and test paths must be strings")
    if ".." in Path(worker_test_name).parts:
        raise pytest.UsageError("SQLite worker test path contains traversal")

    test_root = Path(temporary_directory) / "agomtradepro-test-databases"
    base_path = test_root / f"test_db_{process_id}.sqlite3"
    suffixed_path = Path(f"{base_path}_{worker_id}")
    if normalized_path(worker_test_name) != normalized_path(suffixed_path):
        raise pytest.UsageError(
            "SQLite worker TEST.NAME does not match the exact PID and worker suffix"
        )

    source_path = normalized_path(source_name)
    if source_path in {
        normalized_path(base_path),
        normalized_path(suffixed_path),
    }:
        raise pytest.UsageError("SQLite test path aliases the source database")
    return str(base_path)


def _build_sqlite_worker_path_binding(
    database_settings: Mapping[str, object],
    *,
    database_alias: str,
    worker_id: object,
    process_id: object,
    temporary_directory: str | Path,
    suffixed_test_path: str,
    restored_test_path: str,
) -> _SQLiteWorkerPathBinding:
    """Capture the exact identity that passed the strict SQLite path validator."""
    engine = database_settings.get("ENGINE")
    source_name = database_settings.get("NAME")
    if (
        database_alias != "default"
        or engine != _SQLITE_ENGINE
        or not isinstance(worker_id, str)
        or type(process_id) is not int
        or process_id <= 0
        or not isinstance(source_name, str)
    ):
        raise pytest.UsageError("SQLite worker bridge identity is invalid")
    return _SQLiteWorkerPathBinding(
        database_alias=database_alias,
        engine=_SQLITE_ENGINE,
        worker_id=worker_id,
        process_id=process_id,
        source_path=normalized_path(source_name),
        temporary_directory=normalized_path(temporary_directory),
        suffixed_test_path=normalized_path(suffixed_test_path),
        restored_test_path=normalized_path(restored_test_path),
    )


def wrap_testsuite_property_recorder(
    request: pytest.FixtureRequest,
    original_recorder: Callable[[str, object], None],
) -> Callable[[str, object], None]:
    """Capture JUnit suite properties in workeroutput while preserving no-XML behavior."""
    config = request.config
    worker_input = getattr(config, "workerinput", None)
    xml_path = config.getoption("xmlpath", default=None)
    if worker_input is None or xml_path is None:
        return original_recorder
    if not isinstance(worker_input, Mapping):
        raise pytest.UsageError("xdist worker input is malformed")

    worker_output = getattr(config, "workeroutput", None)
    if not isinstance(worker_output, MutableMapping):
        raise pytest.UsageError("xdist worker output is unavailable for JUnit properties")

    def record(name: str, value: object) -> None:
        """Validate through pytest's recorder and preserve duplicate properties."""
        original_recorder(name, value)
        raw_properties = worker_output.get(JUNIT_PROPERTIES_KEY)
        if not isinstance(raw_properties, list):
            raise pytest.UsageError("xdist JUnit property buffer is missing or invalid")
        properties = cast(list[tuple[str, str]], raw_properties)
        properties.append((name, str(value)))
        worker_output[JUNIT_PROPERTIES_KEY] = properties

    return record


def find_junit_sink(config: pytest.Config) -> JUnitPropertySink | None:
    """Find exactly one configured built-in JUnit writer, failing closed if absent."""
    if config.getoption("xmlpath", default=None) is None:
        return None
    candidates = [
        plugin
        for plugin in config.pluginmanager.get_plugins()
        if type(plugin).__module__ == "_pytest.junitxml" and type(plugin).__name__ == "LogXML"
    ]
    if len(candidates) != 1:
        raise pytest.UsageError(
            "JUnit output was requested but its single LogXML sink is unavailable"
        )
    sink = candidates[0]
    if not callable(getattr(sink, "add_global_property", None)):
        raise pytest.UsageError("JUnit LogXML sink does not support suite properties")
    return cast(JUnitPropertySink, sink)


def replay_testsuite_properties(
    worker_output: Mapping[str, object],
    sink: JUnitPropertySink | None,
) -> None:
    """Replay every serialized worker property without merging duplicate names."""
    if JUNIT_PROPERTIES_KEY not in worker_output:
        if sink is None:
            return
        raise pytest.UsageError("xdist worker omitted its initialized JUnit property buffer")
    raw_properties = worker_output[JUNIT_PROPERTIES_KEY]
    if not isinstance(raw_properties, list):
        raise pytest.UsageError("xdist JUnit property output has an invalid shape")
    if not raw_properties:
        return
    if sink is None:
        raise pytest.UsageError("xdist worker recorded JUnit properties without a master sink")

    for raw_property in raw_properties:
        if (
            not isinstance(raw_property, tuple)
            or len(raw_property) != 2
            or not isinstance(raw_property[0], str)
            or not isinstance(raw_property[1], str)
        ):
            raise pytest.UsageError("xdist JUnit property entry is malformed")
        sink.add_global_property(raw_property[0], raw_property[1])


def pytest_sessionstart(session: pytest.Session) -> None:
    """Initialize worker property transport or resolve the master JUnit writer."""
    global _JUNIT_SINK
    if hasattr(session.config, "workerinput"):
        if session.config.getoption("xmlpath", default=None) is None:
            return
        worker_input = getattr(session.config, "workerinput", None)
        if not isinstance(worker_input, Mapping):
            raise pytest.UsageError("xdist worker input is malformed")
        worker_output = getattr(session.config, "workeroutput", None)
        if not isinstance(worker_output, MutableMapping):
            raise pytest.UsageError("xdist worker output is unavailable for JUnit properties")
        raw_properties = worker_output.setdefault(JUNIT_PROPERTIES_KEY, [])
        if not isinstance(raw_properties, list) or raw_properties:
            raise pytest.UsageError("xdist JUnit property buffer was not initially empty")
        return
    _JUNIT_SINK = find_junit_sink(session.config)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object, error: object | None) -> None:
    """Transfer completed worker suite properties to the controller's JUnit sink."""
    if error is not None:
        return
    worker_output = getattr(node, "workeroutput", None)
    if not isinstance(worker_output, Mapping):
        raise pytest.UsageError("completed xdist worker did not provide workeroutput")
    replay_testsuite_properties(worker_output, _JUNIT_SINK)


@pytest.fixture(scope="session")
def django_db_modify_db_settings_xdist_suffix(
    django_db_modify_db_settings_xdist_suffix: None,
    request: pytest.FixtureRequest,
) -> None:
    """Keep pytest-django's ordering, then restore the already PID-isolated SQLite path."""
    binding = request.config.stash.get(_SQLITE_WORKER_PATH_BINDING_KEY, None)
    worker_input = getattr(request.config, "workerinput", None)
    if worker_input is None:
        if binding is not None:
            raise pytest.UsageError("SQLite worker identity disappeared after path validation")
        return
    if not isinstance(worker_input, Mapping):
        raise pytest.UsageError("xdist worker input is malformed")

    from django.conf import settings

    database_settings = settings.DATABASES.get("default")
    if not isinstance(database_settings, MutableMapping):
        raise pytest.UsageError("default database settings are unavailable")
    if database_settings.get("ENGINE") != _SQLITE_ENGINE:
        if binding is not None:
            raise pytest.UsageError("SQLite worker database engine changed after path validation")
        return

    test_settings = database_settings.get("TEST")
    if not isinstance(test_settings, MutableMapping):
        raise pytest.UsageError("default SQLite TEST settings are unavailable")

    database_alias = "default"
    worker_id = worker_input.get("workerid")
    process_id = os.getpid()
    temporary_directory = tempfile.gettempdir()
    current_test_path = test_settings.get("NAME")
    if not isinstance(current_test_path, str):
        raise pytest.UsageError("default SQLite worker TEST.NAME is unavailable")

    if binding is None:
        restored_test_path = worker_sqlite_test_path(
            database_settings,
            database_alias=database_alias,
            worker_id=worker_id,
            process_id=process_id,
            temporary_directory=temporary_directory,
        )
        binding = _build_sqlite_worker_path_binding(
            database_settings,
            database_alias=database_alias,
            worker_id=worker_id,
            process_id=process_id,
            temporary_directory=temporary_directory,
            suffixed_test_path=current_test_path,
            restored_test_path=restored_test_path,
        )
        test_settings["NAME"] = restored_test_path
        request.config.stash[_SQLITE_WORKER_PATH_BINDING_KEY] = binding
        return

    if not isinstance(binding, _SQLiteWorkerPathBinding):
        raise pytest.UsageError("SQLite worker bridge identity token is malformed")
    if (
        binding.database_alias != database_alias
        or binding.engine != _SQLITE_ENGINE
        or binding.worker_id != worker_id
        or binding.process_id != process_id
        or binding.temporary_directory != normalized_path(temporary_directory)
    ):
        raise pytest.UsageError("SQLite worker bridge identity changed after path validation")
    if normalized_path(current_test_path) != binding.restored_test_path:
        raise pytest.UsageError("SQLite worker bridge identity or path changed after validation")

    source_name = database_settings.get("NAME")
    if not isinstance(source_name, str):
        raise pytest.UsageError("SQLite source path changed after path validation")
    current_source_path = normalized_path(source_name)
    if current_source_path == binding.restored_test_path:
        from django.db import connections

        try:
            connection = connections[database_alias]
            creation = cast(_SQLiteTestDatabaseCreation, connection.creation)
            active_test_path = creation._get_test_db_name()
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise pytest.UsageError(
                "post-setup SQLite connection identity cannot be verified"
            ) from exc
        if connection.alias != database_alias or connection.settings_dict is not database_settings:
            raise pytest.UsageError("post-setup SQLite connection does not use the bound settings")
        if (
            not isinstance(active_test_path, str)
            or normalized_path(active_test_path) != binding.restored_test_path
        ):
            raise pytest.UsageError(
                "post-setup SQLite connection test path changed after validation"
            )
    elif current_source_path != binding.source_path:
        raise pytest.UsageError("SQLite source path changed after path validation")

    validation_database_settings = dict(database_settings)
    validation_test_settings = dict(test_settings)
    validation_database_settings["NAME"] = binding.source_path
    validation_test_settings["NAME"] = binding.suffixed_test_path
    validation_database_settings["TEST"] = validation_test_settings
    restored_test_path = worker_sqlite_test_path(
        validation_database_settings,
        database_alias=database_alias,
        worker_id=worker_id,
        process_id=process_id,
        temporary_directory=temporary_directory,
    )
    current_binding = _build_sqlite_worker_path_binding(
        validation_database_settings,
        database_alias=database_alias,
        worker_id=worker_id,
        process_id=process_id,
        temporary_directory=temporary_directory,
        suffixed_test_path=binding.suffixed_test_path,
        restored_test_path=restored_test_path,
    )
    if (
        current_binding != binding
        or normalized_path(restored_test_path) != binding.restored_test_path
    ):
        raise pytest.UsageError("SQLite worker bridge identity or path changed after validation")


@pytest.fixture(scope="session")
def record_testsuite_property(
    request: pytest.FixtureRequest,
    record_testsuite_property: Callable[[str, object], None],
) -> Callable[[str, object], None]:
    """Bridge worker JUnit properties while retaining pytest's serial/no-XML recorder."""
    return wrap_testsuite_property_recorder(request, record_testsuite_property)
