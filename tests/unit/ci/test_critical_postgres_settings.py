"""An explicit test database identity is required before guarded PG cleanup."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from django.core.exceptions import ImproperlyConfigured

SETTINGS_PATH = Path(__file__).resolve().parents[3] / "core/settings/critical_postgres_test.py"
WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github/workflows/nightly-tests.yml"


def _load_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str | None,
    engine: str = "django.db.backends.postgresql",
    source: str = "critical_source",
) -> dict[str, Any]:
    """Execute the real adapter with an isolated inherited settings module."""
    inherited = ModuleType("core.settings.development")
    vars(inherited)["DATABASES"] = {"default": {"ENGINE": engine, "NAME": source}}
    monkeypatch.setitem(sys.modules, inherited.__name__, inherited)
    if name is None:
        monkeypatch.delenv("AGOM_CRITICAL_TEST_DB_NAME", raising=False)
    else:
        monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", name)
    return runpy.run_path(
        str(SETTINGS_PATH), run_name="core.settings._critical_postgres_test_probe"
    )


def test_explicit_postgres_test_identity_keeps_source_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter identifies the disposable test target without switching NAME."""
    values = _load_settings(monkeypatch, name="test_critical_source")

    assert values["DATABASES"]["default"] == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "critical_source",
        "TEST": {"NAME": "test_critical_source"},
    }


@pytest.mark.parametrize("name", [None, "", " ", " test_critical_source", "test_critical_source "])
def test_missing_or_ambiguous_test_name_fails_before_database_use(
    monkeypatch: pytest.MonkeyPatch,
    name: str | None,
) -> None:
    """A test name is never inferred from a missing or whitespace input."""
    with pytest.raises(ImproperlyConfigured, match="must name the isolated"):
        _load_settings(monkeypatch, name=name)


def test_test_database_cannot_equal_source_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly repeated source identity remains a configuration error."""
    with pytest.raises(ImproperlyConfigured, match="must differ from the source"):
        _load_settings(monkeypatch, name="critical_source")


def test_non_postgres_engine_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guarded PostgreSQL job cannot silently run with SQLite settings."""
    with pytest.raises(ImproperlyConfigured, match="require PostgreSQL"):
        _load_settings(
            monkeypatch, name="test_critical_source", engine="django.db.backends.sqlite3"
        )


def test_critical_step_binds_the_precreated_database() -> None:
    """The guarded test identity matches the clone created by the same job."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["critical-postgres"]["steps"]
    prepare = next(
        step
        for step in steps
        if step.get("name") == "Prepare pre-migrated PostgreSQL test database"
    )
    critical = next(
        step for step in steps if step.get("name") == "Run PostgreSQL critical reliability tests"
    )
    assert critical["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.critical_postgres_test"
    test_name = critical["env"]["AGOM_CRITICAL_TEST_DB_NAME"]
    assert test_name == "test_agomtradepro_critical"
    assert f"CREATE DATABASE {test_name} TEMPLATE " in prepare["run"]

    for step_name in (
        "Run PostgreSQL migration integrity tests",
        "Run current-data contract manifest on PostgreSQL",
    ):
        step = next(step for step in steps if step.get("name") == step_name)
        assert step["env"]["DJANGO_SETTINGS_MODULE"] == ("core.settings.critical_postgres_test")
        assert step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == test_name

    browser_install_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install Python browser runtime for current-data contracts"
    )
    current_data_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Run current-data contract manifest on PostgreSQL"
    )
    assert browser_install_index + 1 == current_data_index
    assert (
        steps[browser_install_index]["run"].strip()
        == "python -m playwright install --with-deps chromium"
    )
