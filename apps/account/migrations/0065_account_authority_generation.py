"""Install the global transactional generation counter for authority sources."""

from __future__ import annotations

import re

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_SOURCE_TABLES: tuple[str, ...] = (
    "account_actor_authority_source_v3_ledger",
    "account_actor_authority_source_v3_root_lock",
    "account_allocated_physical_row_observation_v3_ledger",
    "account_auth_context_source_v3_anchor",
    "account_auth_context_source_v3_ledger",
    "account_owner_assignment_evidence_v5_ledger",
    "account_owner_assignment_provenance_receipt_v5_ledger",
    "account_owner_assignment_subject_v5_ledger",
    "account_owner_tenant_authority_v3_ledger",
    "account_owner_tenant_authority_v3_revocation_ledger",
    "account_physical_row_observation_v2_ledger",
    "account_rbac_authority_source_v3_anchor",
    "account_rbac_authority_source_v3_ledger",
    "account_single_owner_authority_policy_v1",
    "account_user_authority_source_v3_anchor",
    "account_user_authority_source_v3_ledger",
    "canonical_account_creation_allocation_ledger",
    "canonical_account_creation_binding_ledger",
    "canonical_account_creation_binding_v2_ledger",
    "canonical_account_creation_consumption_claim_ledger",
    "canonical_account_ownership_reobservation_v1_ledger",
    "simulated_account_row_source_v2_ledger",
)
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_GENERATION_TABLE = "account_authority_generation"
_DML_TRIGGER = "acct_auth_gen_stmt"
_TRUNCATE_TRIGGER = "acct_auth_gen_truncate"
_FUNCTION = "account_authority_generation_bump"


def seed_generation_row(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Create the required singleton row on PostgreSQL and SQLite."""

    generation_model = apps.get_model("account", "AccountAuthorityGenerationModel")
    generation_model._default_manager.using(schema_editor.connection.alias).get_or_create(
        singleton=1,
        defaults={"generation": 0},
    )


def install_source_triggers(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Install statement-level source triggers only on PostgreSQL."""

    del apps
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    _require_source_tables(connection)
    generation_table = _qualified_name(connection, _GENERATION_TABLE)
    function_name = _qualified_name(connection, _FUNCTION)
    with connection.cursor() as cursor:
        # The migration role is not a reliable identifier for the deployed
        # runtime role, so this migration intentionally makes no blanket
        # REVOKE. A role with direct UPDATE privilege on the singleton could
        # bypass monotonic trigger updates; tightening that ACL needs the
        # production role mapping and remains an explicit deployment limit.
        cursor.execute(f"""
            CREATE FUNCTION {function_name}() RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $account_authority_generation$
            BEGIN
                UPDATE {generation_table}
                   SET generation = generation + 1
                 WHERE singleton = 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'account authority generation singleton row is missing'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NULL;
            END;
            $account_authority_generation$
            """)
        for table_name in _SOURCE_TABLES:
            table = _qualified_name(connection, table_name)
            dml_trigger = connection.ops.quote_name(_DML_TRIGGER)
            truncate_trigger = connection.ops.quote_name(_TRUNCATE_TRIGGER)
            cursor.execute(f"""
                CREATE TRIGGER {dml_trigger}
                BEFORE INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION {function_name}()
                """)
            cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {dml_trigger}")
            cursor.execute(f"""
                CREATE TRIGGER {truncate_trigger}
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION {function_name}()
                """)
            cursor.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {truncate_trigger}")
    _validate_source_triggers(connection)


def remove_source_triggers(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove only this migration's exact triggers and function on PostgreSQL."""

    del apps
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    function_name = _qualified_name(connection, _FUNCTION)
    with connection.cursor() as cursor:
        for table_name in _SOURCE_TABLES:
            table = _qualified_name(connection, table_name)
            cursor.execute(f"DROP TRIGGER {connection.ops.quote_name(_DML_TRIGGER)} ON {table}")
            cursor.execute(
                f"DROP TRIGGER {connection.ops.quote_name(_TRUNCATE_TRIGGER)} ON {table}"
            )
        cursor.execute(f"DROP FUNCTION {function_name}()")


def _require_source_tables(connection: BaseDatabaseWrapper) -> None:
    """Reject installation unless all 22 fixed public source relations exist."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
              FROM pg_catalog.pg_class AS c
              JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = %s
               AND c.relname::text = ANY(%s::text[])
               AND c.relkind = 'r'
            """,
            ["public", list(_SOURCE_TABLES)],
        )
        actual_tables = {row[0] for row in cursor.fetchall()}
    if actual_tables != set(_SOURCE_TABLES):
        missing = set(_SOURCE_TABLES) - actual_tables
        raise RuntimeError(
            "account authority generation migration requires all 22 public source tables; "
            f"missing {len(missing)} table(s)"
        )


def _validate_source_triggers(connection: BaseDatabaseWrapper) -> None:
    """Require all 44 exact BEFORE statement triggers to be enabled ALWAYS."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, t.tgname, t.tgenabled, t.tgtype,
                   p.proname, p.prosecdef, p.proconfig
              FROM pg_catalog.pg_class AS c
              JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
              JOIN pg_catalog.pg_trigger AS t
                ON t.tgrelid = c.oid
               AND NOT t.tgisinternal
               AND t.tgname = ANY(%s::text[])
              JOIN pg_catalog.pg_proc AS p ON p.oid = t.tgfoid
             WHERE n.nspname = %s
               AND c.relname::text = ANY(%s::text[])
               AND c.relkind = 'r'
            """,
            [
                [_DML_TRIGGER, _TRUNCATE_TRIGGER],
                "public",
                list(_SOURCE_TABLES),
            ],
        )
        rows = cursor.fetchall()
    if len(rows) != 44:
        raise RuntimeError("account authority generation migration did not install 44 triggers")
    triggers_by_table: dict[str, set[str]] = {table: set() for table in _SOURCE_TABLES}
    for row in rows:
        table_name, trigger_name, enabled, trigger_type, function_name, security_definer, config = (
            row
        )
        if (
            type(table_name) is not str
            or table_name not in triggers_by_table
            or type(trigger_name) is not str
            or type(enabled) is not str
            or type(trigger_type) is not int
            or type(function_name) is not str
            or type(security_definer) is not bool
            or not isinstance(config, list)
            or any(type(value) is not str for value in config)
        ):
            raise RuntimeError("account authority generation trigger catalog row is invalid")
        expected_type = {
            _DML_TRIGGER: 30,
            _TRUNCATE_TRIGGER: 34,
        }.get(trigger_name)
        if (
            expected_type is None
            or trigger_type != expected_type
            or enabled != "A"
            or function_name != _FUNCTION
            or not security_definer
            or "search_path=pg_catalog, public" not in config
        ):
            raise RuntimeError("account authority generation trigger is not trusted")
        triggers_by_table[table_name].add(trigger_name)
    required_triggers = {_DML_TRIGGER, _TRUNCATE_TRIGGER}
    if any(trigger_names != required_triggers for trigger_names in triggers_by_table.values()):
        raise RuntimeError("account authority generation trigger coverage is incomplete")


def _qualified_name(connection: BaseDatabaseWrapper, name: str) -> str:
    """Quote validated public-schema identifiers used by migration SQL."""

    if _IDENTIFIER.fullmatch(name) is None:
        raise RuntimeError("account authority generation identifier is invalid")
    quote = connection.ops.quote_name
    return f"{quote('public')}.{quote(name)}"


class Migration(migrations.Migration):
    dependencies = [
        (
            "account",
            "0064_remove_accountownerassignmentevidencev5model_acct_asg_v5_account_uq_and_more",
        ),
        ("simulated_trading", "0023_simulated_account_row_source_v2_ledger"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountAuthorityGenerationModel",
            fields=[
                (
                    "singleton",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("generation", models.PositiveBigIntegerField(default=0)),
            ],
            options={
                "db_table": "account_authority_generation",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("singleton", 1)), name="acct_auth_gen_singleton_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("generation__gte", 0)),
                        name="acct_auth_gen_nonnegative_ck",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_generation_row, migrations.RunPython.noop),
        migrations.RunPython(install_source_triggers, remove_source_triggers),
    ]
