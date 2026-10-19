"""Standard-library-only guard for enabling the disposable M5 fixture app."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


def _truthy(name: str) -> bool:
    """Return whether a required CI environment value is explicitly true."""

    return os.environ.get(name, "").strip().lower() in {"1", "true"}


def require_m5_calendar_transport_environment(*, databases: object) -> Path:
    """Validate all opt-in, URL, and database isolation guards before install."""

    if os.environ.get("AGOM_M5_SYNTHETIC_CALENDAR") != "1":
        raise ValueError("AGOM_M5_SYNTHETIC_CALENDAR must equal 1")
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "core.settings.playwright":
        raise ValueError("M5 synthetic calendar requires core.settings.playwright")
    if not _truthy("CI") or not _truthy("GITHUB_ACTIONS"):
        raise ValueError("M5 synthetic calendar requires CI and GitHub Actions")

    runner_temp_raw = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp_raw or not Path(runner_temp_raw).is_absolute():
        raise ValueError("M5 synthetic calendar requires an absolute RUNNER_TEMP")
    runner_temp = Path(runner_temp_raw).resolve()
    expected_database = (runner_temp / "agomtradepro-rc-playwright.sqlite3").resolve()

    db_path_raw = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
    if not db_path_raw or Path(db_path_raw).expanduser().resolve() != expected_database:
        raise ValueError("M5 synthetic calendar database path differs from RUNNER_TEMP")
    if not isinstance(databases, dict):
        raise ValueError("M5 synthetic calendar database settings are unavailable")
    default_database = databases.get("default")
    if not isinstance(default_database, dict):
        raise ValueError("M5 synthetic calendar default database is unavailable")
    if default_database.get("ENGINE") != "django.db.backends.sqlite3":
        raise ValueError("M5 synthetic calendar requires SQLite")
    if Path(str(default_database.get("NAME", ""))).expanduser().resolve() != expected_database:
        raise ValueError("M5 synthetic calendar database NAME differs from RUNNER_TEMP")
    test_database = default_database.get("TEST")
    if not isinstance(test_database, dict):
        raise ValueError("M5 synthetic calendar TEST database is unavailable")
    if Path(str(test_database.get("NAME", ""))).expanduser().resolve() != expected_database:
        raise ValueError("M5 synthetic calendar TEST.NAME differs from RUNNER_TEMP")

    artifact_root = (runner_temp / "agomtradepro-m5-calendar").resolve()
    artifact_root_raw = os.environ.get("AGOM_M5_CALENDAR_ARTIFACT_DIR", "").strip()
    if not artifact_root_raw or Path(artifact_root_raw).expanduser().resolve() != artifact_root:
        raise ValueError("M5 synthetic calendar artifact path differs from RUNNER_TEMP")

    base_url = os.environ.get("AGOM_M5_CALENDAR_BASE_URL", "").strip()
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
        raise ValueError("M5 synthetic calendar requires a literal loopback base URL")

    return artifact_root
