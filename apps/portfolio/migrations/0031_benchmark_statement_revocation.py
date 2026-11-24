"""Retain the authenticated withdrawal of an exact original statement."""

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def install_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reuse the valuation ledger's PostgreSQL immutable row and nonempty truncate guards."""
    db = schema_editor.connection
    model = apps.get_model("portfolio", "BenchmarkStatementRevocationModel")
    if db.vendor != "postgresql" or not router.allow_migrate_model(db.alias, model):
        return
    table = db.ops.quote_name(model._meta.db_table)
    with db.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION pf_bm_statement_fence() RETURNS trigger LANGUAGE plpgsql
            SET search_path=pg_catalog AS $guard$
            DECLARE locked_epoch uuid;
            BEGIN
                EXECUTE format(
                    'SELECT e.id FROM %1$I.portfolio_benchmark_valuation_epoch e
                     JOIN %1$I.portfolio_benchmark_daily_valuation d ON d.epoch_id=e.id
                     WHERE d.id=$1 AND d.original_hash=$2 AND e.owner_user_id=$3
                     FOR UPDATE OF e', TG_TABLE_SCHEMA
                ) INTO locked_epoch USING NEW.day_id, NEW.original_hash, NEW.owner_user_id;
                IF locked_epoch IS NULL THEN RAISE EXCEPTION 'unknown original statement or owner' USING ERRCODE='23514'; END IF;
                RETURN NEW;
            END;
            $guard$
        """)
        cursor.execute(
            f"CREATE TRIGGER pf_bm_statement_fence BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION pf_bm_statement_fence()"
        )
        cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER pf_bm_statement_fence")
        for name, operation in (
            ("pf_bm_statement_immutable", "UPDATE OR DELETE"),
            ("pf_bm_statement_truncate", "TRUNCATE"),
        ):
            level = "STATEMENT" if operation == "TRUNCATE" else "ROW"
            cursor.execute(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH {level} EXECUTE FUNCTION portfolio_benchmark_valuation_guard()"
            )
            cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {name}")


def remove_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Drop only triggers installed on the revocation ledger."""
    db = schema_editor.connection
    model = apps.get_model("portfolio", "BenchmarkStatementRevocationModel")
    if db.vendor == "postgresql" and router.allow_migrate_model(db.alias, model):
        table = db.ops.quote_name(model._meta.db_table)
        with db.cursor() as cursor:
            for name in (
                "pf_bm_statement_fence",
                "pf_bm_statement_immutable",
                "pf_bm_statement_truncate",
            ):
                cursor.execute(f"DROP TRIGGER {name} ON {table}")
            cursor.execute("DROP FUNCTION pf_bm_statement_fence()")


def refuse_nonempty_rollback(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Allow schema rollback only before the first authenticated custody withdrawal."""
    from apps.portfolio.migrations._benchmark_ledger_rollback import (
        refuse_nonempty_benchmark_rollback,
    )

    refuse_nonempty_benchmark_rollback(apps, schema_editor, ("BenchmarkStatementRevocationModel",))


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0030_benchmark_execution_approval")]
    operations = [
        migrations.CreateModel(
            name="BenchmarkStatementRevocationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("original_hash", models.CharField(max_length=64)),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("recorded_at", models.DateTimeField()),
                (
                    "day",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="portfolio.portfoliobenchmarkdailyvaluationmodel",
                    ),
                ),
            ],
            options={
                "db_table": "portfolio_benchmark_statement_revocation",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.RunPython(install_guards, remove_guards),
        migrations.RunPython(migrations.RunPython.noop, refuse_nonempty_rollback),
    ]
