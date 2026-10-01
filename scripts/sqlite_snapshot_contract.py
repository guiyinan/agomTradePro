#!/usr/bin/env python3
"""Capture and reconcile Django model counts for a SQLite snapshot restore."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TypedDict, cast


class SnapshotCounts(TypedDict):
    """Serializable table-count evidence for one Django database."""

    schema_version: int
    database_vendor: str
    table_counts: dict[str, int]
    serialized_tables: list[str]
    row_count: int
    serialized_row_count: int


_EXCLUDED_MODELS = frozenset(
    {
        "auth.permission",
        "contenttypes.contenttype",
        "sessions.session",
    }
)


def capture_snapshot_counts(output_path: Path) -> SnapshotCounts:
    """Capture counts for every dumpdata-managed table present in the database."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.production")
    import django

    django.setup()
    from django.apps import apps
    from django.db import connection

    available = set(connection.introspection.table_names())
    counts: dict[str, int] = {}
    serialized_tables: set[str] = set()
    with connection.cursor() as cursor:
        for model in apps.get_models(include_auto_created=True):
            options = model._meta
            if (
                not options.managed
                or options.proxy
                or options.label_lower in _EXCLUDED_MODELS
                or options.db_table not in available
            ):
                continue
            if options.db_table not in counts:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {connection.ops.quote_name(options.db_table)}"
                )
                row = cursor.fetchone()
                if row is None or type(row[0]) is not int or row[0] < 0:
                    raise RuntimeError("snapshot table count result is invalid")
                counts[options.db_table] = row[0]
            if not options.auto_created:
                serialized_tables.add(options.db_table)
    evidence: SnapshotCounts = {
        "schema_version": 1,
        "database_vendor": connection.vendor,
        "table_counts": dict(sorted(counts.items())),
        "serialized_tables": sorted(serialized_tables),
        "row_count": sum(counts.values()),
        "serialized_row_count": sum(counts[table] for table in serialized_tables),
    }
    _write_json(output_path, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return evidence


def reconcile_snapshot_counts(
    source_path: Path,
    target_path: Path,
    fixture_path: Path,
    report_path: Path,
) -> dict[str, object]:
    """Fail closed unless fixture rows and restored table counts match exactly."""

    source = _load_counts(source_path, expected_vendor="sqlite")
    target = _load_counts(target_path, expected_vendor="postgresql")
    source_counts = source["table_counts"]
    target_counts = target["table_counts"]
    if not source_counts:
        raise ValueError("SQLite source verification produced no managed table counts")
    fixture_rows = sum(
        1 for line in fixture_path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    if fixture_rows != source["serialized_row_count"]:
        raise ValueError(
            "SQLite fixture row count does not match source managed-table counts: "
            f"fixture={fixture_rows}, source={source['serialized_row_count']}"
        )
    all_tables = set(source_counts) | set(target_counts)
    mismatches = {
        table: {"source": source_counts.get(table, 0), "target": target_counts.get(table, 0)}
        for table in sorted(all_tables)
        if source_counts.get(table, 0) != target_counts.get(table, 0)
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "outcome": ("failed" if mismatches else "success" if source["row_count"] > 0 else "noop"),
        "source_table_count": len(source_counts),
        "target_table_count": len(target_counts),
        "source_row_count": source["row_count"],
        "target_row_count": target["row_count"],
        "source_serialized_row_count": source["serialized_row_count"],
        "target_serialized_row_count": target["serialized_row_count"],
        "fixture_row_count": fixture_rows,
        "mismatches": mismatches,
    }
    _write_json(report_path, report)
    if mismatches:
        raise ValueError(
            "managed table count mismatch after PostgreSQL snapshot restore: "
            + json.dumps(mismatches, sort_keys=True)
        )
    print(json.dumps(report, sort_keys=True))
    return report


def _load_counts(path: Path, *, expected_vendor: str) -> SnapshotCounts:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot count evidence must be a JSON object")
    if payload.get("schema_version") != 1 or payload.get("database_vendor") != expected_vendor:
        raise ValueError("snapshot count evidence has the wrong schema or database vendor")
    raw_counts = payload.get("table_counts")
    raw_serialized_tables = payload.get("serialized_tables")
    raw_total = payload.get("row_count")
    raw_serialized_total = payload.get("serialized_row_count")
    if (
        not isinstance(raw_counts, dict)
        or not isinstance(raw_serialized_tables, list)
        or type(raw_total) is not int
        or raw_total < 0
        or type(raw_serialized_total) is not int
        or raw_serialized_total < 0
        or raw_serialized_total > raw_total
        or any(
            not isinstance(table, str) or type(count) is not int or count < 0
            for table, count in raw_counts.items()
        )
    ):
        raise ValueError("snapshot count evidence contains invalid counts")
    counts = cast(dict[str, int], raw_counts)
    serialized_tables = cast(list[object], raw_serialized_tables)
    if raw_total != sum(counts.values()):
        raise ValueError("snapshot count evidence total does not match its tables")
    if (
        any(not isinstance(table, str) or table not in counts for table in serialized_tables)
        or len(set(serialized_tables)) != len(serialized_tables)
        or raw_serialized_total != sum(counts[cast(str, table)] for table in serialized_tables)
    ):
        raise ValueError("snapshot serialized-table evidence is inconsistent")
    return {
        "schema_version": 1,
        "database_vendor": expected_vendor,
        "table_counts": counts,
        "serialized_tables": cast(list[str], serialized_tables),
        "row_count": raw_total,
        "serialized_row_count": raw_serialized_total,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--source", type=Path, required=True)
    verify.add_argument("--target", type=Path, required=True)
    verify.add_argument("--fixture", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run snapshot count capture or cross-database reconciliation."""

    arguments = _parser().parse_args(argv)
    if arguments.command == "capture":
        capture_snapshot_counts(arguments.output)
    else:
        reconcile_snapshot_counts(
            arguments.source,
            arguments.target,
            arguments.fixture,
            arguments.report,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
