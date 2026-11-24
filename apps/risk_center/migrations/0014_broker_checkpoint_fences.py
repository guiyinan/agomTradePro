"""Serialize checkpoint reads with writes to the same PostgreSQL Risk ledger scope."""

from django.apps.registry import Apps
from django.db import migrations, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_LEDGER_MODELS = (
    ("BrokerOrderExecutionPolicySourceModel", "policy"),
    ("BrokerOrderExecutionPolicyActivationModel", "policy"),
    ("BrokerOrderRiskAuthorizationSubjectModel", "authorization"),
    ("BrokerOrderRiskAuthorizationRecordModel", "authorization"),
)
_TRIGGER = "risk_broker_checkpoint_fence"
_KEY = "risk_broker_checkpoint_scope"
_GUARD = "risk_broker_checkpoint_writer"


def install_fences(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Fence all DML, including historical models and non-ORM insertions."""
    db = schema_editor.connection
    if db.vendor != "postgresql":
        return
    quote = db.ops.quote_name
    with db.cursor() as cursor:
        cursor.execute(f"""
            CREATE FUNCTION {_KEY}(scope text, account_id bigint, order_id text)
            RETURNS bigint LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
            AS 'SELECT pg_catalog.hashtextextended(
                ''risk.broker.checkpoint.v1:'' || scope || '':'' || account_id::text || '':'' || order_id, 0)'
        """)
        cursor.execute(f"""
            CREATE FUNCTION {_GUARD}() RETURNS trigger LANGUAGE plpgsql AS $guard$
            DECLARE
                old_key bigint;
                new_key bigint;
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    old_key := {_KEY}(TG_ARGV[0], OLD.account_id,
                        CASE WHEN TG_ARGV[0] = 'policy' THEN '' ELSE to_jsonb(OLD)->>'order_id' END);
                END IF;
                IF TG_OP <> 'DELETE' THEN
                    new_key := {_KEY}(TG_ARGV[0], NEW.account_id,
                        CASE WHEN TG_ARGV[0] = 'policy' THEN '' ELSE to_jsonb(NEW)->>'order_id' END);
                END IF;
                PERFORM pg_catalog.pg_advisory_xact_lock(k)
                  FROM (SELECT DISTINCT k FROM unnest(ARRAY[old_key, new_key]) AS x(k)
                        WHERE k IS NOT NULL ORDER BY k) AS keys;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $guard$
        """)
        for model_name, scope in _LEDGER_MODELS:
            model = apps.get_model("risk_center", model_name)
            if router.allow_migrate_model(db.alias, model):
                table = quote(model._meta.db_table)
                cursor.execute(f"""
                    CREATE TRIGGER {_TRIGGER} BEFORE INSERT OR UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION {_GUARD}('{scope}')
                """)
                cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {_TRIGGER}")


def remove_fences(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove only this migration's local triggers and lock-key functions."""
    db = schema_editor.connection
    if db.vendor != "postgresql":
        return
    with db.cursor() as cursor:
        for model_name, _ in _LEDGER_MODELS:
            model = apps.get_model("risk_center", model_name)
            if router.allow_migrate_model(db.alias, model):
                table = db.ops.quote_name(model._meta.db_table)
                cursor.execute(f"DROP TRIGGER {_TRIGGER} ON {table}")
        cursor.execute(f"DROP FUNCTION {_GUARD}()")
        cursor.execute(f"DROP FUNCTION {_KEY}(text, bigint, text)")


class Migration(migrations.Migration):
    dependencies = [("risk_center", "0013_scenario_run_evidence_snapshots")]
    operations = [migrations.RunPython(install_fences, remove_fences)]
