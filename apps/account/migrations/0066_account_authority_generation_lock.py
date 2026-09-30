"""Install an owner-owned least-privilege lock wrapper for authority generation."""

from __future__ import annotations

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

_SCHEMA = "public"
_GENERATION_TABLE = "account_authority_generation"
_LOCK_FUNCTION = "account_authority_generation_lock"
_BUMP_FUNCTION = "account_authority_generation_bump"
_LOCK_FUNCTION_SEARCH_PATH = "search_path=pg_catalog"


def install_generation_lock_function(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Create the lock wrapper and revoke PUBLIC execution on both helpers.

    A migrator that can SET ROLE to the table owner uses that role to create the
    wrapper. This supports deployments where only the NOLOGIN owner has CREATE
    on ``public``. When no owner role split exists, the migration can still run
    as the relation owner or a role with schema CREATE, but the runtime verifier
    rejects the resulting ACL unless its stricter ownership contract is met.
    """

    del apps
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    quote = connection.ops.quote_name
    generation_table = f"{quote(_SCHEMA)}.{quote(_GENERATION_TABLE)}"
    lock_function = f"{quote(_SCHEMA)}.{quote(_LOCK_FUNCTION)}"
    _harden_bump_function(connection)

    owner_name, owner_can_create, may_set_owner, is_superuser = _generation_owner_state(connection)
    temporary_create = is_superuser and not owner_can_create
    if temporary_create:
        with connection.cursor() as cursor:
            cursor.execute(f"GRANT CREATE ON SCHEMA {quote(_SCHEMA)} TO {quote(owner_name)}")

    if (owner_can_create or temporary_create) and may_set_owner:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            current_role_row = cursor.fetchone()
            if (
                current_role_row is None
                or len(current_role_row) != 1
                or type(current_role_row[0]) is not str
            ):
                raise RuntimeError("account authority migration role identity is invalid")
            current_role = current_role_row[0]
            switched_role = current_role != owner_name
            if switched_role:
                cursor.execute(f"SET LOCAL ROLE {quote(owner_name)}")
            cursor.execute(f"""
                CREATE FUNCTION {lock_function}() RETURNS bigint
                LANGUAGE plpgsql
                SECURITY DEFINER
                SET search_path = pg_catalog
                AS $account_authority_generation_lock$
                DECLARE
                    locked_generation bigint;
                BEGIN
                    SELECT generation
                      INTO locked_generation
                      FROM {generation_table}
                     WHERE singleton = 1
                       FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'account authority generation singleton row is missing'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN locked_generation;
                END;
                $account_authority_generation_lock$
            """)
            cursor.execute(f"REVOKE ALL ON FUNCTION {lock_function}() FROM PUBLIC")
            if switched_role:
                cursor.execute(f"SET LOCAL ROLE {quote(current_role)}")
    else:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.has_schema_privilege(current_user, %s, 'CREATE')",
                [_SCHEMA],
            )
            current_role_can_create = cursor.fetchone()
            if current_role_can_create != (True,):
                raise RuntimeError(
                    "account authority lock migration requires SET ROLE to the "
                    "generation owner or CREATE on public"
                )
            cursor.execute(f"""
                CREATE FUNCTION {lock_function}() RETURNS bigint
                LANGUAGE plpgsql
                SECURITY DEFINER
                SET search_path = pg_catalog
                AS $account_authority_generation_lock$
                DECLARE
                    locked_generation bigint;
                BEGIN
                    SELECT generation
                      INTO locked_generation
                      FROM {generation_table}
                     WHERE singleton = 1
                       FOR SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'account authority generation singleton row is missing'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN locked_generation;
                END;
                $account_authority_generation_lock$
                """)
            cursor.execute(f"REVOKE ALL ON FUNCTION {lock_function}() FROM PUBLIC")

    if temporary_create:
        with connection.cursor() as cursor:
            cursor.execute(f"REVOKE CREATE ON SCHEMA {quote(_SCHEMA)} FROM {quote(owner_name)}")


def remove_generation_lock_function(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Drop the wrapper only when the reverse migrator can become its owner."""

    del apps
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    quote = connection.ops.quote_name
    lock_function = f"{quote(_SCHEMA)}.{quote(_LOCK_FUNCTION)}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT function_owner.rolname,
                   current_user,
                   caller_role.rolsuper,
                   pg_catalog.pg_has_role(
                       session_user, lock_function.proowner, 'SET'
                   )
              FROM pg_catalog.pg_proc AS lock_function
              JOIN pg_catalog.pg_roles AS function_owner
                ON function_owner.oid = lock_function.proowner
              JOIN pg_catalog.pg_roles AS caller_role
                ON caller_role.rolname = current_user
             WHERE lock_function.oid = pg_catalog.to_regprocedure(%s)
            """,
            [f"{_SCHEMA}.{_LOCK_FUNCTION}()"],
        )
        owner_row = cursor.fetchone()
        if owner_row is None:
            raise RuntimeError("account authority generation lock wrapper is unavailable")
        owner_name, current_name, current_is_superuser, can_set_owner = owner_row
        if (
            type(owner_name) is not str
            or type(current_name) is not str
            or type(current_is_superuser) is not bool
            or type(can_set_owner) is not bool
        ):
            raise RuntimeError("account authority generation lock ownership is invalid")
        if not (current_is_superuser or can_set_owner or current_name == owner_name):
            raise RuntimeError(
                "cannot reverse account authority generation lock without function-owner role"
            )
        switched_role = current_name != owner_name
        if switched_role:
            cursor.execute(f"SET LOCAL ROLE {quote(owner_name)}")
        cursor.execute(f"DROP FUNCTION {lock_function}()")
        if switched_role:
            cursor.execute(f"SET LOCAL ROLE {quote(current_name)}")


def _generation_owner_state(
    connection: BaseDatabaseWrapper,
) -> tuple[str, bool, bool, bool]:
    """Return the generation owner and whether this session can safely assume it."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT owner_role.rolname,
                   owner_role.oid,
                   pg_catalog.has_schema_privilege(
                       owner_role.oid, namespace.oid, 'CREATE'
                   ),
                   pg_catalog.pg_has_role(session_user, owner_role.oid, 'SET'),
                   session_role.rolsuper
              FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
              JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = relation.relowner
              JOIN pg_catalog.pg_roles AS session_role
                ON session_role.rolname = session_user
             WHERE namespace.nspname = %s
               AND relation.relname = %s
               AND relation.relkind = 'r'
            """,
            [_SCHEMA, _GENERATION_TABLE],
        )
        owner_row = cursor.fetchone()
        if owner_row is None:
            raise RuntimeError("account authority generation table is unavailable")
        owner_name, owner_oid, owner_can_create, can_set_owner, is_superuser = owner_row
        if (
            type(owner_name) is not str
            or type(owner_oid) is not int
            or type(owner_can_create) is not bool
            or type(can_set_owner) is not bool
            or type(is_superuser) is not bool
        ):
            raise RuntimeError("account authority generation ownership catalog is invalid")
        cursor.execute(
            "SELECT pg_catalog.pg_has_role(current_user, %s, 'SET')",
            [owner_oid],
        )
        current_role_row = cursor.fetchone()
        if current_role_row is None or type(current_role_row[0]) is not bool:
            raise RuntimeError("account authority generation owner SET status is invalid")
        current_is_owner = current_role_row[0]
    return owner_name, owner_can_create, can_set_owner or current_is_owner, is_superuser


def _harden_bump_function(connection: BaseDatabaseWrapper) -> None:
    """Revoke PUBLIC and transfer the trigger helper when the migrator can do so."""

    quote = connection.ops.quote_name
    bump_function = f"{quote(_SCHEMA)}.{quote(_BUMP_FUNCTION)}"
    owner_name, owner_can_create, may_set_owner, is_superuser = _generation_owner_state(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT function_owner.rolname,
                   current_user,
                   pg_catalog.pg_has_role(
                       session_user, function_owner.oid, 'SET'
                   )
              FROM pg_catalog.pg_proc AS function
              JOIN pg_catalog.pg_roles AS function_owner
                ON function_owner.oid = function.proowner
             WHERE function.oid = pg_catalog.to_regprocedure(%s)
            """,
            [f"{_SCHEMA}.{_BUMP_FUNCTION}()"],
        )
        function_row = cursor.fetchone()
        if function_row is None:
            raise RuntimeError("account authority generation bump function is unavailable")
        function_owner, current_name, may_set_function_owner = function_row
        if (
            type(function_owner) is not str
            or type(current_name) is not str
            or type(may_set_function_owner) is not bool
        ):
            raise RuntimeError("account authority generation bump ownership is invalid")

        can_manage_bump = is_superuser or current_name == function_owner or may_set_function_owner
        if not can_manage_bump:
            raise RuntimeError(
                "cannot revoke PUBLIC execution from account authority generation bump function"
            )

        temporary_create = is_superuser and not owner_can_create
        if temporary_create:
            cursor.execute(f"GRANT CREATE ON SCHEMA {quote(_SCHEMA)} TO {quote(owner_name)}")
        if is_superuser:
            cursor.execute(f"REVOKE ALL ON FUNCTION {bump_function}() FROM PUBLIC")
            cursor.execute(f"ALTER FUNCTION {bump_function}() SET search_path = pg_catalog")
            if function_owner != owner_name:
                cursor.execute(f"ALTER FUNCTION {bump_function}() OWNER TO {quote(owner_name)}")
        else:
            switched_role = current_name != function_owner
            if switched_role:
                cursor.execute(f"SET LOCAL ROLE {quote(function_owner)}")
            cursor.execute(f"REVOKE ALL ON FUNCTION {bump_function}() FROM PUBLIC")
            cursor.execute(f"ALTER FUNCTION {bump_function}() SET search_path = pg_catalog")
            if function_owner != owner_name and owner_can_create and may_set_owner:
                cursor.execute(f"ALTER FUNCTION {bump_function}() OWNER TO {quote(owner_name)}")
            if switched_role:
                cursor.execute(f"SET LOCAL ROLE {quote(current_name)}")
        if temporary_create:
            cursor.execute(f"REVOKE CREATE ON SCHEMA {quote(_SCHEMA)} FROM {quote(owner_name)}")


class Migration(migrations.Migration):
    dependencies = [
        (
            "account",
            "0065_account_authority_generation",
        ),
    ]

    operations = [
        migrations.RunPython(
            install_generation_lock_function,
            remove_generation_lock_function,
        ),
    ]
