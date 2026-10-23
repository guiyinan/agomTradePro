"""Shared fixtures for component-level runtime contracts."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Protocol, cast

import pytest

from tests.support.runtime_config import configure_critical_runtime


@pytest.fixture
def active_decision_runtime(db: object) -> None:
    """Explicitly admit decision-facing component requests for the test scope."""

    configure_critical_runtime()

    from apps.config_center.infrastructure.decision_runtime_models import (
        DecisionRuntimeStateModel,
    )

    DecisionRuntimeStateModel._default_manager.update_or_create(
        pk=1,
        defaults={
            "status": "active",
            "reason": "",
            "changed_by": "pytest:component-contract",
        },
    )


_SQLITE_ENGINE = "django.db.backends.sqlite3"
_WORKER_ID_PATTERN = re.compile(r"gw(?:0|[1-9][0-9]*)\Z")
_COMPONENT_JUNIT_PROPERTIES_KEY = "agomtradepro_component_testsuite_properties"


class _JUnitPropertySink(Protocol):
    """Expose the one pytest JUnit method used by the worker bridge."""

    def add_global_property(self, name: str, value: object) -> None:
        """Append one property to pytest's suite-level JUnit output."""


_COMPONENT_JUNIT_SINK: _JUnitPropertySink | None = None


def _normalized_path(value: str | Path) -> str:
    """Return a platform-normalized absolute filesystem path."""
    return os.path.normcase(str(Path(value).resolve()))


def _component_worker_sqlite_test_path(
    database_settings: Mapping[str, object],
    *,
    database_alias: object,
    worker_id: object,
    process_id: object,
    temporary_directory: str | Path,
) -> str:
    """Validate pytest-django's exact worker suffix and return this PID's SQLite path."""
    if database_alias != "default":
        raise pytest.UsageError("component SQLite worker path is only valid for the default alias")
    if database_settings.get("ENGINE") != _SQLITE_ENGINE:
        raise pytest.UsageError("component worker path validation requires SQLite")
    if not isinstance(worker_id, str) or _WORKER_ID_PATTERN.fullmatch(worker_id) is None:
        raise pytest.UsageError("component SQLite worker ID is malformed")
    if type(process_id) is not int or process_id <= 0:
        raise pytest.UsageError("component SQLite worker PID is invalid")

    test_settings = database_settings.get("TEST")
    if not isinstance(test_settings, Mapping):
        raise pytest.UsageError("component SQLite worker TEST settings are missing")
    worker_test_name = test_settings.get("NAME")
    source_name = database_settings.get("NAME")
    if not isinstance(worker_test_name, str) or not isinstance(source_name, str):
        raise pytest.UsageError("component SQLite source and test paths must be strings")
    if ".." in Path(worker_test_name).parts:
        raise pytest.UsageError("component SQLite worker test path contains traversal")

    test_root = Path(temporary_directory) / "agomtradepro-test-databases"
    base_path = test_root / f"test_db_{process_id}.sqlite3"
    suffixed_path = Path(f"{base_path}_{worker_id}")
    if _normalized_path(worker_test_name) != _normalized_path(suffixed_path):
        raise pytest.UsageError(
            "component SQLite worker TEST.NAME does not match the exact PID and worker suffix"
        )

    source_path = _normalized_path(source_name)
    if source_path in {
        _normalized_path(base_path),
        _normalized_path(suffixed_path),
    }:
        raise pytest.UsageError("component SQLite test path aliases the source database")
    return str(base_path)


def _record_component_testsuite_property(
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
        raw_properties = worker_output.get(_COMPONENT_JUNIT_PROPERTIES_KEY)
        if not isinstance(raw_properties, list):
            raise pytest.UsageError("xdist JUnit property buffer is missing or invalid")
        properties = cast(list[tuple[str, str]], raw_properties)
        properties.append((name, str(value)))
        worker_output[_COMPONENT_JUNIT_PROPERTIES_KEY] = properties

    return record


def _component_junit_sink(config: pytest.Config) -> _JUnitPropertySink | None:
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
    return cast(_JUnitPropertySink, sink)


def _replay_component_testsuite_properties(
    worker_output: Mapping[str, object],
    sink: _JUnitPropertySink | None,
) -> None:
    """Replay every serialized worker property without merging duplicate names."""
    if _COMPONENT_JUNIT_PROPERTIES_KEY not in worker_output:
        if sink is None:
            return
        raise pytest.UsageError("xdist worker omitted its initialized JUnit property buffer")
    raw_properties = worker_output[_COMPONENT_JUNIT_PROPERTIES_KEY]
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
    global _COMPONENT_JUNIT_SINK
    if hasattr(session.config, "workerinput"):
        if session.config.getoption("xmlpath", default=None) is None:
            return
        worker_input = getattr(session.config, "workerinput", None)
        if not isinstance(worker_input, Mapping):
            raise pytest.UsageError("xdist worker input is malformed")
        worker_output = getattr(session.config, "workeroutput", None)
        if not isinstance(worker_output, MutableMapping):
            raise pytest.UsageError("xdist worker output is unavailable for JUnit properties")
        raw_properties = worker_output.setdefault(_COMPONENT_JUNIT_PROPERTIES_KEY, [])
        if not isinstance(raw_properties, list) or raw_properties:
            raise pytest.UsageError("xdist JUnit property buffer was not initially empty")
        return
    _COMPONENT_JUNIT_SINK = _component_junit_sink(session.config)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object, error: object | None) -> None:
    """Transfer completed worker suite properties to the controller's JUnit sink."""
    if error is not None:
        return
    worker_output = getattr(node, "workeroutput", None)
    if not isinstance(worker_output, Mapping):
        raise pytest.UsageError("completed xdist worker did not provide workeroutput")
    _replay_component_testsuite_properties(worker_output, _COMPONENT_JUNIT_SINK)


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
        raise pytest.UsageError("component default database settings are unavailable")
    if database_settings.get("ENGINE") != _SQLITE_ENGINE:
        return

    test_settings = database_settings.get("TEST")
    if not isinstance(test_settings, MutableMapping):
        raise pytest.UsageError("component default SQLite TEST settings are unavailable")
    test_settings["NAME"] = _component_worker_sqlite_test_path(
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
    return _record_component_testsuite_property(request, record_testsuite_property)
