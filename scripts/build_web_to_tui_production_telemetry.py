#!/usr/bin/env python
"""Build candidate-bound M5 production telemetry evidence from a reviewed snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.web_to_tui_retained_observation import (  # noqa: E402
    RetainedObservationError,
    parse_retained_observation,
    parse_utc_timestamp,
    utc_text,
)

DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
SNAPSHOT_VERSION = "web-to-tui-production-telemetry-snapshot.v2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
QUERY_KEYS = frozenset(
    {
        "classic_entries",
        "tui_entries",
        "classic_task_requests",
        "tui_task_requests",
        "classic_task_errors",
        "tui_task_errors",
    }
)
APPROVED_QUERIES = {
    "classic_entries": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="classic",event_type="entry"
        }[14d])))
    """,
    "tui_entries": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="tui",event_type="entry"
        }[14d])))
    """,
    "classic_task_requests": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="classic",event_type=~"entry|execution",
          outcome=~"success|client_error|server_error"
        }[14d])))
    """,
    "tui_task_requests": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="tui",event_type="execution",
          outcome=~"success|client_error|server_error"
        }[14d])))
    """,
    "classic_task_errors": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="classic",event_type=~"entry|execution",
          outcome=~"client_error|server_error"
        }[14d])))
    """,
    "tui_task_errors": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="tui",event_type="execution",
          outcome=~"client_error|server_error"
        }[14d])))
    """,
}


class ProductionTelemetryError(RuntimeError):
    """Raised when a production telemetry snapshot is incomplete or unsafe."""


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ProductionTelemetryError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _parse_date(value: object, *, field: str) -> date:
    """Parse one required ISO date field."""

    if not isinstance(value, str) or not value.strip():
        raise ProductionTelemetryError(f"Missing date field: {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ProductionTelemetryError(f"Invalid date field: {field}") from exc


def _non_negative_int(value: object, *, field: str) -> int:
    """Return one non-negative integer while rejecting booleans and floats."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProductionTelemetryError(f"{field} must be a non-negative integer")
    return value


def _git_commit_is_usable(commit: str, *, root: Path = ROOT) -> bool:
    """Return whether a full commit belongs to the current branch history."""

    if not COMMIT_PATTERN.fullmatch(commit):
        return False
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if exists.returncode:
        return False
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return ancestor.returncode == 0


def _valid_exception(value: object) -> bool:
    """Return whether a low-frequency exception has independent dual sign-off."""

    exception = _mapping(value)
    reason = str(exception.get("reason") or "").strip()
    owner = str(exception.get("owner") or "").strip()
    reviewer = str(exception.get("reviewer") or "").strip()
    return bool(reason and owner and reviewer and owner != reviewer)


def _normalize_query(value: str) -> str:
    """Collapse insignificant PromQL whitespace for exact contract comparison."""

    return " ".join(value.split())


def _validate_collection_metadata(snapshot: dict[str, Any]) -> None:
    """Require an auditable, secret-free Prometheus collection description."""

    collection = _mapping(snapshot.get("collection"))
    if collection.get("system") != "prometheus":
        raise ProductionTelemetryError("collection.system must be prometheus")
    endpoint = str(collection.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ProductionTelemetryError("collection.endpoint must be a credential-free HTTPS origin")
    queries = _mapping(collection.get("queries"))
    if set(queries) != QUERY_KEYS:
        raise ProductionTelemetryError("collection.queries must contain the exact six query keys")
    for query_key in sorted(QUERY_KEYS):
        expression = queries.get(query_key)
        approved = APPROVED_QUERIES[query_key]
        if not isinstance(expression, str) or _normalize_query(expression) != _normalize_query(
            approved
        ):
            raise ProductionTelemetryError(
                f"collection query does not match the approved contract for {query_key}"
            )


def _required_task_keys(catalog: dict[str, Any]) -> set[str]:
    """Return only Classic-comparable task keys from the checked-in catalog."""

    raw_routes = catalog.get("classic_routes")
    if not isinstance(raw_routes, list):
        raise ProductionTelemetryError("Telemetry catalog lacks classic_routes")
    keys: set[str] = set()
    for index, raw_route in enumerate(raw_routes):
        route = _mapping(raw_route)
        task_key = str(route.get("task_key") or "").strip()
        if not task_key:
            raise ProductionTelemetryError(
                f"Telemetry catalog classic route {index} lacks task_key"
            )
        keys.add(task_key)
    if not keys:
        raise ProductionTelemetryError("Telemetry catalog has no comparable task keys")
    return keys


def _validated_task_records(
    snapshot: dict[str, Any],
    required_tasks: set[str],
) -> list[dict[str, Any]]:
    """Validate exact task coverage and all M5 sample/error thresholds."""

    raw_tasks = snapshot.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ProductionTelemetryError("Snapshot tasks must be a list")
    records: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for raw_record in raw_tasks:
        record = _mapping(raw_record)
        task_key = str(record.get("task_key") or "").strip()
        if not task_key:
            raise ProductionTelemetryError("Snapshot contains a blank task_key")
        if task_key in records:
            duplicates.add(task_key)
        records[task_key] = record
    if duplicates:
        raise ProductionTelemetryError(
            f"Snapshot contains duplicate task keys: {', '.join(sorted(duplicates))}"
        )
    missing = required_tasks - set(records)
    extras = set(records) - required_tasks
    if missing or extras:
        raise ProductionTelemetryError(
            f"Snapshot task coverage mismatch: missing={len(missing)} extras={len(extras)}"
        )

    validated: list[dict[str, Any]] = []
    invalid: list[str] = []
    for task_key in sorted(required_tasks):
        record = records[task_key]
        try:
            classic_entries = _non_negative_int(
                record.get("classic_entries"), field=f"{task_key}.classic_entries"
            )
            tui_entries = _non_negative_int(
                record.get("tui_entries"), field=f"{task_key}.tui_entries"
            )
            classic_requests = _non_negative_int(
                record.get("classic_task_requests"),
                field=f"{task_key}.classic_task_requests",
            )
            tui_requests = _non_negative_int(
                record.get("tui_task_requests"), field=f"{task_key}.tui_task_requests"
            )
            classic_errors = _non_negative_int(
                record.get("classic_task_errors"), field=f"{task_key}.classic_task_errors"
            )
            tui_errors = _non_negative_int(
                record.get("tui_task_errors"), field=f"{task_key}.tui_task_errors"
            )
        except ProductionTelemetryError:
            invalid.append(task_key)
            continue

        entry_samples = classic_entries + tui_entries
        exception = record.get("low_frequency_exception")
        threshold_ok = True
        if entry_samples < 20:
            threshold_ok = _valid_exception(exception)
        elif classic_entries / entry_samples > 0.05:
            threshold_ok = False
        if classic_requests < 20 or tui_requests < 20:
            threshold_ok = False
        elif classic_errors > classic_requests or tui_errors > tui_requests:
            threshold_ok = False
        elif tui_errors / tui_requests - classic_errors / classic_requests > 0.005:
            threshold_ok = False
        if not threshold_ok:
            invalid.append(task_key)
            continue

        validated.append(
            {
                "task_key": task_key,
                "classic_entries": classic_entries,
                "tui_entries": tui_entries,
                "classic_task_requests": classic_requests,
                "tui_task_requests": tui_requests,
                "classic_task_errors": classic_errors,
                "tui_task_errors": tui_errors,
                "low_frequency_exception": exception,
            }
        )
    if invalid:
        preview = ", ".join(invalid[:10])
        suffix = f" and {len(invalid) - 10} more" if len(invalid) > 10 else ""
        raise ProductionTelemetryError(
            f"Telemetry thresholds failed for {len(invalid)} tasks: {preview}{suffix}"
        )
    return validated


def build_production_telemetry_evidence(
    *,
    snapshot: dict[str, Any],
    catalog: dict[str, Any],
    evidence: dict[str, Any],
    snapshot_evidence_path: str,
    snapshot_sha256: str,
    as_of: datetime,
) -> dict[str, Any]:
    """Return cutover evidence populated from one fully validated production snapshot."""

    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise ProductionTelemetryError("Unsupported production telemetry snapshot version")
    if snapshot.get("environment") != "production":
        raise ProductionTelemetryError("Snapshot environment must be production")
    if not SHA256_PATTERN.fullmatch(snapshot_sha256):
        raise ProductionTelemetryError("Snapshot SHA-256 is invalid")
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    if (
        str(catalog.get("source_sha256") or "").strip() != source_sha256
        or str(snapshot.get("source_sha256") or "").strip() != source_sha256
    ):
        raise ProductionTelemetryError("Snapshot, catalog, and evidence source SHA do not match")

    candidate = _mapping(evidence.get("candidate"))
    stable_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    if not stable_version or not _git_commit_is_usable(candidate_commit):
        raise ProductionTelemetryError("Cutover evidence does not contain a usable candidate")
    if (
        str(snapshot.get("candidate_version") or "").strip() != stable_version
        or str(snapshot.get("candidate_commit") or "").strip() != candidate_commit
    ):
        raise ProductionTelemetryError("Snapshot is bound to a different candidate")

    try:
        retained_observation = parse_retained_observation(candidate)
    except RetainedObservationError as exc:
        raise ProductionTelemetryError(str(exc)) from exc
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ProductionTelemetryError("as_of must include an explicit UTC offset")
    reviewed_at = as_of.astimezone(UTC)

    released_at = _parse_date(candidate.get("released_at"), field="candidate.released_at")
    observation_end = _parse_date(
        candidate.get("observation_end"), field="candidate.observation_end"
    )
    window_start = _parse_date(snapshot.get("window_start"), field="snapshot.window_start")
    window_end = _parse_date(snapshot.get("window_end"), field="snapshot.window_end")
    try:
        collected_at = parse_utc_timestamp(
            snapshot.get("collected_at"), field="snapshot.collected_at"
        )
    except RetainedObservationError as exc:
        raise ProductionTelemetryError(str(exc)) from exc
    expected_window_start = retained_observation.first_retained_sample_at.date()
    expected_window_end = retained_observation.eligible_at.date()
    if (
        released_at > expected_window_start
        or observation_end != expected_window_end
        or window_start != expected_window_start
        or window_end != expected_window_end
    ):
        raise ProductionTelemetryError("Snapshot window must exactly match the candidate window")
    if (window_end - window_start).days < 14:
        raise ProductionTelemetryError("Candidate telemetry window is shorter than 14 days")
    if not retained_observation.eligible_at <= collected_at <= reviewed_at:
        raise ProductionTelemetryError(
            "Snapshot collection timestamp is outside the exact review window"
        )

    _validate_collection_metadata(snapshot)
    task_records = _validated_task_records(snapshot, _required_task_keys(catalog))
    prepared = copy.deepcopy(evidence)
    prepared["telemetry"] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "collected_at": utc_text(collected_at),
        "environment": "production",
        "evidence": snapshot_evidence_path,
        "snapshot_sha256": snapshot_sha256,
        "tasks": task_records,
    }
    return prepared


def _repository_evidence_path(path: Path, *, root: Path = ROOT) -> str:
    """Return a repository-relative evidence path without allowing traversal."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ProductionTelemetryError(
            "Snapshot evidence must be stored inside the repository"
        ) from exc
    if not resolved.is_file():
        raise ProductionTelemetryError(f"Snapshot evidence file does not exist: {resolved}")
    return relative.as_posix()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one JSON evidence file."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--as-of",
        help="Exact UTC review timestamp; defaults to the current UTC time.",
    )
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write validated telemetry into cutover evidence; default is a dry run.",
    )
    args = parser.parse_args()

    try:
        snapshot_path = args.snapshot.resolve()
        snapshot_evidence_path = _repository_evidence_path(snapshot_path)
        snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        snapshot = _load_object(snapshot_path)
        catalog = _load_object(args.catalog.resolve())
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        current_time = datetime.now(UTC)
        as_of = parse_utc_timestamp(args.as_of, field="--as-of") if args.as_of else current_time
        if as_of > current_time:
            raise ProductionTelemetryError("--as-of cannot be in the future")
        prepared = build_production_telemetry_evidence(
            snapshot=snapshot,
            catalog=catalog,
            evidence=evidence,
            snapshot_evidence_path=snapshot_evidence_path,
            snapshot_sha256=snapshot_sha256,
            as_of=as_of,
        )
        if args.write_evidence:
            _write_json_atomic(evidence_path, prepared)
    except (
        OSError,
        json.JSONDecodeError,
        ProductionTelemetryError,
        RetainedObservationError,
        ValueError,
    ) as exc:
        print(f"Web-to-TUI production telemetry: FAIL - {exc}")
        return 1

    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    task_count = len(cast(dict[str, Any], prepared["telemetry"])["tasks"])
    print(
        f"Web-to-TUI production telemetry: {mode} - "
        f"tasks={task_count} snapshot_sha256={snapshot_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
