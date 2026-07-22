"""Isolated settings for browser tests that exercise a managed live server."""

from __future__ import annotations

import os
from pathlib import Path

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
DATABASES["default"]["NAME"] = str(_resolved_database_path)  # noqa: F405
DATABASES["default"]["TEST"]["NAME"] = str(_resolved_database_path)  # noqa: F405
