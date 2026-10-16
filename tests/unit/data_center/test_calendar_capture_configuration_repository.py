"""Database-fence contracts for calendar capture configuration reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from django.db import DatabaseError

from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfigurationError,
)
from apps.data_center.infrastructure.calendar_capture_configuration_repository import (
    _CONFIGURATION_MODELS,
    DjangoCalendarCaptureConfigurationRepository,
    _acquire_configuration_fence,
)


class _Cursor:
    """Record the limited SQL issued by the catalog fence."""

    def __init__(
        self,
        results: tuple[tuple[object, ...] | None, ...],
        *,
        fail_on_execute: bool = False,
    ) -> None:
        self._results = iter(results)
        self._fail_on_execute = fail_on_execute
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)
        if self._fail_on_execute:
            raise DatabaseError("synthetic database lock failure")

    def fetchone(self) -> tuple[object, ...] | None:
        return next(self._results)


class _Operations:
    """Quote only trusted model table identifiers in the test adapter."""

    @staticmethod
    def quote_name(value: str) -> str:
        return f'"{value}"'


class _Connection:
    """Small adapter for exercising PostgreSQL lock decisions without a DB."""

    vendor = "postgresql"
    ops = _Operations()

    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    @contextmanager
    def cursor(self) -> Iterator[_Cursor]:
        with self._cursor:
            yield self._cursor


@pytest.mark.parametrize("cap_timeout", [True, False])
def test_postgresql_fence_uses_sorted_shared_table_locks(cap_timeout: bool) -> None:
    cursor = _Cursor((("read committed",), (cap_timeout,)))
    connection = _Connection(cursor)

    _acquire_configuration_fence(connection)  # type: ignore[arg-type]

    lock_statements = [statement for statement in cursor.statements if "LOCK TABLE" in statement]
    assert len(lock_statements) == len(_CONFIGURATION_MODELS)
    assert lock_statements == sorted(lock_statements)
    assert ("SET LOCAL lock_timeout = '5s'" in cursor.statements) is cap_timeout


def test_postgresql_fence_rejects_non_read_committed_transactions() -> None:
    connection = _Connection(_Cursor((("repeatable read",),)))

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        _acquire_configuration_fence(connection)  # type: ignore[arg-type]

    assert raised.value.code == "CALENDAR_CAPTURE_TRANSACTION_ISOLATION_UNSUPPORTED"


def test_postgresql_fence_rejects_missing_timeout_evidence() -> None:
    connection = _Connection(_Cursor((("read committed",), None)))

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        _acquire_configuration_fence(connection)  # type: ignore[arg-type]

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_FENCE_UNAVAILABLE"


def test_postgresql_lock_database_error_is_typed() -> None:
    connection = _Connection(_Cursor((), fail_on_execute=True))

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        _acquire_configuration_fence(connection)  # type: ignore[arg-type]

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_FENCE_UNAVAILABLE"


def test_unsupported_database_vendor_is_blocked() -> None:
    connection = _Connection(_Cursor(()))
    connection.vendor = "mysql"

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        _acquire_configuration_fence(connection)  # type: ignore[arg-type]

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_VENDOR_UNSUPPORTED"


def test_repository_requires_default_caller_transaction() -> None:
    repository = DjangoCalendarCaptureConfigurationRepository()
    assert repository.unit_of_work_key == "django:default"

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        repository.load_candidates(using="replica")

    assert raised.value.code == "CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED"

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        repository.load_candidates(using="default")

    assert raised.value.code == "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
