"""Isolated settings for browser tests that exercise a managed live server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured

from .development_sqlite import *  # noqa: F403

_database_path = os.environ.get("AGOM_PLAYWRIGHT_DB_PATH", "").strip()
if not _database_path:
    raise ImproperlyConfigured(
        "AGOM_PLAYWRIGHT_DB_PATH is required for the Playwright settings module"
    )

_resolved_database_path = Path(_database_path).expanduser().resolve()
_resolved_database_path.parent.mkdir(parents=True, exist_ok=True)

# The managed runserver and pytest are separate processes. They must point to the
# same isolated SQLite file so browser authentication and committed fixtures are
# visible to both processes. Callers must use a disposable path and --reuse-db.
_databases = cast(dict[str, dict[str, Any]], DATABASES)  # noqa: F405
_default_database = _databases.setdefault("default", {})
_default_database["NAME"] = str(_resolved_database_path)
_test_database = _default_database.setdefault("TEST", {})
_test_database["NAME"] = str(_resolved_database_path)

# Matrix-driven browser UAT executes hundreds of governed TUI actions against a
# disposable server. Preserve throttling behavior while preventing unrelated 429s.
_rest_framework = cast(dict[str, Any], REST_FRAMEWORK)  # noqa: F405
_default_throttle_rates = cast(
    dict[str, str],
    _rest_framework.setdefault("DEFAULT_THROTTLE_RATES", {}),
)
_rest_framework["DEFAULT_THROTTLE_RATES"] = {
    **_default_throttle_rates,
    "anon": "10000/hour",
    "user": "100000/hour",
    "backtest": "1000/hour",
    "write": "10000/hour",
    "burst": "10000/minute",
}
