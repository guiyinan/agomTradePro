"""Immutable reverse-migration checks shared by the benchmark evidence ledgers."""

from django.apps.registry import Apps
from django.db import router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError


def refuse_nonempty_benchmark_rollback(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor, model_names: tuple[str, ...]
) -> None:
    """Hold the write fence through DDL and preserve every existing evidence row."""
    db = schema_editor.connection
    tables = []
    for name in model_names:
        model = apps.get_model("portfolio", name)
        if router.allow_migrate_model(db.alias, model):
            tables.append(db.ops.quote_name(model._meta.db_table))
    if not tables:
        return
    if not db.in_atomic_block or db.vendor not in {"postgresql", "sqlite"}:
        raise IrreversibleError(
            "Benchmark reversal requires an atomic PostgreSQL or SQLite migration."
        )
    with db.cursor() as cursor:
        if db.vendor == "postgresql":
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise IrreversibleError(
                    "Benchmark reversal requires a current READ COMMITTED snapshot."
                )
            cursor.execute(f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE")
        else:
            # Promote the SQLite transaction to a writer before inspecting any table.
            cursor.execute(f"UPDATE {tables[0]} SET id = id WHERE 1 = 0")
        for table in tables:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
            if cursor.fetchone() is not None:
                raise IrreversibleError(
                    f"Cannot reverse nonempty Portfolio benchmark ledger {table}."
                )
