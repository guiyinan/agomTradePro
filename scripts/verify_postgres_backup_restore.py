#!/usr/bin/env python3
"""Restore a PostgreSQL custom dump into isolation and emit exact evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit
from uuid import uuid4

from psycopg import Connection, connect, sql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.data_center.infrastructure.canonical_schema_contract import (  # noqa: E402
    build_canonical_schema_report,
)

DATABASE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class TableFingerprint(TypedDict):
    """Exact bounded-CI fingerprint for one restored table."""

    rows: int
    content_sha256: str


class SequenceFingerprint(TypedDict):
    """Value that determines the next result returned by one sequence."""

    last_value: int
    is_called: bool


class DatabaseSnapshot(TypedDict):
    """Stable public-schema snapshot used for source/restore comparison."""

    tables: dict[str, TableFingerprint]
    data_center_migrations: list[str]
    schema_sha256: str
    sequences: dict[str, SequenceFingerprint]


class SnapshotDifference(TypedDict):
    """Bounded component-level differences between source and restore."""

    missing_tables: list[str]
    extra_tables: list[str]
    changed_tables: dict[str, dict[str, TableFingerprint]]
    missing_migrations: list[str]
    extra_migrations: list[str]
    schema_sha256: dict[str, str] | None
    missing_sequences: list[str]
    extra_sequences: list[str]
    changed_sequences: dict[str, dict[str, SequenceFingerprint]]


@dataclass(frozen=True)
class PostgresTarget:
    """Parsed connection details without exposing the password in argv."""

    url: str
    database: str
    host: str
    port: int
    user: str
    password: str
    parsed: SplitResult

    def url_for_database(self, database: str) -> str:
        """Return a DSN for another database on the same server."""

        if not DATABASE_NAME_RE.fullmatch(database):
            raise ValueError("restore database name is invalid")
        return urlunsplit(self.parsed._replace(path=f"/{database}"))

    def client_environment(self) -> dict[str, str]:
        """Return a subprocess environment carrying the password out of argv."""

        environment = os.environ.copy()
        if self.password:
            environment["PGPASSWORD"] = self.password
        return environment

    def client_connection_args(self) -> list[str]:
        """Return common libpq CLI arguments without credentials."""

        return [
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--username",
            self.user,
        ]

    def client_connection_args_for_container(self) -> list[str]:
        """Return CLI arguments that reach a host-local database container.

        Docker Desktop containers cannot use their own loopback interface to
        reach a PostgreSQL server published on the Windows host.  The Docker
        provided ``host.docker.internal`` name is substituted only for
        loopback targets when the optional container client is selected.
        Remote database hosts are left untouched.
        """

        return [
            "--host",
            self.container_host(),
            "--port",
            str(self.port),
            "--username",
            self.user,
        ]

    def container_host(self) -> str:
        """Return the hostname visible from an optional Docker client."""

        return (
            "host.docker.internal" if self.host in {"localhost", "127.0.0.1", "::1"} else self.host
        )


def parse_postgres_target(database_url: str) -> PostgresTarget:
    """Validate and parse one PostgreSQL URL for an isolated restore rehearsal."""

    parsed = urlsplit(database_url.strip())
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use postgres or postgresql")
    database = unquote(parsed.path.lstrip("/"))
    host = parsed.hostname or ""
    user = unquote(parsed.username or "")
    if not DATABASE_NAME_RE.fullmatch(database) or not host or not user:
        raise ValueError("DATABASE_URL database, host and user are required")
    return PostgresTarget(
        url=database_url.strip(),
        database=database,
        host=host,
        port=int(parsed.port or 5432),
        user=user,
        password=unquote(parsed.password or ""),
        parsed=parsed,
    )


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for the completed dump artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pgpass_value(value: str) -> str:
    """Escape one secret-free ``.pgpass`` field without allowing line breaks."""

    if "\n" in value or "\r" in value:
        raise ValueError("PostgreSQL credentials cannot contain line breaks")
    return value.replace("\\", "\\\\").replace(":", "\\:")


@contextmanager
def _pg_restore_invocation(
    path: Path,
    target: PostgresTarget,
    *,
    container_image: str | None,
) -> Iterator[tuple[list[str], dict[str, str], str]]:
    """Yield a pg_restore command prefix, environment, and dump argument.

    The default uses the host ``pg_restore`` binary.  An explicit Docker image
    keeps the fallback opt-in and portable for Windows hosts without libpq
    client tools.  The database password is placed in a short-lived mounted
    ``.pgpass`` file rather than in Docker arguments or process output.
    """

    if not container_image:
        yield ["pg_restore"], target.client_environment(), str(path)
        return
    image = container_image.strip()
    if not image:
        raise ValueError("pg_restore container image must not be blank")
    dump_path = path.resolve()
    with TemporaryDirectory(prefix="agom-pg-restore-") as temporary:
        passfile = Path(temporary) / "pgpass"
        container_dump = "/tmp/agom-postgres-restore.dump"
        mounted_passfile = "/run/secrets/agom-postgres-restore.pgpass"
        container_passfile = "/tmp/agom-postgres-restore.pgpass"
        passfile_user = _pgpass_value(target.user)
        passfile_password = _pgpass_value(target.password)
        passfile.write_text(
            f"*:*:*:{passfile_user}:{passfile_password}\n",
            encoding="utf-8",
        )
        try:
            passfile.chmod(0o600)
        except OSError:
            # Windows ACLs are enforced by the temporary directory and Docker
            # Desktop; a POSIX mode bit is best-effort on that host.
            pass
        command = [
            "docker",
            "run",
            "--rm",
            "--volume",
            f"{dump_path}:{container_dump}:ro",
            "--volume",
            f"{passfile}:{mounted_passfile}:ro",
            image,
            "sh",
            "-c",
            (
                f"cp {mounted_passfile} {container_passfile} && "
                f"chmod 600 {container_passfile} && "
                f'PGPASSFILE={container_passfile} exec pg_restore "$@"'
            ),
            "pg_restore",
        ]
        environment = os.environ.copy()
        environment.pop("PGPASSWORD", None)
        yield command, environment, container_dump


def validate_custom_dump(
    path: Path,
    target: PostgresTarget,
    *,
    container_image: str | None = None,
) -> int:
    """Fail closed unless pg_restore can enumerate a non-empty custom dump."""

    if not path.is_file() or path.stat().st_size < 1:
        raise ValueError("postgres backup dump is missing or empty")
    with _pg_restore_invocation(path, target, container_image=container_image) as invocation:
        command_prefix, environment, dump_argument = invocation
        completed = subprocess.run(
            [*command_prefix, "--list", dump_argument],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
    entries = [line for line in completed.stdout.splitlines() if line and not line.startswith(";")]
    if not entries:
        raise ValueError("postgres backup dump contains no restore entries")
    return len(entries)


def _table_fingerprint(connection: Connection[tuple[object, ...]], table: str) -> TableFingerprint:
    """Stream a stable SHA-256 over every serialized row."""

    query = sql.SQL(
        "SELECT to_jsonb(source_row)::text FROM {} AS source_row "
        "ORDER BY to_jsonb(source_row)::text"
    ).format(sql.Identifier("public", table))
    digest = hashlib.sha256()
    rows = 0
    cursor_name = f"fingerprint_{hashlib.sha256(table.encode('utf-8')).hexdigest()[:16]}"
    with connection.cursor(name=cursor_name) as cursor:
        cursor.execute(query)
        while batch := cursor.fetchmany(1_000):
            for row in batch:
                row_json = row[0]
                if not isinstance(row_json, str):
                    raise RuntimeError(f"table fingerprint returned invalid row: {table}")
                digest.update(row_json.encode("utf-8"))
                digest.update(b"\n")
                rows += 1
    return {"rows": rows, "content_sha256": digest.hexdigest()}


def _schema_fingerprint(connection: Connection[tuple[object, ...]]) -> str:
    """Hash columns, constraints, indexes and sequence definitions."""

    queries = {
        "columns": """
            SELECT table_name, column_name, data_type,
                   udt_schema, udt_name, is_nullable, column_default,
                   identity_generation, is_generated, collation_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, column_name
        """,
        "constraints": """
            SELECT relation.relname, constraint_row.conname, constraint_row.contype,
                   pg_get_constraintdef(constraint_row.oid, true)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
            ORDER BY relation.relname, constraint_row.conname
        """,
        "indexes": """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
        """,
        "sequences": """
            SELECT sequencename, data_type, start_value, min_value, max_value,
                   increment_by, cycle, cache_size
            FROM pg_sequences
            WHERE schemaname = 'public'
            ORDER BY sequencename
        """,
    }
    evidence: dict[str, list[list[object]]] = {}
    with connection.cursor() as cursor:
        for name, query in queries.items():
            cursor.execute(query)
            rows = [list(row) for row in cursor.fetchall()]
            if name == "constraints":
                for row in rows:
                    definition = row[3]
                    if not isinstance(definition, str):
                        raise RuntimeError("constraint definition is invalid")
                    row[3] = _normalize_constraint_definition(definition)
            evidence[name] = rows
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_constraint_definition(definition: str) -> str:
    """Collapse PostgreSQL dump/reparse variants with identical cast semantics."""

    return (
        definition.replace("::character varying::text", "::text")
        .replace("::character varying", "::text")
        .replace("]::text[]", "]")
    )


def _sequence_fingerprints(
    connection: Connection[tuple[object, ...]],
) -> dict[str, SequenceFingerprint]:
    """Capture last_value and is_called without conflating data with schema."""

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT sequencename
            FROM pg_sequences
            WHERE schemaname = 'public'
            ORDER BY sequencename
            """)
        sequence_names = [str(row[0]) for row in cursor.fetchall()]
        if not sequence_names:
            return {}
        sequence_queries = [
            sql.SQL("SELECT {}::text AS sequence_name, last_value, is_called FROM {}").format(
                sql.Literal(sequence_name),
                sql.Identifier("public", sequence_name),
            )
            for sequence_name in sequence_names
        ]
        cursor.execute(
            sql.SQL(" UNION ALL ").join(sequence_queries) + sql.SQL(" ORDER BY sequence_name")
        )
        fingerprints: dict[str, SequenceFingerprint] = {}
        for row in cursor.fetchall():
            sequence_name = str(row[0])
            if not isinstance(row[1], int) or not isinstance(row[2], bool):
                raise RuntimeError(f"sequence fingerprint is invalid: {sequence_name}")
            fingerprints[sequence_name] = {
                "last_value": row[1],
                "is_called": row[2],
            }
    return fingerprints


def snapshot_database(database_url: str) -> DatabaseSnapshot:
    """Capture exact row counts/content hashes plus applied Data Center migrations."""

    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL DateStyle = 'ISO, YMD'")
            cursor.execute("SET LOCAL IntervalStyle = 'iso_8601'")
            cursor.execute("SET LOCAL search_path = pg_catalog, public")
            cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """)
            tables = [str(row[0]) for row in cursor.fetchall()]
        fingerprints = {table: _table_fingerprint(connection, table) for table in tables}
        migrations: list[str] = []
        if "django_migrations" in fingerprints:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT name
                    FROM django_migrations
                    WHERE app = 'data_center'
                    ORDER BY name
                    """)
                migrations = [str(row[0]) for row in cursor.fetchall()]
        schema_sha256 = _schema_fingerprint(connection)
        sequences = _sequence_fingerprints(connection)
    return {
        "tables": fingerprints,
        "data_center_migrations": migrations,
        "schema_sha256": schema_sha256,
        "sequences": sequences,
    }


def compare_snapshots(source: DatabaseSnapshot, restored: DatabaseSnapshot) -> SnapshotDifference:
    """Return exact, machine-readable differences for restore failures."""

    source_tables = set(source["tables"])
    restored_tables = set(restored["tables"])
    common_tables = sorted(source_tables & restored_tables)
    changed_tables = {
        table: {
            "source": source["tables"][table],
            "restored": restored["tables"][table],
        }
        for table in common_tables
        if source["tables"][table] != restored["tables"][table]
    }
    source_migrations = set(source["data_center_migrations"])
    restored_migrations = set(restored["data_center_migrations"])
    source_sequences = set(source["sequences"])
    restored_sequences = set(restored["sequences"])
    common_sequences = sorted(source_sequences & restored_sequences)
    changed_sequences = {
        sequence: {
            "source": source["sequences"][sequence],
            "restored": restored["sequences"][sequence],
        }
        for sequence in common_sequences
        if source["sequences"][sequence] != restored["sequences"][sequence]
    }
    schema_difference = None
    if source["schema_sha256"] != restored["schema_sha256"]:
        schema_difference = {
            "source": source["schema_sha256"],
            "restored": restored["schema_sha256"],
        }
    return {
        "missing_tables": sorted(source_tables - restored_tables),
        "extra_tables": sorted(restored_tables - source_tables),
        "changed_tables": changed_tables,
        "missing_migrations": sorted(source_migrations - restored_migrations),
        "extra_migrations": sorted(restored_migrations - source_migrations),
        "schema_sha256": schema_difference,
        "missing_sequences": sorted(source_sequences - restored_sequences),
        "extra_sequences": sorted(restored_sequences - source_sequences),
        "changed_sequences": changed_sequences,
    }


def snapshots_match(difference: SnapshotDifference) -> bool:
    """Return whether a structured restore comparison contains no differences."""

    return not any(difference.values())


def recreate_restore_database(target: PostgresTarget, restore_database: str) -> None:
    """Create a clean isolated database using a maintenance connection."""

    maintenance_url = target.url_for_database("postgres")
    with connect(maintenance_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(restore_database)
                )
            )
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_database)))


def drop_restore_database(target: PostgresTarget, restore_database: str) -> None:
    """Remove the isolated restore database after evidence capture."""

    with connect(target.url_for_database("postgres"), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(restore_database)
                )
            )


def restore_dump(
    path: Path,
    target: PostgresTarget,
    restore_database: str,
    *,
    container_image: str | None = None,
) -> None:
    """Restore with ownership/ACL isolation and stop on the first error."""

    with _pg_restore_invocation(path, target, container_image=container_image) as invocation:
        command_prefix, environment, dump_argument = invocation
        connection_args = (
            target.client_connection_args_for_container()
            if container_image
            else target.client_connection_args()
        )
        try:
            subprocess.run(
                [
                    *command_prefix,
                    *connection_args,
                    "--dbname",
                    restore_database,
                    "--no-owner",
                    "--no-acl",
                    "--jobs=4",
                    "--exit-on-error",
                    dump_argument,
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            stderr = str(error.stderr or "").strip()
            if target.password:
                stderr = stderr.replace(target.password, "[redacted]")
            bounded_stderr = stderr[-4000:] or "unavailable"
            raise RuntimeError(
                f"pg_restore_failed(returncode={error.returncode}, " f"stderr={bounded_stderr})"
            ) from None


def write_report(path: Path, report: dict[str, object]) -> None:
    """Atomically persist machine-readable restore evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(f"{path.suffix}.partial")
    partial.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, path)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line contract used by PostgreSQL nightly CI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--dump-path", required=True)
    parser.add_argument(
        "--report-path",
        default="reports/quality/postgres-backup-restore/evidence.json",
    )
    parser.add_argument("--restore-database", default="")
    parser.add_argument(
        "--pg-restore-container",
        default=os.getenv("PG_RESTORE_CONTAINER", ""),
        help=(
            "Optional PostgreSQL image used for pg_restore when the host lacks "
            "libpq client tools; remains disabled by default."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run custom dump validation, isolated restore and exact comparison."""

    args = build_parser().parse_args(argv)
    report_path = Path(args.report_path).resolve()
    started = time.monotonic()
    report: dict[str, object] = {
        "outcome": "failed",
        "started_at": datetime.now(UTC).isoformat(),
    }
    target: PostgresTarget | None = None
    restore_database = ""
    restore_seconds: float | None = None
    verification_seconds: float | None = None
    dump_sha256_before = ""
    dump_sha256_after = ""
    try:
        target = parse_postgres_target(str(args.database_url))
        restore_prefix = f"{target.database[:40]}_restore_verify_"
        restore_candidate = (
            str(args.restore_database).strip() or f"{restore_prefix}{uuid4().hex[:8]}"
        )
        if (
            restore_candidate == target.database
            or not restore_candidate.startswith(restore_prefix)
            or not DATABASE_NAME_RE.fullmatch(restore_candidate)
        ):
            raise ValueError("restore database must use the controlled verification prefix")
        restore_database = restore_candidate
        dump_path = Path(args.dump_path).resolve()
        # Hash before format validation so the report identifies the exact
        # artifact that the validator and restore process were expected to
        # consume.  The archive is an input to a destructive-capable tool;
        # silently accepting a replacement while it is being read would make
        # the resulting restore evidence non-reproducible.
        dump_sha256_before = sha256_file(dump_path)
        restore_container = str(args.pg_restore_container).strip() or None
        if restore_container is None:
            restore_entries = validate_custom_dump(dump_path, target)
        else:
            restore_entries = validate_custom_dump(
                dump_path,
                target,
                container_image=restore_container,
            )
        validated_sha256 = sha256_file(dump_path)
        report.update(
            {
                "dump_sha256": validated_sha256,
                "dump_sha256_before": dump_sha256_before,
                "dump_sha256_after": validated_sha256,
            }
        )
        if validated_sha256 != dump_sha256_before:
            raise RuntimeError("postgres_backup_changed_during_validation")
        source_snapshot = snapshot_database(target.url)
        restore_started = time.monotonic()
        recreate_restore_database(target, restore_database)
        if restore_container is None:
            restore_dump(dump_path, target, restore_database)
        else:
            restore_dump(
                dump_path,
                target,
                restore_database,
                container_image=restore_container,
            )
        restore_seconds = round(time.monotonic() - restore_started, 3)
        dump_sha256_after = sha256_file(dump_path)
        report.update(
            {
                "dump_sha256": dump_sha256_after,
                "dump_sha256_before": dump_sha256_before,
                "dump_sha256_after": dump_sha256_after,
            }
        )
        if dump_sha256_after != dump_sha256_before:
            raise RuntimeError("postgres_backup_changed_during_restore")
        verification_started = time.monotonic()
        restored_snapshot = snapshot_database(target.url_for_database(restore_database))
        schema_report = build_canonical_schema_report(
            restored_snapshot["tables"].keys(),
            restored_snapshot["data_center_migrations"],
        )
        snapshot_difference = compare_snapshots(source_snapshot, restored_snapshot)
        verification_seconds = round(time.monotonic() - verification_started, 3)
        report.update(
            {
                "source_database": target.database,
                "restore_database": restore_database,
                "dump_path": str(dump_path),
                "dump_size_bytes": dump_path.stat().st_size,
                "dump_sha256": dump_sha256_after,
                "dump_sha256_before": dump_sha256_before,
                "dump_sha256_after": dump_sha256_after,
                "pg_restore_client": restore_container or "host",
                "restore_entries": restore_entries,
                "source_snapshot": source_snapshot,
                "restored_snapshot": restored_snapshot,
                "snapshot_difference": snapshot_difference,
                "canonical_schema": schema_report,
                "restore_seconds": restore_seconds,
                "verification_seconds": verification_seconds,
            }
        )
        if not snapshots_match(snapshot_difference):
            raise RuntimeError("postgres_restore_snapshot_mismatch")
        if schema_report["missing_tables"] or schema_report["missing_migrations"]:
            raise RuntimeError("postgres_restore_canonical_schema_incomplete")
        report.update(
            {
                "outcome": "success",
                "verification_seconds": verification_seconds,
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if target is not None and restore_database:
            try:
                drop_restore_database(target, restore_database)
            except Exception as cleanup_exc:
                report["cleanup_error"] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                report["outcome"] = "failed"
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["total_seconds"] = round(time.monotonic() - started, 3)
        report["rto_seconds"] = restore_seconds
        write_report(report_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
