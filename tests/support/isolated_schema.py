"""Reusable schema fixture for component tests with mixed Django settings.

Some component modules are also collected alongside the full project suite. In
that mode migrations have already created the concrete tables, so attempting
to create them again with ``schema_editor`` is an operational error. This
helper uses existing tables when present, clears only the tables under test,
and drops only tables it created itself.
"""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from django.db import connection, models

ModelType = type[models.Model]


def _unique_models(model_types: Iterable[ModelType]) -> tuple[ModelType, ...]:
    """Return model classes once, preserving their dependency order."""

    return tuple(dict.fromkeys(model_types))


def _clear_rows(model_types: tuple[ModelType, ...], existing_tables: set[str]) -> None:
    """Clear test-owned rows using SQL so append-only guards remain testable."""

    with connection.cursor() as cursor:
        for model_type in reversed(model_types):
            table_name = model_type._meta.db_table
            if table_name in existing_tables:
                cursor.execute(f"DELETE FROM {connection.ops.quote_name(table_name)}")


@contextmanager
def isolated_schema(
    model_types: Iterable[ModelType],
    *,
    before_cleanup: Callable[[], None] | None = None,
    clear_existing_rows: bool = True,
) -> Iterator[None]:
    """Create missing tables and clean only rows the caller owns.

    Set ``clear_existing_rows=False`` only when an enclosing pytest-django database
    fixture will roll back or flush the test. In that mode, existing tables are
    left untouched and this helper drops only tables it created.
    """

    ordered_models = _unique_models(model_types)
    existing_tables = set(connection.introspection.table_names())
    missing_models = tuple(
        model_type
        for model_type in ordered_models
        if model_type._meta.db_table not in existing_tables
    )

    if missing_models:
        with connection.schema_editor() as editor:
            for model_type in missing_models:
                editor.create_model(model_type)

    all_tables = existing_tables | {model_type._meta.db_table for model_type in missing_models}
    if clear_existing_rows:
        _clear_rows(ordered_models, all_tables)
    try:
        yield
    finally:
        if before_cleanup is not None:
            before_cleanup()
        if clear_existing_rows:
            _clear_rows(ordered_models, all_tables)
        if missing_models:
            with connection.schema_editor() as editor:
                for model_type in reversed(missing_models):
                    editor.delete_model(model_type)
