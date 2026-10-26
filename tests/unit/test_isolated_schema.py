"""Pure checks that isolated_schema opens DDL editors only for missing tables."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import isolated_schema as isolated_schema_support


class _ModelMeta:
    def __init__(self, table_name: str) -> None:
        self.db_table = table_name


class ExistingModel:
    _meta = _ModelMeta("existing_model_table")


class MissingModel:
    _meta = _ModelMeta("missing_model_table")


class _FakeCursor:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self._statements.append(statement)


class _FakeSchemaEditor:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events

    def __enter__(self) -> _FakeSchemaEditor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def create_model(self, model_type: type[Any]) -> None:
        self._events.append(("create", model_type._meta.db_table))

    def delete_model(self, model_type: type[Any]) -> None:
        self._events.append(("delete", model_type._meta.db_table))


class _FakeConnection:
    def __init__(self, existing_tables: set[str]) -> None:
        self.introspection = type(
            "Introspection", (), {"table_names": lambda self: sorted(existing_tables)}
        )()
        self.statements: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.schema_editor_calls = 0
        self.ops = type("Operations", (), {"quote_name": staticmethod(lambda name: f'"{name}"')})()

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.statements)

    def schema_editor(self) -> _FakeSchemaEditor:
        self.schema_editor_calls += 1
        return _FakeSchemaEditor(self.events)


def test_existing_tables_do_not_enter_schema_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the requested table already exists, setup and cleanup perform no DDL."""

    connection = _FakeConnection({"existing_model_table"})
    monkeypatch.setattr(isolated_schema_support, "connection", connection)

    with isolated_schema_support.isolated_schema((ExistingModel,)):
        pass

    assert connection.schema_editor_calls == 0
    assert connection.events == []
    assert connection.statements == [
        'DELETE FROM "existing_model_table"',
        'DELETE FROM "existing_model_table"',
    ]


def test_only_missing_models_are_created_and_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing tables get row cleanup only; schema_editor owns only missing tables."""

    connection = _FakeConnection({"existing_model_table"})
    monkeypatch.setattr(isolated_schema_support, "connection", connection)

    with isolated_schema_support.isolated_schema((ExistingModel, MissingModel)):
        pass

    assert connection.schema_editor_calls == 2
    assert connection.events == [
        ("create", "missing_model_table"),
        ("delete", "missing_model_table"),
    ]
    assert connection.statements == [
        'DELETE FROM "missing_model_table"',
        'DELETE FROM "existing_model_table"',
        'DELETE FROM "missing_model_table"',
        'DELETE FROM "existing_model_table"',
    ]


def test_existing_tables_can_defer_cleanup_to_pytest_db_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full-migration tables are not manually cleared inside the test fixture."""

    connection = _FakeConnection({"existing_model_table"})
    monkeypatch.setattr(isolated_schema_support, "connection", connection)

    with isolated_schema_support.isolated_schema(
        (ExistingModel,),
        clear_existing_rows=False,
    ):
        pass

    assert connection.schema_editor_calls == 0
    assert connection.events == []
    assert connection.statements == []


def test_partial_schema_defers_existing_rows_and_drops_only_owned_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial schema setup only creates and drops the table it owns."""

    connection = _FakeConnection({"existing_model_table"})
    monkeypatch.setattr(isolated_schema_support, "connection", connection)

    with isolated_schema_support.isolated_schema(
        (ExistingModel, MissingModel),
        clear_existing_rows=False,
    ):
        pass

    assert connection.schema_editor_calls == 2
    assert connection.events == [
        ("create", "missing_model_table"),
        ("delete", "missing_model_table"),
    ]
    assert connection.statements == []
