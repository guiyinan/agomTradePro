"""PostgreSQL runtime-role ACL checks for Account authority generation fencing."""

from typing import cast

from django.db import DatabaseError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.infrastructure.account_authority_generation_errors import (
    AccountAuthorityGenerationCoverageError,
)


def verify_account_authority_generation_runtime_acl_contract(
    *,
    connection: BaseDatabaseWrapper,
    source_tables: tuple[str, ...],
    lock_function_name: str,
    function_search_path: str,
    lock_function_search_path: str,
) -> None:
    """Require the active role to use the owner-owned wrapper with read-only table access."""

    if connection.vendor != "postgresql":
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation ACL verification requires PostgreSQL"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_owner.rolname,
                       function_owner.rolname,
                       bump_function.proowner = generation_table.relowner,
                       bump_function.prosecdef,
                       bump_function.proconfig,
                       EXISTS (
                           SELECT 1
                             FROM pg_catalog.aclexplode(
                                 COALESCE(
                                     bump_function.proacl,
                                     pg_catalog.acldefault('f', bump_function.proowner)
                                 )
                             ) AS acl
                            WHERE acl.grantee = 0
                              AND acl.privilege_type = 'EXECUTE'
                       ),
                       caller_role.rolsuper,
                       session_role.rolsuper,
                       pg_catalog.pg_has_role(
                           current_user, generation_table.relowner, 'SET'
                       ),
                       pg_catalog.pg_has_role(
                           current_user, generation_table.relowner, 'MEMBER'
                       ),
                       pg_catalog.pg_has_role(
                           session_user, generation_table.relowner, 'SET'
                       ),
                       pg_catalog.pg_has_role(
                           session_user, generation_table.relowner, 'MEMBER'
                       ),
                       pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
                       pg_catalog.has_schema_privilege(session_user, 'public', 'CREATE'),
                       table_owner.rolcanlogin,
                       table_owner.rolsuper,
                       lock_function.prosecdef,
                       lock_function.proconfig,
                       lock_function.pronargs,
                       lock_function.prorettype = 'pg_catalog.int8'::pg_catalog.regtype,
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'SELECT'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'INSERT'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'UPDATE'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'DELETE'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'TRUNCATE'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'REFERENCES'
                       ),
                       pg_catalog.has_table_privilege(
                           current_user, generation_table.oid, 'TRIGGER'
                       ),
                       pg_catalog.has_function_privilege(
                           current_user, lock_function.oid, 'EXECUTE'
                       ),
                       pg_catalog.has_function_privilege(
                           current_user, bump_function.oid, 'EXECUTE'
                       ),
                       EXISTS (
                           SELECT 1
                             FROM pg_catalog.aclexplode(
                                 COALESCE(
                                     lock_function.proacl,
                                     pg_catalog.acldefault('f', lock_function.proowner)
                                 )
                             ) AS acl
                            WHERE acl.grantee = 0
                              AND acl.privilege_type = 'EXECUTE'
                       )
                  FROM pg_catalog.pg_class AS generation_table
                  JOIN pg_catalog.pg_namespace AS generation_namespace
                    ON generation_namespace.oid = generation_table.relnamespace
                  JOIN pg_catalog.pg_roles AS table_owner
                    ON table_owner.oid = generation_table.relowner
                  JOIN pg_catalog.pg_roles AS caller_role
                    ON caller_role.rolname = current_user
                  JOIN pg_catalog.pg_roles AS session_role
                    ON session_role.rolname = session_user
                  CROSS JOIN pg_catalog.pg_proc AS bump_function
                  CROSS JOIN pg_catalog.pg_proc AS lock_function
                  JOIN pg_catalog.pg_roles AS function_owner
                    ON function_owner.oid = lock_function.proowner
                 WHERE generation_namespace.nspname = 'public'
                   AND generation_table.relname = 'account_authority_generation'
                   AND generation_table.relkind = 'r'
                   AND bump_function.oid = pg_catalog.to_regprocedure(
                       'public.account_authority_generation_bump()'
                   )
                   AND lock_function.oid = pg_catalog.to_regprocedure(%s)
                """,
                [f"public.{lock_function_name}()"],
            )
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation runtime ACL query failed"
        ) from error

    if row is None or len(row) != 30:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation lock wrapper is missing"
        )
    (
        table_owner,
        function_owner,
        bump_owner_matches,
        bump_security_definer,
        bump_config,
        bump_public_can_execute,
        caller_is_superuser,
        session_is_superuser,
        caller_can_set_owner,
        caller_is_member_of_owner,
        session_can_set_owner,
        session_is_member_of_owner,
        caller_can_create_in_public,
        session_can_create_in_public,
        table_owner_can_login,
        table_owner_is_superuser,
        security_definer,
        config,
        argument_count,
        returns_bigint,
        can_select,
        can_insert,
        can_update,
        can_delete,
        can_truncate,
        can_reference,
        can_trigger,
        can_execute,
        can_execute_bump,
        public_can_execute,
    ) = row
    if (
        type(table_owner) is not str
        or type(function_owner) is not str
        or type(bump_owner_matches) is not bool
        or type(bump_security_definer) is not bool
        or not isinstance(bump_config, list)
        or any(type(value) is not str for value in bump_config)
        or type(bump_public_can_execute) is not bool
        or any(
            type(value) is not bool
            for value in (
                caller_is_superuser,
                session_is_superuser,
                caller_can_set_owner,
                caller_is_member_of_owner,
                session_can_set_owner,
                session_is_member_of_owner,
                caller_can_create_in_public,
                session_can_create_in_public,
                table_owner_can_login,
                table_owner_is_superuser,
                security_definer,
            )
        )
        or not isinstance(config, list)
        or any(type(value) is not str for value in config)
        or type(argument_count) is not int
        or type(returns_bigint) is not bool
        or any(
            type(value) is not bool
            for value in (
                can_select,
                can_insert,
                can_update,
                can_delete,
                can_truncate,
                can_reference,
                can_trigger,
                can_execute,
                can_execute_bump,
                public_can_execute,
            )
        )
    ):
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation runtime ACL catalog row is malformed"
        )
    if (
        function_owner != table_owner
        or not bump_owner_matches
        or not bump_security_definer
        or bump_config != [function_search_path]
        or bump_public_can_execute
        or caller_is_superuser
        or session_is_superuser
        or caller_can_set_owner
        or caller_is_member_of_owner
        or session_can_set_owner
        or session_is_member_of_owner
        or caller_can_create_in_public
        or session_can_create_in_public
        or table_owner_can_login
        or table_owner_is_superuser
        or not security_definer
        or config != [lock_function_search_path]
        or argument_count != 0
        or not returns_bigint
        or not can_select
        or any(
            (
                can_insert,
                can_update,
                can_delete,
                can_truncate,
                can_reference,
                can_trigger,
            )
        )
        or not can_execute
        or can_execute_bump
        or public_can_execute
    ):
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation runtime ACL contract is not satisfied"
        )
    _verify_account_authority_role_closure(connection, source_tables)


def _verify_account_authority_role_closure(
    connection: BaseDatabaseWrapper,
    source_tables: tuple[str, ...],
) -> None:
    """Reject reachable privilege escalation and mismatched source ownership."""

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH generation_table AS (
                    SELECT relation.oid, relation.relowner
                      FROM pg_catalog.pg_class AS relation
                      JOIN pg_catalog.pg_namespace AS namespace
                        ON namespace.oid = relation.relnamespace
                     WHERE namespace.nspname = 'public'
                       AND relation.relname = 'account_authority_generation'
                       AND relation.relkind = 'r'
                ),
                bump_function AS (
                    SELECT function.oid
                      FROM pg_catalog.pg_proc AS function
                     WHERE function.oid = pg_catalog.to_regprocedure(
                         'public.account_authority_generation_bump()'
                     )
                ),
                source_relation AS (
                    SELECT relation.oid, relation.relowner
                      FROM pg_catalog.pg_class AS relation
                      JOIN pg_catalog.pg_namespace AS namespace
                        ON namespace.oid = relation.relnamespace
                     WHERE namespace.nspname = 'public'
                       AND relation.relname::text = ANY(%s::text[])
                       AND relation.relkind = 'r'
                ),
                reachable_role AS (
                    SELECT role.oid, role.rolsuper, role.rolcreaterole,
                           role.rolreplication, role.rolbypassrls,
                           (
                               role.rolname NOT IN (current_user, session_user)
                               AND (
                                   pg_catalog.pg_has_role(
                                       current_user,
                                       role.oid,
                                       'MEMBER WITH ADMIN OPTION'
                                   )
                                   OR pg_catalog.pg_has_role(
                                       session_user,
                                       role.oid,
                                       'MEMBER WITH ADMIN OPTION'
                                   )
                               )
                           ) AS controlled_by_admin
                      FROM pg_catalog.pg_roles AS role
                     WHERE pg_catalog.pg_has_role(current_user, role.oid, 'SET')
                        OR pg_catalog.pg_has_role(session_user, role.oid, 'SET')
                        OR (
                            role.rolname NOT IN (current_user, session_user)
                            AND (
                                pg_catalog.pg_has_role(
                                    current_user,
                                    role.oid,
                                    'MEMBER WITH ADMIN OPTION'
                                )
                                OR pg_catalog.pg_has_role(
                                    session_user,
                                    role.oid,
                                    'MEMBER WITH ADMIN OPTION'
                                )
                            )
                        )
                )
                SELECT (SELECT COUNT(*) FROM source_relation),
                       COALESCE(
                           (
                               SELECT pg_catalog.bool_and(
                                   source_relation.relowner = generation_table.relowner
                               )
                                 FROM source_relation
                                 CROSS JOIN generation_table
                           ),
                           FALSE
                       ),
                       EXISTS (
                           SELECT 1
                             FROM reachable_role
                             CROSS JOIN generation_table
                             CROSS JOIN bump_function
                            WHERE reachable_role.controlled_by_admin
                               OR reachable_role.rolsuper
                               OR reachable_role.rolcreaterole
                               OR reachable_role.rolreplication
                               OR reachable_role.rolbypassrls
                               OR pg_catalog.has_schema_privilege(
                                   reachable_role.oid, 'public', 'CREATE'
                               )
                               OR pg_catalog.has_table_privilege(
                                   reachable_role.oid, generation_table.oid, 'INSERT'
                               )
                               OR pg_catalog.has_table_privilege(
                                   reachable_role.oid, generation_table.oid, 'UPDATE'
                               )
                               OR pg_catalog.has_table_privilege(
                                   reachable_role.oid, generation_table.oid, 'DELETE'
                               )
                               OR pg_catalog.has_table_privilege(
                                   reachable_role.oid, generation_table.oid, 'TRUNCATE'
                               )
                               OR pg_catalog.has_table_privilege(
                                   reachable_role.oid, generation_table.oid, 'TRIGGER'
                               )
                               OR pg_catalog.has_function_privilege(
                                   reachable_role.oid, bump_function.oid, 'EXECUTE'
                               )
                               OR EXISTS (
                                   SELECT 1
                                     FROM source_relation
                                    WHERE pg_catalog.has_table_privilege(
                                        reachable_role.oid,
                                        source_relation.oid,
                                        'TRIGGER'
                                    )
                                       OR pg_catalog.has_table_privilege(
                                           reachable_role.oid,
                                           source_relation.oid,
                                           'TRUNCATE'
                                       )
                               )
                       )
                """,
                [list(source_tables)],
            )
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationCoverageError(
            "account authority runtime role-closure query failed"
        ) from error
    if (
        row is None
        or len(row) != 3
        or type(row[0]) is not int
        or type(row[1]) is not bool
        or type(row[2]) is not bool
    ):
        raise AccountAuthorityGenerationCoverageError(
            "account authority runtime role-closure catalog row is malformed"
        )
    source_count, source_owners_match, reachable_role_is_dangerous = row
    if source_count != len(source_tables) or not source_owners_match or reachable_role_is_dangerous:
        raise AccountAuthorityGenerationCoverageError(
            "account authority runtime role-closure contract is not satisfied"
        )


__all__ = ["verify_account_authority_generation_runtime_acl_contract"]
