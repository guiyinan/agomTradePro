"""Isolated settings for native PostgreSQL critical reliability tests."""

from __future__ import annotations

import os
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured

from .development import *  # noqa: F403

_test_database_name = os.environ.get("AGOM_CRITICAL_TEST_DB_NAME", "")
if not _test_database_name or _test_database_name.strip() != _test_database_name:
    raise ImproperlyConfigured(
        "AGOM_CRITICAL_TEST_DB_NAME must name the isolated PostgreSQL test database"
    )

_databases = cast(dict[str, dict[str, Any]], DATABASES)  # noqa: F405
_default_database = _databases["default"]
if _default_database.get("ENGINE") != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Critical reliability tests require PostgreSQL")
_source_database_name = _default_database.get("NAME")
if not isinstance(_source_database_name, str) or _source_database_name == _test_database_name:
    raise ImproperlyConfigured(
        "The critical PostgreSQL test database must differ from the source database"
    )
_test_database = _default_database.setdefault("TEST", {})
_test_database["NAME"] = _test_database_name
