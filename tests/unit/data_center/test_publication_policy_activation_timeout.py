"""Timeout-boundary tests for policy activation's PostgreSQL guard."""

from __future__ import annotations

import pytest

from apps.data_center.infrastructure import publication_policy_activation_timeout as timeout_module


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)
        prefix = "SET LOCAL "
        if statement.startswith(prefix):
            setting, value = statement.removeprefix(prefix).split(" = ", maxsplit=1)
            self.connection.settings[setting] = value.strip("'")

    def fetchone(self) -> tuple[str]:
        statement = self.statements[-1]
        if statement == "SHOW lock_timeout":
            return (self.connection.settings["lock_timeout"],)
        if statement == "SHOW statement_timeout":
            return (self.connection.settings["statement_timeout"],)
        raise AssertionError(f"unexpected fetchone after {statement!r}")


class _Connection:
    vendor = "postgresql"
    in_atomic_block = True
    needs_rollback = False

    def __init__(self, *, lock_timeout: str, statement_timeout: str) -> None:
        self.settings = {
            "lock_timeout": lock_timeout,
            "statement_timeout": statement_timeout,
        }
        self.cursor_value = _Cursor(self)

    def cursor(self) -> _Cursor:
        return self.cursor_value


class _Savepoint:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        # Model Django's savepoint rollback before the outer guard's finally.
        self.connection.needs_rollback = False
        return False


def test_guard_preserves_stricter_caller_and_restores_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2s caller lock and 60s statement remain bounded and are restored."""

    connection = _Connection(lock_timeout="2s", statement_timeout="60s")
    monkeypatch.setattr(timeout_module, "connection", connection)

    with timeout_module.postgres_timeout_guard(5_000, 35_000) as guard:
        guard.apply()
        assert connection.settings == {
            "lock_timeout": "2s",
            "statement_timeout": "35s",
        }

    assert connection.settings == {"lock_timeout": "2s", "statement_timeout": "60s"}
    assert connection.cursor_value.statements == [
        "SHOW lock_timeout",
        "SHOW statement_timeout",
        "SET LOCAL lock_timeout = '2s'",
        "SET LOCAL statement_timeout = '35s'",
        "SET LOCAL lock_timeout = '2s'",
        "SET LOCAL statement_timeout = '60s'",
    ]


def test_guard_restores_after_savepoint_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An activation failure restores settings only after its savepoint settles."""

    connection = _Connection(lock_timeout="0", statement_timeout="7s")
    monkeypatch.setattr(timeout_module, "connection", connection)

    with pytest.raises(RuntimeError, match="activation failure"):
        with timeout_module.postgres_timeout_guard(5_000, 35_000) as guard:
            with _Savepoint(connection):
                guard.apply()
                raise RuntimeError("activation failure")

    assert connection.settings == {"lock_timeout": "0", "statement_timeout": "7s"}
    assert connection.cursor_value.statements[-2:] == [
        "SET LOCAL lock_timeout = '0'",
        "SET LOCAL statement_timeout = '7s'",
    ]
