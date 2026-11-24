from uuid import uuid4

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

from ._benchmark_ledger_rollback import refuse_nonempty_benchmark_rollback


def install_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reject edits, deletes and destructive truncation on the immutable issued facts."""
    db = schema_editor.connection
    if db.vendor != "postgresql" or not router.allow_migrate_model(
        db.alias, apps.get_model("portfolio", "PortfolioBenchmarkDailyValuationModel")
    ):
        return
    with db.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION portfolio_benchmark_valuation_guard() RETURNS trigger LANGUAGE plpgsql
            SET search_path=pg_catalog AS $body$
            DECLARE present boolean;
            BEGIN
                IF TG_OP='TRUNCATE' THEN
                    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I)',TG_TABLE_SCHEMA,TG_TABLE_NAME) INTO STRICT present;
                    IF NOT present THEN RETURN NULL; END IF;
                END IF;
                RAISE EXCEPTION 'issued valuation evidence is immutable' USING ERRCODE='23514';
            END;
            $body$
        """)
        for table in ("portfolio_benchmark_daily_valuation", "portfolio_benchmark_valuation_epoch"):
            cursor.execute(
                f"CREATE TRIGGER pf_bench_valuation_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION portfolio_benchmark_valuation_guard()"
            )
            cursor.execute(
                f"CREATE TRIGGER pf_bench_valuation_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION portfolio_benchmark_valuation_guard()"
            )
            for trigger in ("pf_bench_valuation_immutable", "pf_bench_valuation_truncate"):
                cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger}")


def remove_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove precisely the valuation triggers during an explicit migration reversal."""
    db = schema_editor.connection
    if db.vendor != "postgresql" or not router.allow_migrate_model(
        db.alias, apps.get_model("portfolio", "PortfolioBenchmarkDailyValuationModel")
    ):
        return
    with db.cursor() as cursor:
        for table in ("portfolio_benchmark_daily_valuation", "portfolio_benchmark_valuation_epoch"):
            for trigger in ("pf_bench_valuation_immutable", "pf_bench_valuation_truncate"):
                cursor.execute(f"DROP TRIGGER {trigger} ON {table}")
        cursor.execute("DROP FUNCTION portfolio_benchmark_valuation_guard()")


def preserve_issued_evidence(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Refuse the downgrade before removing a trigger or table containing issued evidence."""
    refuse_nonempty_benchmark_rollback(
        apps,
        schema_editor,
        ("PortfolioBenchmarkDailyValuationModel", "PortfolioBenchmarkValuationEpochModel"),
    )


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("portfolio", "0028_transition_plan_revision_family")]
    operations = [
        migrations.CreateModel(
            name="PortfolioBenchmarkValuationEpochModel",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("account_namespace", models.CharField(max_length=128)),
                ("account_id", models.CharField(max_length=128)),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("sequence", models.PositiveIntegerField()),
                ("scope_hash", models.CharField(max_length=64)),
                ("definition_id", models.CharField(max_length=192)),
                ("policy_id", models.CharField(max_length=192)),
                ("configuration_hash", models.CharField(max_length=64)),
                ("started_at", models.DateTimeField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
            ],
            options={
                "db_table": "portfolio_benchmark_valuation_epoch",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account_namespace", "account_id", "sequence"),
                        name="pf_bench_val_epoch_seq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PortfolioBenchmarkDailyValuationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("observation_date", models.DateField()),
                ("observed_at", models.DateTimeField()),
                ("recorded_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("snapshot_id", models.PositiveBigIntegerField()),
                ("reconciliation_hash", models.CharField(max_length=64)),
                ("original_statement", models.BinaryField()),
                ("original_hash", models.CharField(max_length=64)),
                ("fixing_hash", models.CharField(max_length=64)),
                ("predecessor_hash", models.CharField(max_length=64, blank=True)),
                ("balance", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                (
                    "epoch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="closes",
                        to="portfolio.portfoliobenchmarkvaluationepochmodel",
                    ),
                ),
            ],
            options={
                "db_table": "portfolio_benchmark_daily_valuation",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(fields=("epoch", "version"), name="pf_bench_day_seq"),
                    models.UniqueConstraint(
                        fields=("epoch", "observation_date"), name="pf_bench_day_date"
                    ),
                ],
            },
        ),
        migrations.RunPython(install_guards, remove_guards),
        migrations.RunPython(migrations.RunPython.noop, preserve_issued_evidence),
    ]
