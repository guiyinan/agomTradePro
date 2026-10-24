"""Shared xdist contracts for test database isolation and JUnit properties.

This module deliberately imports no Django or application modules at import time.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Protocol, cast

import pytest

_SQLITE_ENGINE = "django.db.backends.sqlite3"
_WORKER_ID_PATTERN = re.compile(r"gw(?:0|[1-9][0-9]*)\Z")
JUNIT_PROPERTIES_KEY = "agomtradepro_component_testsuite_properties"


class JUnitPropertySink(Protocol):
    """Expose the one pytest JUnit method used by the worker bridge."""

    def add_global_property(self, name: str, value: object) -> None:
        """Append one property to pytest's suite-level JUnit output."""


_JUNIT_SINK: JUnitPropertySink | None = None


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
    worker_input = getattr(request.config, "workerinput", None)
    if worker_input is None:
        return
    if not isinstance(worker_input, Mapping):
        raise pytest.UsageError("xdist worker input is malformed")

    from django.conf import settings

    database_settings = settings.DATABASES.get("default")
    if not isinstance(database_settings, MutableMapping):
        raise pytest.UsageError("default database settings are unavailable")
    if database_settings.get("ENGINE") != _SQLITE_ENGINE:
        return

    test_settings = database_settings.get("TEST")
    if not isinstance(test_settings, MutableMapping):
        raise pytest.UsageError("default SQLite TEST settings are unavailable")
    test_settings["NAME"] = worker_sqlite_test_path(
        database_settings,
        database_alias="default",
        worker_id=worker_input.get("workerid"),
        process_id=os.getpid(),
        temporary_directory=tempfile.gettempdir(),
    )


@pytest.fixture(scope="session")
def record_testsuite_property(
    request: pytest.FixtureRequest,
    record_testsuite_property: Callable[[str, object], None],
) -> Callable[[str, object], None]:
    """Bridge worker JUnit properties while retaining pytest's serial/no-XML recorder."""
    return wrap_testsuite_property_recorder(request, record_testsuite_property)
