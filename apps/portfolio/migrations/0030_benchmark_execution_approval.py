"""Append-only, scope-fenced transitions for Portfolio benchmark approvals."""

from django.apps.registry import Apps
from django.db import migrations, models, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

from ._benchmark_ledger_rollback import refuse_nonempty_benchmark_rollback


def install_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Protect all SQL writers and serialize first insertions against exact current reads."""
    db = schema_editor.connection
    model = apps.get_model("portfolio", "BenchmarkApprovalEventModel")
    if db.vendor != "postgresql" or not router.allow_migrate_model(db.alias, model):
        return
    sql = db.ops.quote_name(model._meta.db_table)
    with db.cursor() as c:
        c.execute("""
            CREATE FUNCTION portfolio_benchmark_event_guard() RETURNS trigger LANGUAGE plpgsql
            SET search_path=pg_catalog AS $guard$
            DECLARE present boolean;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    PERFORM pg_advisory_xact_lock(hashtextextended('portfolio.benchmark.approval:' || NEW.scope_key,0));
                    RETURN NEW;
                END IF;
                IF TG_OP = 'TRUNCATE' THEN
                    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I)',TG_TABLE_SCHEMA,TG_TABLE_NAME) INTO STRICT present;
                    IF NOT present THEN RETURN NULL; END IF;
                END IF;
                RAISE EXCEPTION 'benchmark approvals are immutable' USING ERRCODE='23514';
            END;
            $guard$
        """)
        c.execute(
            f"CREATE TRIGGER pf_bm_event_guard BEFORE INSERT OR UPDATE OR DELETE ON {sql} FOR EACH ROW EXECUTE FUNCTION portfolio_benchmark_event_guard()"
        )
        c.execute(
            f"CREATE TRIGGER pf_bm_event_truncate BEFORE TRUNCATE ON {sql} FOR EACH STATEMENT EXECUTE FUNCTION portfolio_benchmark_event_guard()"
        )
        for trigger in ("pf_bm_event_guard", "pf_bm_event_truncate"):
            c.execute(f"ALTER TABLE {sql} ENABLE ALWAYS TRIGGER {trigger}")


def remove_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove only the local PostgreSQL row and statement guards."""
    db = schema_editor.connection
    model = apps.get_model("portfolio", "BenchmarkApprovalEventModel")
    if db.vendor == "postgresql" and router.allow_migrate_model(db.alias, model):
        table = db.ops.quote_name(model._meta.db_table)
        with db.cursor() as c:
            for trigger in ("pf_bm_event_guard", "pf_bm_event_truncate"):
                c.execute(f"DROP TRIGGER {trigger} ON {table}")
            c.execute("DROP FUNCTION portfolio_benchmark_event_guard()")


def preserve_issued_evidence(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Refuse the downgrade before removing a trigger or table containing issued evidence."""
    refuse_nonempty_benchmark_rollback(apps, schema_editor, ("BenchmarkApprovalEventModel",))


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("portfolio", "0029_policy_benchmark_daily_valuation")]
    operations = [
        migrations.CreateModel(
            name="BenchmarkApprovalEventModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("scope_key", models.CharField(max_length=64)),
                ("sequence", models.PositiveBigIntegerField()),
                ("request_id", models.UUIDField(db_index=True)),
                ("action", models.CharField(max_length=16)),
                ("account_namespace", models.CharField(max_length=192)),
                ("account_id", models.CharField(max_length=192)),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("tenant_id", models.CharField(max_length=192)),
                ("owner_id", models.CharField(max_length=192)),
                ("valuation_id", models.UUIDField()),
                ("valuation_version", models.PositiveBigIntegerField()),
                ("source_seal", models.CharField(max_length=64)),
                ("source_manifest", models.TextField()),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("actor_role", models.CharField(max_length=32)),
                ("recorded_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("previous_hash", models.CharField(max_length=64)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("signature", models.CharField(max_length=128)),
            ],
            options={
                "db_table": "portfolio_benchmark_approval_event",
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scope_key", "sequence"), name="pf_bm_scope_seq_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("request_id", "action"), name="pf_bm_request_action_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(action__in=["submitted", "approved", "revoked"]),
                        name="pf_bm_event_action_ck",
                    ),
                ],
            },
        ),
        migrations.RunPython(install_guards, remove_guards),
        migrations.RunPython(migrations.RunPython.noop, preserve_issued_evidence),
    ]
