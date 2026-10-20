"""Constrain synthetic research seeders to explicit disposable test files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

from django.conf import settings
from django.db import connection

from tests.support.native_postgres_database import assert_native_postgres_test_database

_NATIVE_POSTGRES_SYNTHETIC_TEST_IDS: Final[frozenset[str]] = frozenset(
    {
        "tests/api/test_equity_published_valuation_member_read.py::"
        "test_published_valuation_api_reads_exact_current_members_and_source_clocks",
        "tests/api/test_equity_published_valuation_member_read.py::"
        "test_published_valuation_api_blocks_when_current_member_is_missing",
    }
)


def require_test_database(*, allow_native_postgres_test: bool = False) -> Path | None:
    """Reject unsafe fixture databases; opt PostgreSQL in for two exact CI contracts."""

    if connection.vendor == "postgresql":
        current_test = os.environ.get("PYTEST_CURRENT_TEST", "").partition(" ")[0]
        if (
            not allow_native_postgres_test
            or current_test not in _NATIVE_POSTGRES_SYNTHETIC_TEST_IDS
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "core.settings.critical_postgres_test"
        ):
            raise AssertionError("This source-bearing synthetic fixture requires disposable SQLite")
        database_name = assert_native_postgres_test_database()
        if not database_name.startswith("test_") or database_name != os.environ.get(
            "AGOM_CRITICAL_TEST_DB_NAME"
        ):
            raise AssertionError("Native synthetic fixture requires its exact test_ database")
        return None
    if connection.vendor != "sqlite":
        raise AssertionError("This source-bearing synthetic fixture requires disposable SQLite")
    raw = connection.settings_dict.get("NAME")
    if not isinstance(raw, str) or not raw or raw == ":memory:" or raw.startswith("file:"):
        raise AssertionError("Research consumer fixture requires an explicit SQLite file")
    target = Path(raw).resolve()
    repo_tmp = (Path(settings.BASE_DIR) / ".tmp").resolve()
    if getattr(settings, "IS_TUX08_FORMAL_TEST", False) is True:
        qa_root = Path(settings.QA_ROOT).resolve()
        expected = {
            qa_root / name
            for name in (
                "tux08-default.sqlite3",
                "tux08-tests.sqlite3",
                "tux08-browser.sqlite3",
                "tux08-browser-tests.sqlite3",
            )
        }
        if not qa_root.is_relative_to(repo_tmp) or target not in expected:
            raise AssertionError("Formal research fixture is outside its exact QA database set")
        return target
    test_options = connection.settings_dict.get("TEST", {})
    test_name = test_options.get("NAME") if isinstance(test_options, dict) else None
    if (
        not os.environ.get("PYTEST_CURRENT_TEST")
        or not isinstance(test_name, str)
        or Path(test_name).resolve() != target
        or not target.name.startswith("test_")
        or not (
            target.is_relative_to(repo_tmp)
            or target.is_relative_to(Path(tempfile.gettempdir()).resolve())
        )
    ):
        raise AssertionError("Fixture requires pytest's exact configured temporary test database")
    return target
