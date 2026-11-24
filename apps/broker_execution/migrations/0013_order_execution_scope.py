"""Add an empty, one-way revocable ledger of human-signed order scopes."""

from django.apps.registry import Apps
from django.db import migrations, models, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError


def install_guard(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Prevent SQL mutation of signatures, reactivation and deletion on PostgreSQL."""
    model = apps.get_model("broker_execution", "BrokerOrderExecutionScopeModel")
    if schema_editor.connection.vendor == "postgresql" and router.allow_migrate_model(
        schema_editor.connection.alias, model
    ):
        schema_editor.execute(
            """
            CREATE FUNCTION broker_execution_protect_order_scope() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
            DECLARE present boolean;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I)',TG_TABLE_SCHEMA,TG_TABLE_NAME) INTO STRICT present;
                    IF NOT present THEN RETURN NULL; END IF;
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF OLD.revoked_at IS NULL AND NEW.revoked_at >= OLD.recorded_at
                       AND (to_jsonb(OLD) - 'revoked_at') = (to_jsonb(NEW) - 'revoked_at') THEN
                        RETURN NEW;
                    END IF;
                END IF;
                RAISE EXCEPTION 'broker order signature is immutable';
            END; $$;
            CREATE TRIGGER broker_execution_order_scope_guard BEFORE UPDATE OR DELETE ON broker_execution_order_scope
                FOR EACH ROW EXECUTE FUNCTION broker_execution_protect_order_scope();
            CREATE TRIGGER broker_execution_order_scope_truncate BEFORE TRUNCATE ON broker_execution_order_scope
                FOR EACH STATEMENT EXECUTE FUNCTION broker_execution_protect_order_scope();
            ALTER TABLE broker_execution_order_scope ENABLE ALWAYS TRIGGER broker_execution_order_scope_guard;
            ALTER TABLE broker_execution_order_scope ENABLE ALWAYS TRIGGER broker_execution_order_scope_truncate;
        """,
            params=None,
        )


def remove_guard(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove the native ledger guard before schema downgrade."""
    model = apps.get_model("broker_execution", "BrokerOrderExecutionScopeModel")
    if schema_editor.connection.vendor == "postgresql" and router.allow_migrate_model(
        schema_editor.connection.alias, model
    ):
        schema_editor.execute(
            "DROP TRIGGER broker_execution_order_scope_truncate ON broker_execution_order_scope; "
            "DROP TRIGGER broker_execution_order_scope_guard ON broker_execution_order_scope; "
            "DROP FUNCTION broker_execution_protect_order_scope()"
        )


def preserve_signed_history(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Refuse reverse DDL after the first mandate, including a revoked mandate."""
    db = schema_editor.connection
    model = apps.get_model("broker_execution", "BrokerOrderExecutionScopeModel")
    if not router.allow_migrate_model(db.alias, model):
        return
    if not db.in_atomic_block or db.vendor not in {"postgresql", "sqlite"}:
        raise IrreversibleError("Order scope reversal needs an atomic schema transaction.")
    table = db.ops.quote_name(model._meta.db_table)
    with db.cursor() as cursor:
        if db.vendor == "postgresql":
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise IrreversibleError("Order scope reversal requires READ COMMITTED.")
            cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
        else:
            cursor.execute(f"UPDATE {table} SET revoked_at=revoked_at WHERE 1=0")
        cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
        if cursor.fetchone() is not None:
            raise IrreversibleError("Cannot drop a nonempty order scope ledger.")


class Migration(migrations.Migration):
    dependencies = [("broker_execution", "0012_plan_order_binding")]
    operations = [
        migrations.CreateModel(
            name="BrokerOrderExecutionScopeModel",
            fields=[
                ("scope_id", models.UUIDField(primary_key=True, serialize=False)),
                ("client_order_id", models.UUIDField(db_index=True)),
                ("order_version", models.PositiveIntegerField()),
                ("account_id", models.PositiveIntegerField()),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("recorded_at", models.DateTimeField()),
                ("valid_until", models.DateTimeField()),
                ("benchmark_approval_id", models.UUIDField()),
                ("benchmark_approval_version", models.PositiveIntegerField()),
                ("benchmark_content_hash", models.CharField(max_length=64)),
                ("manifest", models.JSONField()),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("issuer_mac", models.CharField(max_length=64)),
                ("revoked_at", models.DateTimeField(null=True)),
            ],
            options={
                "db_table": "broker_execution_order_scope",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("client_order_id", "order_version"),
                        name="uq_broker_order_signed_version",
                    )
                ],
            },
        ),
        migrations.RunPython(install_guard, remove_guard),
        migrations.RunPython(migrations.RunPython.noop, preserve_signed_history),
    ]
