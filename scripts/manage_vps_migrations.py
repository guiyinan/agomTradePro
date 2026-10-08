#!/usr/bin/env python3
"""Run Django schema migrations through the isolated deployment role."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from pathlib import Path
from typing import cast

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.production")

import django

django.setup()

from django.core.management import execute_from_command_line
from django.db import connection, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

_OWNER_ROLE = "agomtradepro_owner"
_MIGRATOR_ROLE = "agomtradepro_migrator"
_ALLOWED_COMMANDS = frozenset({"migrate", "flush", "loaddata"})
_S6_MIGRATION_RESULT_SCHEMA = "release.s6-isolated-database-migration-result.v1"
_S6_MIGRATION_RESULT_PATH = "/run/agom/stage/migration-command-result.json"


def _assert_s6_rehearsal_scope() -> tuple[int, str] | None:
    """Verify the live migration connection is the exact disposable S6 database."""
    if os.environ.get("AGOM_S6_ISOLATED_DATABASE_MIGRATION") != "1":
        return None
    expected_database_name = os.environ.get("AGOM_S6_EXPECTED_DATABASE_NAME", "").strip()
    expected_database_host = os.environ.get("AGOM_S6_EXPECTED_DATABASE_HOST", "").strip()
    expected_container_id = os.environ.get("AGOM_S6_EXPECTED_DATABASE_CONTAINER_ID", "").strip()
    expected_database_address = os.environ.get("AGOM_S6_EXPECTED_DATABASE_ADDRESS", "").strip()
    result_path = os.environ.get("AGOM_S6_MIGRATION_RESULT_PATH", "")
    if (
        os.environ.get("AGOM_RELEASE_REHEARSAL_DATABASE") != "1"
        or not expected_database_name
        or not expected_database_host
        or len(expected_container_id) != 64
        or any(character not in "0123456789abcdef" for character in expected_container_id)
        or not expected_database_address
        or result_path != _S6_MIGRATION_RESULT_PATH
    ):
        raise RuntimeError("isolated S6 migration scope is incomplete")
    from apps.data_center.infrastructure.isolated_write_rehearsal_runner import (
        assert_isolated_rehearsal_database,
    )

    assert_isolated_rehearsal_database(
        expected_database_name=expected_database_name,
        expected_database_host=expected_database_host,
        require_ephemeral_host=True,
    )
    configured_port = connection.settings_dict.get("PORT") or 5432
    try:
        database_port = int(configured_port)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("isolated S6 migration database port is invalid") from exc
    if not 1 <= database_port <= 65535:
        raise RuntimeError("isolated S6 migration database port is invalid")
    with connection.cursor() as cursor:
        cursor.execute("SELECT inet_server_addr()::text, inet_server_port()")
        server_address, server_port = cast(tuple[str | None, int | None], cursor.fetchone())
    try:
        expected_address = ipaddress.ip_address(expected_database_address)
        actual_address = ipaddress.ip_address(server_address or "")
    except ValueError as exc:
        raise RuntimeError("isolated S6 migration database address is invalid") from exc
    if actual_address != expected_address or server_port != database_port:
        raise RuntimeError("isolated S6 migration database endpoint did not match Docker identity")
    return database_port, str(actual_address)


def _migration_state() -> tuple[list[str], list[str]]:
    """Return pending and applied migration identities in stable sorted order."""
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    pending = sorted(
        f"{migration.app_label}.{migration.name}" for migration, backwards in plan if not backwards
    )
    applied = sorted(
        f"{app_label}.{migration_name}"
        for app_label, migration_name in MigrationRecorder(connection).applied_migrations()
    )
    return pending, applied


def _write_s6_migration_result(
    *,
    pending_before: list[str],
    pending_after: list[str],
    applied_migrations: list[str],
    database_port: int,
    database_address: str,
) -> None:
    """Write the bounded, secret-free result consumed by the S6 runner."""
    path = Path(_S6_MIGRATION_RESULT_PATH)
    payload = {
        "schema": _S6_MIGRATION_RESULT_SCHEMA,
        "pending_before": pending_before,
        "pending_after": pending_after,
        "applied_migrations": applied_migrations,
        "database_port": database_port,
        "database_address": database_address,
    }
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _set_owner_role(
    sender: type[BaseDatabaseWrapper],
    connection: BaseDatabaseWrapper,
    **kwargs: object,
) -> None:
    """Set the owner role on each migrator database connection."""

    del sender, kwargs
    if connection.alias != "default":
        return
    if connection.vendor != "postgresql":
        raise RuntimeError("the deployment migrator requires PostgreSQL")
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE agomtradepro_owner")
        cursor.execute("SELECT session_user, current_user")
        session_user, current_user = cast(tuple[str, str], cursor.fetchone())
    if session_user != _MIGRATOR_ROLE or current_user != _OWNER_ROLE:
        raise RuntimeError("migrator database role identity did not match the deployment contract")
    _assert_s6_rehearsal_scope()


def main(argv: list[str] | None = None) -> int:
    """Run an allow-listed deployment migration or snapshot restore command."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in _ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(_ALLOWED_COMMANDS))
        raise SystemExit(f"only these deployment database commands are allowed: {allowed}")

    s6_migration = os.environ.get("AGOM_S6_ISOLATED_DATABASE_MIGRATION") == "1"
    if s6_migration and arguments != ["migrate", "--noinput"]:
        raise SystemExit("isolated S6 migration must use migrate --noinput")
    connection_created.connect(_set_owner_role, weak=False)
    connections["default"].ensure_connection()
    validated_database_endpoint = _assert_s6_rehearsal_scope() if s6_migration else None
    if s6_migration and validated_database_endpoint is None:
        raise SystemExit("isolated S6 migration database identity is unavailable")
    if arguments[0] == "loaddata":
        from apps.data_center.infrastructure.candidate_raw_audit_manifest_models import (
            _allow_candidate_manifest_fixture_restore,
        )

        with _allow_candidate_manifest_fixture_restore():
            execute_from_command_line(["manage.py", "loaddata", *arguments[1:]])
    elif arguments[0] == "migrate":
        migration_state_before: tuple[list[str], list[str]] | None = None
        if s6_migration:
            migration_state_before = _migration_state()
        execute_from_command_line(["manage.py", "migrate", *arguments[1:]])
        if migration_state_before is not None:
            if validated_database_endpoint is None:
                raise SystemExit("isolated S6 migration database identity is unavailable")
            pending_before, applied_before = migration_state_before
            pending_after, applied_after = _migration_state()
            applied_migrations = sorted(set(applied_after) - set(applied_before))
            _write_s6_migration_result(
                pending_before=pending_before,
                pending_after=pending_after,
                applied_migrations=applied_migrations,
                database_port=validated_database_endpoint[0],
                database_address=validated_database_endpoint[1],
            )
            if pending_after or applied_migrations != pending_before:
                raise SystemExit("candidate migrations remain pending")
    else:
        execute_from_command_line(["manage.py", "flush", *arguments[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
