"""Strict runtime guard for a disposable canonical universe-config fixture."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


def require_m5_universe_fixture_environment(*, databases: object) -> None:
    """Require explicit local CI, literal loopback, and the fixed runner SQLite."""

    if os.environ.get("AGOM_M5_SYNTHETIC_UNIVERSE") != "1":
        raise ValueError("AGOM_M5_SYNTHETIC_UNIVERSE must equal 1")
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "tests.settings.m5_playwright":
        raise ValueError("M5 universe fixture requires tests.settings.m5_playwright")
    if not _true("CI") or not _true("GITHUB_ACTIONS"):
        raise ValueError("M5 universe fixture requires CI and GitHub Actions")

    runner_temp_raw = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp_raw or not Path(runner_temp_raw).is_absolute():
        raise ValueError("M5 universe fixture requires an absolute RUNNER_TEMP")
    expected_database = (
        Path(runner_temp_raw).resolve() / "agomtradepro-rc-playwright.sqlite3"
    ).resolve()
    database_path_raw = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if not database_path_raw or Path(database_path_raw).expanduser().resolve() != expected_database:
        raise ValueError("M5 universe fixture database path differs from RUNNER_TEMP")
    if not isinstance(databases, dict):
        raise ValueError("M5 universe fixture database settings are unavailable")
    default_database = databases.get("default")
    if not isinstance(default_database, dict):
        raise ValueError("M5 universe fixture default database is unavailable")
    if default_database.get("ENGINE") != "django.db.backends.sqlite3":
        raise ValueError("M5 universe fixture requires SQLite")
    if Path(str(default_database.get("NAME", ""))).expanduser().resolve() != expected_database:
        raise ValueError("M5 universe fixture database NAME differs from RUNNER_TEMP")
    test_database = default_database.get("TEST")
    if not isinstance(test_database, dict):
        raise ValueError("M5 universe fixture TEST database is unavailable")
    if Path(str(test_database.get("NAME", ""))).expanduser().resolve() != expected_database:
        raise ValueError("M5 universe fixture TEST.NAME differs from RUNNER_TEMP")

    base_url = os.environ.get("AGOM_M5_UNIVERSE_BASE_URL", "").strip()
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or base_url != f"http://127.0.0.1:{parsed.port}"
    ):
        raise ValueError("M5 universe fixture requires a literal loopback base URL")


def _true(name: str) -> bool:
    """Return whether a required CI flag is explicitly true."""

    return os.environ.get(name, "").strip().lower() in {"1", "true"}
