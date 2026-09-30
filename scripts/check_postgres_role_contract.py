#!/usr/bin/env python3
"""Read-only acceptance check for the production PostgreSQL role split."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import cast

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.production")

ROLE_CONTRACT_SQL = """
WITH owner_role AS (
    SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_owner'
), migrator_role AS (
    SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolreplication, rolbypassrls, rolinherit
    FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_migrator'
), runtime_role AS (
    SELECT oid, rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
           rolreplication, rolbypassrls
    FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_runtime'
), public_owner_objects AS (
    SELECT relation.relowner AS owner_oid
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT function.proowner
    FROM pg_catalog.pg_proc AS function
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT data_type.typowner
    FROM pg_catalog.pg_type AS data_type
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = data_type.typnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT object_collation.collowner
    FROM pg_catalog.pg_collation AS object_collation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = object_collation.collnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT conversion.conowner
    FROM pg_catalog.pg_conversion AS conversion
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = conversion.connamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT operator_class.opcowner
    FROM pg_catalog.pg_opclass AS operator_class
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_class.opcnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT operator_family.opfowner
    FROM pg_catalog.pg_opfamily AS operator_family
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_family.opfnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT config.cfgowner
    FROM pg_catalog.pg_ts_config AS config
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = config.cfgnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT dictionary.dictowner
    FROM pg_catalog.pg_ts_dict AS dictionary
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = dictionary.dictnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT extension.extowner
    FROM pg_catalog.pg_extension AS extension
    WHERE extension.extnamespace = 'public'::pg_catalog.regnamespace
    UNION ALL
    SELECT statistic.stxowner
    FROM pg_catalog.pg_statistic_ext AS statistic
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = statistic.stxnamespace
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT namespace.nspowner
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname = 'public'
), authority_triggers AS (
    SELECT trigger.oid, trigger.tgenabled, relation.oid AS relation_oid,
           relation.relowner, function.proowner, function.prosecdef,
           function.proconfig, function.proname
    FROM pg_catalog.pg_trigger AS trigger
    JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_proc AS function ON function.oid = trigger.tgfoid
    WHERE namespace.nspname = 'public'
      AND NOT trigger.tgisinternal
      AND trigger.tgname IN ('acct_auth_gen_stmt', 'acct_auth_gen_truncate')
), generation_acl AS (
    SELECT
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'SELECT') AS can_select,
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'INSERT') AS can_insert,
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'UPDATE') AS can_update,
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'DELETE') AS can_delete,
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'TRUNCATE') AS can_truncate,
        pg_catalog.has_table_privilege('agomtradepro_runtime',
            'public.account_authority_generation', 'TRIGGER') AS can_trigger
), public_acl AS (
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(namespace.nspacl,
                     pg_catalog.acldefault('n', namespace.nspowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'CREATE'
    ) AS public_can_create
)
SELECT
    current_user = 'agomtradepro_runtime'
        AND session_user = current_user AS runtime_identity,
    EXISTS (
        SELECT 1 FROM runtime_role
        WHERE rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) AS runtime_role_safe,
    NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members
        WHERE member = (SELECT oid FROM runtime_role)
    ) AS runtime_has_no_role_memberships,
    NOT EXISTS (
        SELECT 1 FROM public_owner_objects
        WHERE owner_oid = (SELECT oid FROM runtime_role)
    ) AS runtime_owns_no_public_objects,
    EXISTS (
        SELECT 1 FROM owner_role
        WHERE NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) AS owner_role_safe,
    NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members
        WHERE member = (SELECT oid FROM owner_role)
    ) AS owner_has_no_role_memberships,
    (
        SELECT count(*) = 1 AND bool_and(
            child.rolname = 'agomtradepro_migrator'
            AND NOT link.admin_option
            AND COALESCE((pg_catalog.to_jsonb(link)->>'set_option')::boolean, true)
            AND NOT COALESCE((pg_catalog.to_jsonb(link)->>'inherit_option')::boolean, false)
        )
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS child ON child.oid = link.member
        WHERE link.roleid = (SELECT oid FROM owner_role)
    ) AS owner_has_only_migrator_member,
    EXISTS (
        SELECT 1 FROM migrator_role
        WHERE rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit
    ) AS migrator_role_safe,
    (
        SELECT count(*) = 1 AND bool_and(
            parent.rolname = 'agomtradepro_owner'
            AND NOT link.admin_option
            AND COALESCE((pg_catalog.to_jsonb(link)->>'set_option')::boolean, true)
            AND NOT COALESCE((pg_catalog.to_jsonb(link)->>'inherit_option')::boolean, false)
        )
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = link.roleid
        WHERE link.member = (SELECT oid FROM migrator_role)
    ) AS migrator_has_only_set_owner_membership,
    NOT pg_catalog.has_schema_privilege('agomtradepro_runtime', 'public', 'CREATE')
        AS runtime_cannot_create_in_public,
    NOT (SELECT public_can_create FROM public_acl) AS public_cannot_create,
    pg_catalog.has_schema_privilege('agomtradepro_runtime', 'public', 'USAGE')
        AS runtime_can_use_public,
    (
        SELECT relation.relowner = (SELECT oid FROM owner_role)
        FROM pg_catalog.pg_class AS relation
        WHERE relation.oid = 'public.account_authority_generation'::pg_catalog.regclass
    ) AS generation_owned_by_owner,
    (
        SELECT count(*) = 1 AND bool_and(singleton = 1 AND generation >= 0)
        FROM public.account_authority_generation
    ) AS generation_singleton_valid,
    (SELECT can_select FROM generation_acl) AS runtime_can_select_generation,
    NOT (SELECT can_insert OR can_update OR can_delete OR can_truncate OR can_trigger
         FROM generation_acl) AS runtime_cannot_write_or_trigger_generation,
    (
        SELECT count(*) = 44
           AND count(*) FILTER (
                WHERE tgenabled <> 'A'
                   OR relowner <> (SELECT oid FROM owner_role)
                   OR proowner <> (SELECT oid FROM owner_role)
                   OR NOT prosecdef
                   OR proname <> 'account_authority_generation_bump'
                   OR NOT COALESCE(
                       proconfig @> ARRAY['search_path=pg_catalog']::text[], false
                   )
           ) = 0
        FROM authority_triggers
    ) AS authority_triggers_secure,
    (
        SELECT count(*) = 1 AND bool_and(
            proowner = (SELECT oid FROM owner_role)
            AND prosecdef
            AND proconfig @> ARRAY['search_path=pg_catalog']::text[]
        )
        FROM pg_catalog.pg_proc AS function
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
        WHERE namespace.nspname = 'public'
          AND function.proname = 'account_authority_generation_bump'
    ) AS bump_function_secure,
    NOT pg_catalog.has_function_privilege(
        'agomtradepro_runtime',
        'public.account_authority_generation_bump()',
        'EXECUTE'
    ) AS runtime_cannot_execute_bump,
    (
        SELECT count(*) = 1 AND bool_and(
            proowner = (SELECT oid FROM owner_role)
            AND prosecdef
            AND proconfig @> ARRAY['search_path=pg_catalog']::text[]
        )
        FROM pg_catalog.pg_proc AS function
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
        WHERE namespace.nspname = 'public'
          AND function.proname = 'account_authority_generation_lock'
    ) AS fence_lock_function_secure,
    pg_catalog.has_function_privilege(
        'agomtradepro_runtime',
        'public.account_authority_generation_lock()',
        'EXECUTE'
    ) AS runtime_can_execute_fence_lock;
"""

ROLE_CONTRACT_CHECKS: tuple[str, ...] = (
    "runtime_identity",
    "runtime_role_safe",
    "runtime_has_no_role_memberships",
    "runtime_owns_no_public_objects",
    "owner_role_safe",
    "owner_has_no_role_memberships",
    "owner_has_only_migrator_member",
    "migrator_role_safe",
    "migrator_has_only_set_owner_membership",
    "runtime_cannot_create_in_public",
    "public_cannot_create",
    "runtime_can_use_public",
    "generation_owned_by_owner",
    "generation_singleton_valid",
    "runtime_can_select_generation",
    "runtime_cannot_write_or_trigger_generation",
    "authority_triggers_secure",
    "bump_function_secure",
    "runtime_cannot_execute_bump",
    "fence_lock_function_secure",
    "runtime_can_execute_fence_lock",
)


def evaluate_role_contract(values: Mapping[str, object]) -> tuple[str, ...]:
    """Return failed role-contract checks without including connection details."""

    return tuple(name for name in ROLE_CONTRACT_CHECKS if values.get(name) is not True)


def main() -> int:
    """Run the PostgreSQL contract query through the configured runtime connection."""

    from django import setup
    from django.db import connection

    setup()

    if connection.vendor != "postgresql":
        print("[FAIL] PostgreSQL role contract requires the production PostgreSQL backend")
        return 1

    from apps.account.infrastructure.account_authority_generation import (
        AccountAuthorityGenerationUnavailable,
        verify_account_authority_generation_coverage,
        verify_account_authority_generation_runtime_acl,
    )

    try:
        coverage = verify_account_authority_generation_coverage()
        if len(coverage.source_tables) != 22:
            print("[FAIL] PostgreSQL role contract: expected exactly 22 authority source tables")
            return 1
        verify_account_authority_generation_runtime_acl()
    except AccountAuthorityGenerationUnavailable as error:
        print(f"[FAIL] PostgreSQL account authority role contract: {error}")
        return 1

    with connection.cursor() as cursor:
        cursor.execute(ROLE_CONTRACT_SQL)
        row = cursor.fetchone()
        description = cursor.description
    if row is None or description is None:
        print("[FAIL] PostgreSQL role contract returned no result")
        return 1

    columns = tuple(cast(str, item[0]) for item in description)
    snapshot = dict(zip(columns, cast(tuple[object, ...], row), strict=True))
    failures = evaluate_role_contract(snapshot)
    if failures:
        for failure in failures:
            print(f"[FAIL] PostgreSQL role contract: {failure}")
        return 1

    print("[OK] PostgreSQL runtime role contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
