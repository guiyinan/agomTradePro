"""Pin the exact signed authorities on live-order materialization."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def install_pin_guard(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Forbid replacing a live order's source authority, including on historical rows."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            CREATE FUNCTION broker_order_protect_authority_pin() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF OLD.authority_pin IS DISTINCT FROM NEW.authority_pin OR
                   OLD.client_order_id IS DISTINCT FROM NEW.client_order_id THEN
                    RAISE EXCEPTION 'broker_order_authority_pin_immutable' USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END $$;
            CREATE TRIGGER broker_order_authority_pin_immutable BEFORE UPDATE
            ON broker_execution_live_order FOR EACH ROW EXECUTE FUNCTION broker_order_protect_authority_pin();
            ALTER TABLE broker_execution_live_order ENABLE ALWAYS TRIGGER broker_order_authority_pin_immutable;
        """)


def remove_pin_guard(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore the previous schema only while it contains no signed order pins."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "LOCK TABLE broker_execution_live_order IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    table = apps.get_model("broker_execution", "LiveOrderModel")
    if (
        table._default_manager.using(schema_editor.connection.alias)
        .exclude(authority_pin={})
        .exists()
    ):
        raise migrations.exceptions.IrreversibleError("preserve the existing order authority pins")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER broker_order_authority_pin_immutable ON broker_execution_live_order;
            DROP FUNCTION broker_order_protect_authority_pin();
        """)


class Migration(migrations.Migration):
    dependencies = [("broker_execution", "0013_order_execution_scope")]

    operations = [
        migrations.AddField(
            model_name="liveordermodel",
            name="authority_pin",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(install_pin_guard, remove_pin_guard),
    ]
