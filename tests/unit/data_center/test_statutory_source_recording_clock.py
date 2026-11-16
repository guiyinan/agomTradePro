"""Unexecuted focused clock-selection tests for the source repository patch."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.data_center.application.statutory_source_documents import (
    StatutorySourceDocumentBodyStorePort,
)
from apps.data_center.infrastructure import statutory_source_repository as repository_module
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)

_FIXED = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
_DATABASE_NOW = datetime(2026, 11, 16, 9, 1, tzinfo=UTC)


class _Cursor:
    """Minimal cursor double for PostgreSQL clock selection."""

    def __init__(self, database_now: datetime) -> None:
        self.database_now = database_now
        self.statement: str | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statement = statement

    def fetchone(self) -> tuple[datetime]:
        return (self.database_now,)


class _Connection:
    """Expose only the backend and cursor surface used by the repository."""

    def __init__(self, vendor: str, database_now: datetime = _DATABASE_NOW) -> None:
        self.vendor = vendor
        self.cursor_calls = 0
        self.last_cursor = _Cursor(database_now)

    def cursor(self) -> AbstractContextManager[_Cursor]:
        self.cursor_calls += 1
        return self.last_cursor


class _Connections:
    """Route the repository's default alias to one fake connection."""

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __getitem__(self, alias: str) -> _Connection:
        assert alias == "default"
        return self.connection


def _repository(*, clock: Callable[[], datetime] | None = None) -> DjangoStatutorySourceRepository:
    """Build a repository without using its body-store dependency in clock tests."""

    return DjangoStatutorySourceRepository(
        body_store=cast(StatutorySourceDocumentBodyStorePort, object()),
        using="default",
        clock=clock,
    )


@pytest.mark.parametrize("vendor", ("sqlite", "postgresql"))
def test_injected_clock_keeps_priority_without_backend_clock_queries(
    monkeypatch: pytest.MonkeyPatch, vendor: str
) -> None:
    """Preserve deterministic injected-clock behavior on every backend."""

    connection = _Connection(vendor)
    monkeypatch.setattr(repository_module, "connections", _Connections(connection))
    repository = _repository(clock=lambda: _FIXED)

    assert repository._now() == _FIXED
    assert connection.cursor_calls == 0


def test_default_sqlite_clock_uses_django_time_and_skips_postgres_table_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep SQLite fallback behavior without issuing PG clock or lock SQL."""

    connection = _Connection("sqlite")
    monkeypatch.setattr(repository_module, "connections", _Connections(connection))
    monkeypatch.setattr(repository_module.timezone, "now", lambda: _FIXED)
    repository = _repository()

    assert repository._now() == _FIXED
    repository._lock_capture_append_tables()
    assert connection.cursor_calls == 0


def test_default_postgres_clock_uses_clock_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the configured PostgreSQL server clock when no test clock is injected."""

    connection = _Connection("postgresql", _DATABASE_NOW)
    monkeypatch.setattr(repository_module, "connections", _Connections(connection))
    repository = _repository()

    assert repository._now() == _DATABASE_NOW
    assert connection.cursor_calls == 1
    assert connection.last_cursor.statement == "SELECT clock_timestamp()"
