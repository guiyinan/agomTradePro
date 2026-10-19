"""Fail-closed admission for the local M5 published-valuation fixture."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

_EXPECTED_SETTINGS_MODULE = "tests.settings.m5_playwright"
_M5_FIXTURE_OPT_IN = "AGOM_M5_PUBLISHED_VALUATION_FIXTURE"
_FIXED_DATABASE_NAME = "agomtradepro-rc-playwright.sqlite3"


def _truthy_environment_value(name: str) -> bool:
    """Return whether one required CI marker is explicitly enabled."""

    return os.environ.get(name, "").strip().lower() in {"1", "true"}


def _literal_loopback_http_origin(base_url: str) -> bool:
    """Require the exact IPv4 loopback origin used by the managed M5 server."""

    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.username is None
        and parsed.password is None
        and port is not None
        and 1 <= port <= 65535
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and base_url == f"http://127.0.0.1:{port}"
    )


def _resolved_path(value: object, *, label: str) -> Path:
    """Resolve a configured filesystem path or reject a non-path value."""

    if not isinstance(value, (str, os.PathLike)):
        raise RuntimeError(f"{label} is not a filesystem path")
    raw = str(value).strip()
    if not raw:
        raise RuntimeError(f"{label} is empty")
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        raise RuntimeError(f"{label} cannot be resolved") from None


def require_m5_valuation_fixture_database(*, base_url: str) -> Path:
    """Require an explicit M5 CI opt-in and its exact shared Playwright SQLite file."""

    if os.environ.get(_M5_FIXTURE_OPT_IN, "").strip() != "1":
        raise RuntimeError(f"{_M5_FIXTURE_OPT_IN}=1 is required before fixture writes")
    if not _literal_loopback_http_origin(base_url):
        raise RuntimeError("M5 valuation fixture requires literal http://127.0.0.1:<port>")
    if not _truthy_environment_value("CI") or not _truthy_environment_value("GITHUB_ACTIONS"):
        raise RuntimeError("M5 valuation fixture requires explicit CI and GitHub Actions markers")
    if os.environ.get("DJANGO_SETTINGS_MODULE", "").strip() != _EXPECTED_SETTINGS_MODULE:
        raise RuntimeError("M5 valuation fixture requires tests.settings.m5_playwright")
    if os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("M5 valuation fixture refuses DATABASE_URL remote scope")

    runner_temp_raw = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp_raw:
        raise RuntimeError("M5 valuation fixture requires RUNNER_TEMP")
    runner_temp = Path(runner_temp_raw).expanduser()
    if not runner_temp.is_absolute():
        raise RuntimeError("RUNNER_TEMP must be an absolute path")
    resolved_runner_temp = runner_temp.resolve()
    fixed_candidate = resolved_runner_temp / _FIXED_DATABASE_NAME
    if fixed_candidate.is_symlink():
        raise RuntimeError("the fixed M5 Playwright SQLite file cannot be a symlink")
    expected_path = fixed_candidate.resolve()
    if expected_path.parent != resolved_runner_temp or expected_path.name != _FIXED_DATABASE_NAME:
        raise RuntimeError("the fixed M5 Playwright SQLite file must stay inside RUNNER_TEMP")
    configured_path = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if (
        not configured_path
        or _resolved_path(
            configured_path,
            label="AGOM_PLAYWRIGHT_DB_PATH",
        )
        != expected_path
    ):
        raise RuntimeError("AGOM_PLAYWRIGHT_DB_PATH must be the fixed RUNNER_TEMP M5 file")
    if not expected_path.is_file():
        raise RuntimeError("the exact M5 Playwright SQLite file must already exist")

    from django.conf import settings

    if getattr(settings, "SETTINGS_MODULE", "") != _EXPECTED_SETTINGS_MODULE:
        raise RuntimeError("active Django settings differ from tests.settings.m5_playwright")
    databases = getattr(settings, "DATABASES", None)
    if not isinstance(databases, dict) or set(databases) != {"default"}:
        raise RuntimeError("M5 valuation fixture requires only the default database alias")
    database = databases.get("default")
    if not isinstance(database, dict):
        raise RuntimeError("active default database configuration is unavailable")
    if database.get("ENGINE") != "django.db.backends.sqlite3":
        raise RuntimeError("M5 valuation fixture requires SQLite")
    test_database = database.get("TEST")
    test_name = test_database.get("NAME") if isinstance(test_database, dict) else None
    if (
        _resolved_path(database.get("NAME"), label="DATABASES.default.NAME") != expected_path
        or _resolved_path(test_name, label="DATABASES.default.TEST.NAME") != expected_path
    ):
        raise RuntimeError("SQLite NAME and TEST.NAME must equal the fixed RUNNER_TEMP M5 file")

    from django.db import connection

    if (
        connection.vendor != "sqlite"
        or _resolved_path(
            connection.settings_dict.get("NAME"),
            label="active default connection NAME",
        )
        != expected_path
    ):
        raise RuntimeError("active default Django connection does not target the fixed M5 file")
    return expected_path


__all__ = ["require_m5_valuation_fixture_database"]
