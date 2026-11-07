"""Protect existing V1 provenance receipts from direct PostgreSQL row mutation."""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_TABLE = '"public"."account_owner_assignment_provenance_receipt_ledger"'
_GUARD = '"public"."account_provenance_receipt_v1_immutable"'
_TRIGGER = '"acct_prov_receipt_v1_immutable"'


def install_receipt_guard(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reject direct changes to existing rows while preserving inserts and reads."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"""
        CREATE FUNCTION {_GUARD}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $receipt_guard$
        BEGIN
            RAISE EXCEPTION 'V1 provenance receipts are append-only'
                USING ERRCODE = '23514';
        END;
        $receipt_guard$
        """)
    schema_editor.execute(f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_GUARD}()
        """)
    schema_editor.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TRIGGER}")


def remove_receipt_guard(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reverse only the guard DDL and leave all receipt rows intact."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP TRIGGER {_TRIGGER} ON {_TABLE}")
    schema_editor.execute(f"DROP FUNCTION {_GUARD}()")


class Migration(migrations.Migration):
    dependencies = [("account", "0068_broker_trade_reconciliation")]
    operations = [
        migrations.RunPython(
            install_receipt_guard,
            remove_receipt_guard,
            hints={"model_name": "accountownerassignmentprovenancereceiptmodel"},
        ),
    ]
