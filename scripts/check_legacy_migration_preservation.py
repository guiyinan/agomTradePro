#!/usr/bin/env python3
"""Read-only PostgreSQL fingerprints before legacy bootstrap and after migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import capture_legacy_observed_runtime as observer  # noqa: E402
from scripts.legacy_observed_runtime_baseline import LegacyBaselineBlocked  # noqa: E402
from scripts.observed_deploy_runtime_checks import _container  # noqa: E402

_SCHEMA = "legacy-observed-data-preservation.v1"
_READ_ONLY_OPTIONS = (
    "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=120000 -c lock_timeout=1000"
)
_READ_ONLY_PSQL = (
    "sh",
    "-eu",
    "-c",
    'exec psql -XAtq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
)


@dataclass(frozen=True)
class TableColumns:
    """Schema catalog narrowed before building a fixed read-only projection."""

    fields: tuple[str, ...]
    order: tuple[str, ...]


def _identifier(name: str) -> str:
    """Quote an identifier obtained only from PostgreSQL's own schema catalog."""
    if not name or "\0" in name:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_IDENTIFIER_INVALID")
    return '"' + name.replace('"', '""') + '"'


def _psql(container_id: str, sql: str) -> str:
    """Execute hardcoded catalog SQL with both session and transaction read-only."""
    command = (
        "docker",
        "exec",
        "-i",
        "-e",
        _READ_ONLY_OPTIONS,
        container_id,
        *_READ_ONLY_PSQL,
    )
    try:
        result = subprocess.run(
            command,
            input=f"BEGIN READ ONLY;\n{sql}\nCOMMIT;\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED") from exc
    if result.returncode:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED")
    return result.stdout.strip()


def _row_digest(
    container_id: str,
    table: str,
    fields: tuple[str, ...],
    order: tuple[str, ...],
    *,
    timeout_seconds: float = 180.0,
) -> dict[str, object]:
    """Stream COPY bytes directly into a digest without retaining financial rows."""
    projection = ", ".join(_identifier(field) for field in fields)
    sort = ", ".join(_identifier(field) for field in order)
    if not fields or not order or not set(order).issubset(fields):
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_ROW_ORDER_INVALID")
    sql = (
        "BEGIN READ ONLY; COPY (SELECT row_to_json(preserved_row) FROM "
        f"(SELECT {projection} FROM public.{_identifier(table)} ORDER BY {sort}) "
        "AS preserved_row) TO STDOUT; COMMIT;\n"
    )
    command = (
        "docker",
        "exec",
        "-i",
        "-e",
        _READ_ONLY_OPTIONS,
        container_id,
        *_READ_ONLY_PSQL,
    )
    digest = hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode())
    count = 0
    errors: list[OSError | ValueError] = []
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    except OSError as exc:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED") from exc

    def consume() -> None:
        """Keep memory bounded while the caller enforces the whole-pipe deadline."""
        nonlocal count
        try:
            if process.stdin is None or process.stdout is None:
                raise OSError("unavailable pipes")
            process.stdin.write(sql.encode())
            process.stdin.close()
            while chunk := process.stdout.read(65536):
                digest.update(chunk)
                count += chunk.count(b"\n")
        except (OSError, ValueError) as exc:
            errors.append(exc)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    try:
        reader.join(timeout=max(0.0, timeout_seconds - (time.monotonic() - started)))
        if reader.is_alive():
            raise subprocess.TimeoutExpired("read-only database stream", timeout_seconds)
        status = process.wait(timeout=max(0.0, timeout_seconds - (time.monotonic() - started)))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED") from exc
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        reader.join(timeout=5)
        if not reader.is_alive():
            if process.stdin is not None:
                with suppress(OSError, ValueError):
                    process.stdin.close()
            if process.stdout is not None:
                with suppress(OSError, ValueError):
                    process.stdout.close()
    if errors:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED")
    if status:
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_READ_FAILED")
    return {
        "fields": list(fields),
        "order": list(order),
        "rows": count,
        "sha256": digest.hexdigest(),
    }


def _catalog(container_id: str) -> dict[str, TableColumns]:
    """Read all data-center base tables, their column order and primary keys."""
    sql = """
SELECT coalesce(json_agg(item ORDER BY item->>'table'), '[]'::json) FROM (
 SELECT json_build_object('table', t.table_name,
   'fields', (SELECT json_agg(c.column_name ORDER BY c.ordinal_position)
       FROM information_schema.columns c WHERE c.table_schema='public' AND c.table_name=t.table_name),
   'order', (SELECT json_agg(a.attname ORDER BY k.ordinality)
       FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ordinality)
       JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
       WHERE i.indrelid=(quote_ident('public')||'.'||quote_ident(t.table_name))::regclass AND i.indisprimary)) item
 FROM information_schema.tables t
 WHERE t.table_schema='public' AND t.table_type='BASE TABLE' AND left(t.table_name,12)='data_center_'
) catalog;
"""
    rows = observer._array(json.loads(_psql(container_id, sql)))
    result: dict[str, TableColumns] = {}
    for value in rows:
        row = observer._object(value)
        name = observer._string(row.get("table"))
        if name in result or not name.startswith("data_center_"):
            raise LegacyBaselineBlocked("OBSERVED_DATABASE_CATALOG_INVALID")
        fields = tuple(observer._string(item) for item in observer._array(row.get("fields")))
        order = tuple(observer._string(item) for item in observer._array(row.get("order")))
        if not fields or not order or not set(order).issubset(fields):
            raise LegacyBaselineBlocked("OBSERVED_DATABASE_PRIMARY_KEY_REQUIRED")
        result[name] = TableColumns(fields=fields, order=order)
    if not {"data_center_financial_fact", "data_center_canonical_publication"}.issubset(result):
        raise LegacyBaselineBlocked("OBSERVED_DATABASE_LEGACY_SCHEMA_MISSING")
    return result


def capture_preservation() -> dict[str, object]:
    """Fingerprint every existing data-center table and its original columns."""
    container = _container("postgres")
    container_id = observer._string(container.get("Id"))
    database = _psql(container_id, "SELECT current_database();")
    if database != "agomtradepro":
        raise LegacyBaselineBlocked("OBSERVED_PRODUCTION_DATABASE_IDENTITY_INVALID")
    catalog = _catalog(container_id)
    tables = {
        name: _row_digest(container_id, name, definition.fields, definition.order)
        for name, definition in catalog.items()
    }
    return {
        "schema": _SCHEMA,
        "postgres_container_id": container_id,
        "database": database,
        "tables": tables,
    }


def verify_preservation(baseline: dict[str, object]) -> None:
    """Require unchanged original rows/columns and zero new business/evidence rows."""
    if (
        set(baseline) != {"schema", "postgres_container_id", "database", "tables"}
        or baseline.get("schema") != _SCHEMA
    ):
        raise LegacyBaselineBlocked("OBSERVED_PRESERVATION_SNAPSHOT_INVALID")
    container_id = observer._string(_container("postgres").get("Id"))
    if (
        baseline.get("postgres_container_id") != container_id
        or baseline.get("database") != "agomtradepro"
    ):
        raise LegacyBaselineBlocked("OBSERVED_PRODUCTION_DATABASE_IDENTITY_INVALID")
    if _psql(container_id, "SELECT current_database();") != "agomtradepro":
        raise LegacyBaselineBlocked("OBSERVED_PRODUCTION_DATABASE_IDENTITY_INVALID")
    catalog = _catalog(container_id)
    tables = observer._object(baseline.get("tables"))
    if not tables or not set(tables).issubset(catalog):
        raise LegacyBaselineBlocked("OBSERVED_LEGACY_TABLE_REMOVED")
    for name, value in tables.items():
        old = observer._object(value)
        if set(old) != {"fields", "order", "rows", "sha256"}:
            raise LegacyBaselineBlocked("OBSERVED_PRESERVATION_SNAPSHOT_INVALID")
        fields = tuple(observer._string(item) for item in observer._array(old.get("fields")))
        order = tuple(observer._string(item) for item in observer._array(old.get("order")))
        if not set(fields).issubset(catalog[name].fields) or order != catalog[name].order:
            raise LegacyBaselineBlocked("OBSERVED_LEGACY_SCHEMA_CHANGED")
        if _row_digest(container_id, name, fields, order) != old:
            raise LegacyBaselineBlocked("OBSERVED_LEGACY_DATA_CHANGED")
    for name in sorted(set(catalog) - set(tables)):
        count = _psql(container_id, f"SELECT count(*) FROM public.{_identifier(name)};")
        if count != "0":
            raise LegacyBaselineBlocked("OBSERVED_NEW_BUSINESS_ROWS_PRESENT")
    numeric = _psql(
        container_id,
        """SELECT count(*) FROM public.data_center_financial_fact
        WHERE numeric_schema IS DISTINCT FROM 'legacy-decimal-v1'
           OR exact_value_text IS NOT NULL OR numeric_evidence IS NOT NULL OR value IS NULL;""",
    )
    if numeric != "0":
        raise LegacyBaselineBlocked("OBSERVED_NATIVE_NUMERIC_ROWS_PRESENT")


def main(argv: Sequence[str] | None = None) -> int:
    """Capture/verify hashes on the existing production PG through read-only queries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify"))
    parser.add_argument("--snapshot-json", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            payload = capture_preservation()
            with args.snapshot_json.open("xb") as output:
                output.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
            args.snapshot_json.chmod(0o444)
        else:
            if not stat.S_ISREG(args.snapshot_json.lstat().st_mode):
                raise LegacyBaselineBlocked("OBSERVED_PRESERVATION_SNAPSHOT_INVALID")
            verify_preservation(observer._object(json.loads(args.snapshot_json.read_bytes())))
        print("OBSERVED_LEGACY_DATA_PRESERVATION_PASSED")
        return 0
    except LegacyBaselineBlocked as exc:
        code = str(exc)
        if re.fullmatch(r"[A-Za-z0-9_,]+", code) is None:
            code = "OBSERVED_LEGACY_DATA_INVALID"
        print(f"OBSERVED_LEGACY_DATA_PRESERVATION_BLOCKED code={code}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "OBSERVED_LEGACY_DATA_PRESERVATION_BLOCKED code=OBSERVED_LEGACY_DATA_INPUT_INVALID",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
