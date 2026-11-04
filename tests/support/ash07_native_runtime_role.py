"""Reversible runtime-role setup for the one owned ASH07 Native test database."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg
from django.db import DatabaseError, connections
from psycopg import sql

from apps.account.infrastructure.account_authority_generation import (
    verify_account_authority_generation_coverage,
    verify_account_authority_generation_runtime_acl,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

_TEST_DATABASE = "test_ash03_close_20261102"
_PORT = 59513
_FUNCTIONS = ("account_authority_generation_bump", "account_authority_generation_lock")
_GENERATION_TABLE = "account_authority_generation"

_ACL_QUERY = """
WITH objects AS (
 SELECT 'relation' AS kind, n.nspname AS namespace, c.relname AS name,
        c.relowner AS owner,
        COALESCE(c.relacl, pg_catalog.acldefault(
          CASE WHEN c.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,
          c.relowner)) AS acl
   FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','S')
 UNION ALL
 SELECT 'function', n.nspname, p.proname || '(' ||
        pg_catalog.pg_get_function_identity_arguments(p.oid) || ')', p.proowner,
        COALESCE(p.proacl, pg_catalog.acldefault('f',p.proowner))
   FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public'
 UNION ALL
 SELECT 'schema', n.nspname, n.nspname, n.nspowner,
        COALESCE(n.nspacl, pg_catalog.acldefault('n',n.nspowner))
   FROM pg_catalog.pg_namespace n WHERE n.nspname='public'
)
SELECT o.kind,o.namespace,o.name,owner_role.rolname,
       COALESCE(grantee.rolname,'PUBLIC'),grantor.rolname,
       a.privilege_type,a.is_grantable
  FROM objects o
  JOIN pg_catalog.pg_roles owner_role ON owner_role.oid=o.owner
  CROSS JOIN LATERAL pg_catalog.aclexplode(o.acl) a
  LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=a.grantee
  JOIN pg_catalog.pg_roles grantor ON grantor.oid=a.grantor
 ORDER BY 1,2,3,4,5,6,7,8
"""

_OWNERS_QUERY = """
SELECT n.nspname,c.relname,c.relkind,r.rolname
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  JOIN pg_catalog.pg_roles r ON r.oid=c.relowner
 WHERE n.nspname NOT IN ('pg_catalog','information_schema')
   AND n.nspname NOT LIKE 'pg_temp%%' AND n.nspname NOT LIKE 'pg_toast_temp%%'
 ORDER BY 1,2,3,4
"""


def _rows(
    admin: psycopg.Connection[tuple[object, ...]],
    query: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    with admin.cursor() as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _execute(admin: psycopg.Connection[tuple[object, ...]], statement: sql.Composable) -> None:
    with admin.cursor() as cursor:
        cursor.execute(statement)


def _identity(admin: psycopg.Connection[tuple[object, ...]]) -> tuple[object, ...]:
    return _rows(
        admin,
        "SELECT current_database(),inet_server_port(),session_user,current_user",
    )[0]


@contextmanager
def isolated_ash07_runtime_role(evidence_directory: Path) -> Iterator[dict[str, object]]:
    """Use a real restricted default login, restoring every touched owner and ACL.

    Only this existing loopback TEST database is accepted. No schema/table is
    created or dropped, no function definition/search path is replaced, and no
    PUBLIC privilege or role membership is granted. The local cluster's existing
    trust authentication permits a temporary login without any password DDL.
    """

    database = connections["default"]
    assert_native_postgres_test_database(expected_name=_TEST_DATABASE)
    if database.in_atomic_block or not database.get_autocommit():
        raise RuntimeError("runtime-role setup requires the outer transaction-test boundary")
    with database.cursor() as cursor:
        cursor.execute("SELECT current_database(),inet_server_port(),session_user,current_user")
        original_identity = cursor.fetchone()
    if (
        original_identity is None
        or original_identity[0:2] != (_TEST_DATABASE, _PORT)
        or original_identity[2] != original_identity[3]
        or str(database.settings_dict.get("HOST")) not in ("127.0.0.1", "localhost")
    ):
        raise RuntimeError("runtime-role setup refuses an unapproved physical target")
    coverage = verify_account_authority_generation_coverage(using="default")
    protected = (*coverage.source_tables, _GENERATION_TABLE)
    if len(coverage.source_tables) != 22 or len(set(protected)) != 23:
        raise RuntimeError("runtime-role setup requires the existing exact 22-source contract")
    saved_settings = deepcopy(database.settings_dict)
    suffix = uuid4().hex
    owner_role = f"ash07_owner_{suffix}"
    runtime_role = f"ash07_runtime_{suffix}"
    evidence_directory.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "database": _TEST_DATABASE,
        "port": _PORT,
        "management_identity": list(original_identity),
        "owner_role": owner_role,
        "runtime_role": runtime_role,
        "source_tables": list(coverage.source_tables),
        "restored": False,
        "runtime_acl_verified": False,
    }
    report_path = evidence_directory / "runtime-role.json"

    def record() -> None:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with psycopg.connect(**database.get_connection_params(), autocommit=True) as admin:
        if _identity(admin) != original_identity:
            raise RuntimeError("administrative connection differs from the guarded TEST target")
        before_acl = _rows(admin, _ACL_QUERY)
        before_owners = _rows(admin, _OWNERS_QUERY)
        for filename, snapshot in (
            ("effective-acl-before.json", before_acl),
            ("relation-owners-before.json", before_owners),
        ):
            (evidence_directory / filename).write_text(
                json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
            )
        table_owners = _rows(
            admin,
            "SELECT c.relname,r.rolname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner "
            "WHERE n.nspname='public' AND c.relkind='r' "
            "AND c.relname::text=ANY(%s::text[]) ORDER BY c.relname",
            (list(protected),),
        )
        function_owners = _rows(
            admin,
            "SELECT p.proname,r.rolname,p.prosecdef,p.proconfig "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' "
            "AND p.pronargs=0 AND p.proname::text=ANY(%s::text[]) ORDER BY p.proname",
            (list(_FUNCTIONS),),
        )
        if len(table_owners) != 23 or len(function_owners) != 2:
            raise RuntimeError("protected objects are missing; no ownership changes performed")
        report["original_table_owners"] = table_owners
        report["original_function_contracts"] = function_owners
        created: list[str] = []
        changed_tables: list[tuple[str, str]] = []
        changed_functions: list[tuple[str, str]] = []
        switched = False
        record()
        try:
            for name, login in ((owner_role, "NOLOGIN"), (runtime_role, "LOGIN")):
                _execute(
                    admin,
                    sql.SQL(
                        "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(name), sql.SQL(login)),
                )
                created.append(name)
            _execute(
                admin,
                sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(owner_role)),
            )
            for name, old_owner in table_owners:
                if type(name) is not str or type(old_owner) is not str:
                    raise RuntimeError("invalid protected table identity")
                _execute(
                    admin,
                    sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                        sql.Identifier("public", name), sql.Identifier(owner_role)
                    ),
                )
                changed_tables.append((name, old_owner))
            for name, old_owner, _secdef, _config in function_owners:
                if type(name) is not str or type(old_owner) is not str:
                    raise RuntimeError("invalid protected function identity")
                _execute(
                    admin,
                    sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
                        sql.Identifier("public", name), sql.Identifier(owner_role)
                    ),
                )
                changed_functions.append((name, old_owner))
            _execute(
                admin,
                sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                    sql.Identifier(owner_role)
                ),
            )
            runtime = sql.Identifier(runtime_role)
            for statement in (
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}"),
                sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}"),
                sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"),
                sql.SQL(
                    "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER "
                    "ON public.account_authority_generation FROM {}"
                ),
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION public.account_authority_generation_lock() TO {}"
                ),
                sql.SQL(
                    "REVOKE ALL ON FUNCTION public.account_authority_generation_bump() FROM {}"
                ),
            ):
                _execute(admin, statement.format(runtime))
            database.close()
            database.settings_dict.update(USER=runtime_role, PASSWORD="", CONN_MAX_AGE=0)
            switched = True
            database.ensure_connection()
            assert_native_postgres_test_database(expected_name=_TEST_DATABASE)
            with database.cursor() as cursor:
                cursor.execute(
                    "SELECT current_database(),inet_server_port(),session_user,current_user"
                )
                runtime_identity = cursor.fetchone()
            if runtime_identity != (_TEST_DATABASE, _PORT, runtime_role, runtime_role):
                raise RuntimeError("default alias did not establish a real runtime login")
            verify_account_authority_generation_runtime_acl(using="default")
            report["runtime_identity"] = list(runtime_identity)
            report["runtime_acl_verified"] = True
            record()
            yield report
        finally:
            errors: list[str] = []

            def restore(statement: sql.Composable, label: str) -> None:
                try:
                    _execute(admin, statement)
                except psycopg.Error as error:
                    errors.append(f"{label}: {type(error).__name__}")

            if switched:
                try:
                    database.close()
                    database.settings_dict.clear()
                    database.settings_dict.update(saved_settings)
                    database.ensure_connection()
                    with database.cursor() as cursor:
                        cursor.execute(
                            "SELECT current_database(),inet_server_port(),session_user,current_user"
                        )
                        restored_identity = cursor.fetchone()
                    if restored_identity != original_identity:
                        errors.append("management connection identity was not restored")
                except (DatabaseError, psycopg.Error) as error:
                    errors.append(f"management reconnection: {type(error).__name__}")
            for name, previous_owner in reversed(changed_functions):
                restore(
                    sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
                        sql.Identifier("public", name), sql.Identifier(previous_owner)
                    ),
                    name,
                )
            for name, previous_owner in reversed(changed_tables):
                restore(
                    sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                        sql.Identifier("public", name), sql.Identifier(previous_owner)
                    ),
                    name,
                )
            for name in created:
                role = sql.Identifier(name)
                statements = (
                    (
                        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}"),
                        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}"),
                        sql.SQL("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {}"),
                        sql.SQL("REVOKE ALL ON SCHEMA public FROM {}"),
                    )
                    if name == runtime_role
                    else (sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}"),)
                )
                for statement in statements:
                    restore(statement.format(role), f"revoke {name}")
            after_owners = _rows(admin, _OWNERS_QUERY)
            after_acl = _rows(admin, _ACL_QUERY)
            report["relation_owners_match"] = after_owners == before_owners
            report["effective_acl_matches"] = after_acl == before_acl
            for filename, snapshot in (
                ("effective-acl-after.json", after_acl),
                ("relation-owners-after.json", after_owners),
            ):
                (evidence_directory / filename).write_text(
                    json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
                )
            if after_owners != before_owners:
                errors.append("relation/index/owned-sequence owners differ from their snapshot")
            if after_acl != before_acl:
                errors.append(
                    "effective schema/table/sequence/function ACLs differ from their snapshot"
                )
            functions_after = _rows(
                admin,
                "SELECT p.proname,r.rolname,p.prosecdef,p.proconfig "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' "
                "AND p.pronargs=0 AND p.proname::text=ANY(%s::text[]) ORDER BY p.proname",
                (list(_FUNCTIONS),),
            )
            if functions_after != function_owners:
                errors.append("protected function owners or security contracts differ")
            for name in created:
                dependencies = _rows(
                    admin,
                    "SELECT count(*) FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid "
                    "WHERE d.refclassid='pg_authid'::regclass AND r.rolname=%s",
                    (name,),
                )[0][0]
                members = _rows(
                    admin,
                    "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r "
                    "ON r.oid IN (m.roleid,m.member) WHERE r.rolname=%s",
                    (name,),
                )[0][0]
                if dependencies != 0 or members != 0:
                    errors.append(f"temporary role still has dependencies: {name}")
            report["restore_errors"] = errors
            if not errors:
                for name in reversed(created):
                    _execute(admin, sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
                if _rows(
                    admin,
                    "SELECT count(*) FROM pg_roles WHERE rolname=ANY(%s::text[])",
                    (created,),
                ) != [(0,)]:
                    raise RuntimeError("temporary roles were not completely removed")
                report["temporary_roles_absent"] = True
                report["restored"] = True
            record()
            if errors:
                raise RuntimeError("test runtime-role cleanup failed: " + "; ".join(errors))
