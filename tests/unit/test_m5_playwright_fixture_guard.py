"""Narrow admission tests for the local M5 valuation fixture database."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.support.tui_research.m5_playwright_fixture_guard import (
    require_m5_valuation_fixture_database,
)

_FIXED_DATABASE_NAME = "agomtradepro-rc-playwright.sqlite3"


def _configure_m5_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner_temp: Path,
    configured_database: Path,
) -> Path:
    """Set only the explicit local CI markers and return the expected database path."""

    expected = runner_temp.resolve() / _FIXED_DATABASE_NAME
    monkeypatch.setenv("AGOM_M5_PUBLISHED_VALUATION_FIXTURE", "1")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "tests.settings.m5_playwright")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp.resolve()))
    monkeypatch.setenv("AGOM_PLAYWRIGHT_DB_PATH", str(configured_database))
    return expected


def _install_fake_django_database_boundary(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_path: Path,
) -> None:
    """Install fake settings and connection objects without opening a database."""

    django_package = ModuleType("django")
    django_package.__path__ = []
    conf_module = ModuleType("django.conf")
    conf_module.settings = SimpleNamespace(
        SETTINGS_MODULE="tests.settings.m5_playwright",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(database_path),
                "TEST": {"NAME": str(database_path)},
            }
        },
    )
    db_module = ModuleType("django.db")
    db_module.connection = SimpleNamespace(
        vendor="sqlite", settings_dict={"NAME": str(database_path)}
    )
    django_package.conf = conf_module
    django_package.db = db_module
    monkeypatch.setitem(sys.modules, "django", django_package)
    monkeypatch.setitem(sys.modules, "django.conf", conf_module)
    monkeypatch.setitem(sys.modules, "django.db", db_module)


def test_m5_guard_rejects_symlink_at_fixed_runner_temp_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    candidate = runner_temp / _FIXED_DATABASE_NAME
    candidate.write_bytes(b"disposable sqlite placeholder")
    _configure_m5_environment(
        monkeypatch,
        runner_temp=runner_temp,
        configured_database=candidate,
    )
    candidate_type = type(candidate)
    original_is_symlink = candidate_type.is_symlink

    def report_candidate_as_symlink(path: Path) -> bool:
        if path == candidate:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(candidate_type, "is_symlink", report_candidate_as_symlink)

    with pytest.raises(RuntimeError, match="cannot be a symlink"):
        require_m5_valuation_fixture_database(base_url="http://127.0.0.1:58166")


def test_m5_guard_rejects_fixed_path_resolving_outside_runner_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    outside = tmp_path / "outside" / _FIXED_DATABASE_NAME
    outside.parent.mkdir()
    outside.write_bytes(b"outside sqlite placeholder")
    candidate = runner_temp / _FIXED_DATABASE_NAME
    candidate.write_bytes(b"disposable sqlite placeholder")
    _configure_m5_environment(
        monkeypatch,
        runner_temp=runner_temp,
        configured_database=outside,
    )
    candidate_type = type(candidate)
    original_resolve = candidate_type.resolve

    def resolve_candidate_outside(path: Path, *args: object, **kwargs: object) -> Path:
        if path == candidate:
            return outside.resolve()
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(candidate_type, "resolve", resolve_candidate_outside)

    with pytest.raises(RuntimeError, match="stay inside RUNNER_TEMP"):
        require_m5_valuation_fixture_database(base_url="http://127.0.0.1:58166")


def test_m5_guard_rejects_a_different_configured_database_before_django(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    candidate = runner_temp / _FIXED_DATABASE_NAME
    candidate.write_bytes(b"disposable sqlite placeholder")
    configured_elsewhere = runner_temp / "other.sqlite3"
    configured_elsewhere.write_bytes(b"other sqlite placeholder")
    _configure_m5_environment(
        monkeypatch,
        runner_temp=runner_temp,
        configured_database=configured_elsewhere,
    )

    with pytest.raises(RuntimeError, match="must be the fixed RUNNER_TEMP M5 file"):
        require_m5_valuation_fixture_database(base_url="http://127.0.0.1:58166")


def test_m5_guard_rejects_missing_fixed_database_before_django(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    _configure_m5_environment(
        monkeypatch,
        runner_temp=runner_temp,
        configured_database=runner_temp / _FIXED_DATABASE_NAME,
    )

    with pytest.raises(RuntimeError, match="must already exist"):
        require_m5_valuation_fixture_database(base_url="http://127.0.0.1:58166")


def test_m5_guard_accepts_exact_fixed_path_with_fake_django_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    candidate = runner_temp / _FIXED_DATABASE_NAME
    candidate.write_bytes(b"disposable sqlite placeholder")
    expected = _configure_m5_environment(
        monkeypatch,
        runner_temp=runner_temp,
        configured_database=candidate,
    )
    _install_fake_django_database_boundary(monkeypatch, database_path=expected)

    assert require_m5_valuation_fixture_database(base_url="http://127.0.0.1:58166") == expected
