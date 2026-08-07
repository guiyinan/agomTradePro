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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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


class DatabaseSnapshot(TypedDict):
    """Stable public-schema snapshot used for source/restore comparison."""

    tables: dict[str, TableFingerprint]
    data_center_migrations: list[str]
    schema_sha256: str


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


def validate_custom_dump(path: Path, target: PostgresTarget) -> int:
    """Fail closed unless pg_restore can enumerate a non-empty custom dump."""

    if not path.is_file() or path.stat().st_size < 1:
        raise ValueError("postgres backup dump is missing or empty")
    completed = subprocess.run(
        ["pg_restore", "--list", str(path)],
        env=target.client_environment(),
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
    """Hash columns, constraints, indexes and sequence state in stable order."""

    queries = {
        "columns": """
            SELECT table_name, column_name, ordinal_position, data_type,
                   udt_schema, udt_name, is_nullable, column_default,
                   identity_generation, is_generated, collation_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
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
                   increment_by, cycle, cache_size, last_value
            FROM pg_sequences
            WHERE schemaname = 'public'
            ORDER BY sequencename
        """,
    }
    evidence: dict[str, list[list[object]]] = {}
    with connection.cursor() as cursor:
        for name, query in queries.items():
            cursor.execute(query)
            evidence[name] = [list(row) for row in cursor.fetchall()]
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def snapshot_database(database_url: str) -> DatabaseSnapshot:
    """Capture exact row counts/content hashes plus applied Data Center migrations."""

    with connect(database_url) as connection:
        with connection.cursor() as cursor:
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
    return {
        "tables": fingerprints,
        "data_center_migrations": migrations,
        "schema_sha256": schema_sha256,
    }


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


def restore_dump(path: Path, target: PostgresTarget, restore_database: str) -> None:
    """Restore with ownership/ACL isolation and stop on the first error."""

    subprocess.run(
        [
            "pg_restore",
            *target.client_connection_args(),
            "--dbname",
            restore_database,
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            str(path),
        ],
        env=target.client_environment(),
        capture_output=True,
        text=True,
        check=True,
    )


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
        restore_entries = validate_custom_dump(dump_path, target)
        source_snapshot = snapshot_database(target.url)
        restore_started = time.monotonic()
        recreate_restore_database(target, restore_database)
        restore_dump(dump_path, target, restore_database)
        restore_seconds = round(time.monotonic() - restore_started, 3)
        verification_started = time.monotonic()
        restored_snapshot = snapshot_database(target.url_for_database(restore_database))
        schema_report = build_canonical_schema_report(
            restored_snapshot["tables"].keys(),
            restored_snapshot["data_center_migrations"],
        )
        if source_snapshot != restored_snapshot:
            raise RuntimeError("postgres_restore_snapshot_mismatch")
        if schema_report["missing_tables"] or schema_report["missing_migrations"]:
            raise RuntimeError("postgres_restore_canonical_schema_incomplete")
        verification_seconds = round(time.monotonic() - verification_started, 3)
        report.update(
            {
                "outcome": "success",
                "source_database": target.database,
                "restore_database": restore_database,
                "dump_path": str(dump_path),
                "dump_size_bytes": dump_path.stat().st_size,
                "dump_sha256": sha256_file(dump_path),
                "restore_entries": restore_entries,
                "source_snapshot": source_snapshot,
                "restored_snapshot": restored_snapshot,
                "canonical_schema": schema_report,
                "restore_seconds": restore_seconds,
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
