"""Pure contract checks for authority-preserving test database flush support."""

from __future__ import annotations

import sqlite3
from typing import Any, cast

import pytest

from tests.support.account_authority_generation_flush import (
    _assert_generation_non_decreasing,
    _flush_tables_without_authority_generation,
    _generation_from_rows,
    _read_authority_generation,
)


def test_flush_table_selection_accepts_restricted_app_set_without_authority_table() -> None:
    """An app-restricted flush may omit the table; the physical row is checked separately."""

    tables = ["simulated_position", "auth_group_permissions"]
    assert _flush_tables_without_authority_generation(tables) == tables


def test_flush_table_selection_excludes_one_authority_table_entry() -> None:
    """A full flush list excludes the singleton while preserving business tables."""

    assert _flush_tables_without_authority_generation(
        ["simulated_position", "account_authority_generation", "auth_group_permissions"]
    ) == ["simulated_position", "auth_group_permissions"]


def test_flush_table_selection_rejects_duplicate_authority_entries() -> None:
    """The restricted-app allowance must not mask duplicate table selections."""

    with pytest.raises(AssertionError, match="duplicate flush entries"):
        _flush_tables_without_authority_generation(
            ["account_authority_generation", "account_authority_generation"]
        )


def test_generation_rows_require_exactly_one_valid_singleton() -> None:
    """The preservation probe rejects absent, duplicate, or malformed rows."""

    assert _generation_from_rows([(1, 4)]) == 4
    with pytest.raises(AssertionError, match="exist exactly once"):
        _generation_from_rows([])
    with pytest.raises(AssertionError, match="exist exactly once"):
        _generation_from_rows([(1, 4), (1, 4)])
    with pytest.raises(AssertionError, match="nonnegative integer"):
        _generation_from_rows([(1, True)])


def test_flush_observation_allows_equal_or_increased_generation() -> None:
    """Enabled source triggers may advance the counter while rows are flushed."""

    assert _assert_generation_non_decreasing(4, 4) is None
    assert _assert_generation_non_decreasing(4, 5) is None


def test_flush_observation_rejects_generation_decrease() -> None:
    """A test cleanup may preserve or advance, but never reset the singleton."""

    with pytest.raises(AssertionError, match="decreased during flush"):
        _assert_generation_non_decreasing(5, 4)


def test_missing_physical_authority_table_is_not_suppressed() -> None:
    """The actual SQL probe propagates a missing-table database error."""

    class MissingTableCursor:
        def __enter__(self) -> MissingTableCursor:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: object | None,
        ) -> bool | None:
            return None

        def execute(self, sql: str) -> None:
            assert sql == "SELECT singleton, generation FROM account_authority_generation"
            raise sqlite3.OperationalError("no such table: account_authority_generation")

        def fetchall(self) -> list[tuple[Any, ...]]:
            raise AssertionError("A missing physical table cannot return rows.")

    class MissingTableConnection:
        def cursor(self) -> MissingTableCursor:
            return MissingTableCursor()

    class Operations:
        connection = MissingTableConnection()

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        _read_authority_generation(cast(Any, Operations()))
