#!/usr/bin/env python
"""Build candidate-bound M5 production telemetry evidence from a reviewed snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
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

from scripts.web_to_tui_candidate_binding import BINDING_VERSION  # noqa: E402
from scripts.web_to_tui_retained_observation import (  # noqa: E402
    RetainedObservationError,
    parse_retained_observation,
    parse_utc_timestamp,
    utc_text,
)

DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
SNAPSHOT_VERSION = "web-to-tui-production-telemetry-snapshot.v2"
LOW_FREQUENCY_SNAPSHOT_VERSION = "web-to-tui-production-telemetry-snapshot.v3"
LOW_FREQUENCY_ACCEPTANCE_VERSION = "web-to-tui-low-frequency-task-acceptance.v1"
RAW_RESULTS_VERSION = "web-to-tui-prometheus-results.v1"
CLEANUP_LOW_FREQUENCY_SNAPSHOT_VERSION = "web-to-tui-cleanup-wave-telemetry-snapshot.v2"
CLEANUP_LOW_FREQUENCY_ACCEPTANCE_VERSION = "web-to-tui-low-frequency-task-acceptance.v1"
CLEANUP_LOW_FREQUENCY_QUERY_KEYS = frozenset(
    {"baseline_requests", "baseline_errors", "candidate_requests", "candidate_errors"}
)
CLEANUP_LOW_FREQUENCY_QUERIES = {
    "baseline_requests": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="classic",event_type=~"entry|execution",
          outcome=~"success|client_error|server_error"
        }[48h])))
    """,
    "baseline_errors": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="classic",event_type=~"entry|execution",
          outcome=~"client_error|server_error"
        }[48h])))
    """,
    "candidate_requests": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="tui",event_type="execution",
          outcome=~"success|client_error|server_error"
        }[48h])))
    """,
    "candidate_errors": """
        round(sum by (task_key) (increase(web_to_tui_migration_events_total{
          surface="tui",event_type="execution",
          outcome=~"client_error|server_error"
        }[48h])))
    """,
}
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

    return _parse_object_bytes(path.read_bytes())


def _parse_object_bytes(content: bytes) -> dict[str, Any]:
    """Parse an already-read JSON boundary without reopening its source."""

    payload = cast(Any, json.loads(content))
    if not isinstance(payload, dict):
        raise ProductionTelemetryError("Expected a JSON object")
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


def _verified_reference_bytes(value: object, *, root: Path) -> bytes:
    """Read the exact digest-bound artifact bytes without repository escape."""

    reference = _mapping(value)
    location = reference.get("evidence")
    digest = reference.get("sha256")
    if (
        not isinstance(location, str)
        or not location
        or not isinstance(digest, str)
        or not SHA256_PATTERN.fullmatch(digest)
    ):
        raise ProductionTelemetryError("Missing digest-bound telemetry artifact")
    relative = Path(location)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ProductionTelemetryError("Telemetry artifact must exist inside evidence root")
    content = path.read_bytes()
    if not content or hashlib.sha256(content).hexdigest() != digest:
        raise ProductionTelemetryError("Telemetry artifact SHA-256 mismatch")
    return content


def _verified_json_reference(value: object, *, root: Path) -> dict[str, Any]:
    """Parse the same verified bytes without a second unverified file open."""

    return _parse_object_bytes(_verified_reference_bytes(value, root=root))


def parse_prometheus_result_vectors(
    reference: object,
    *,
    root: Path,
    candidate_binding: dict[str, Any],
    endpoint: str,
    queries: dict[str, str],
    query_at: datetime | dict[str, datetime],
    query_keys: frozenset[str],
    expected_metadata: dict[str, object] | None = None,
) -> dict[str, dict[str, int]]:
    """Parse digest-bound Prometheus vectors without converting absent series to zero."""

    raw = _verified_json_reference(reference, root=root)
    if (
        raw.get("version") != RAW_RESULTS_VERSION
        or raw.get("candidate_binding") != candidate_binding
        or raw.get("endpoint") != endpoint
        or raw.get("queries") != queries
        or not candidate_binding
    ):
        raise ProductionTelemetryError("Raw query artifact candidate or collection mismatch")
    for key, expected in (expected_metadata or {}).items():
        if raw.get(key) != expected:
            raise ProductionTelemetryError(f"Raw query artifact {key} mismatch")
    if isinstance(query_at, datetime):
        if parse_utc_timestamp(raw.get("query_at"), field="query_at") != query_at:
            raise ProductionTelemetryError("Raw query instant is not the exact eligible instant")
        query_times = dict.fromkeys(query_keys, query_at)
    else:
        raw_query_at = _mapping(raw.get("query_at"))
        if set(raw_query_at) != query_keys:
            raise ProductionTelemetryError("Raw query artifact needs an instant for every query")
        query_times = query_at
        for key, instant in query_times.items():
            if parse_utc_timestamp(raw_query_at.get(key), field=f"query_at.{key}") != instant:
                raise ProductionTelemetryError(
                    "Raw query instant is not the exact eligible instant"
                )
    results = _mapping(raw.get("results"))
    if set(results) != query_keys:
        raise ProductionTelemetryError("Raw query artifact lacks an exact query response set")
    counts: dict[str, dict[str, int]] = {}
    for key in sorted(query_keys):
        response = _mapping(results[key])
        data = _mapping(response.get("data"))
        if (
            response.get("status") != "success"
            or data.get("resultType") != "vector"
            or not isinstance(data.get("result"), list)
        ):
            raise ProductionTelemetryError("Raw telemetry query did not return a successful vector")
        values: dict[str, int] = {}
        for item in cast(list[object], data["result"]):
            series = _mapping(item)
            task_key = _mapping(series.get("metric")).get("task_key")
            sample = series.get("value")
            if (
                not isinstance(task_key, str)
                or not task_key
                or task_key in values
                or not isinstance(sample, list)
                or len(sample) != 2
                or isinstance(sample[0], bool)
                or not isinstance(sample[0], (int, float))
                or not isinstance(sample[1], str)
            ):
                raise ProductionTelemetryError(
                    "Raw telemetry has malformed or duplicate task series"
                )
            try:
                timestamp = float(sample[0])
                number = float(sample[1])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ProductionTelemetryError("Raw telemetry sample is not numeric") from exc
            if (
                not math.isfinite(timestamp)
                or abs(timestamp - query_times[key].timestamp()) > 0.001
                or not math.isfinite(number)
                or number < 0
                or not number.is_integer()
            ):
                raise ProductionTelemetryError(
                    "Raw telemetry sample is stale or not a non-negative count"
                )
            values[task_key] = int(number)
        counts[key] = values
    return counts


def _raw_task_counts(
    snapshot: dict[str, Any], candidate_binding: dict[str, Any], *, query_at: datetime, root: Path
) -> dict[str, dict[str, int | None]]:
    """Preserve missing query series as unknown and verify all supplied v3 counts."""

    collection = _mapping(snapshot.get("collection"))
    counts = parse_prometheus_result_vectors(
        collection.get("raw_results"),
        root=root,
        candidate_binding=candidate_binding,
        endpoint=str(collection.get("endpoint") or ""),
        queries=cast(dict[str, str], collection.get("queries")),
        query_at=query_at,
        query_keys=QUERY_KEYS,
        expected_metadata={
            **{key: snapshot.get(key) for key in ("window_start", "window_end", "collected_at")},
            "query_at": collection.get("query_at"),
        },
    )
    nullable_counts = {
        query: {task: values.get(task) for task in values} for query, values in counts.items()
    }
    # A missing series is unknown. Populate each task's absent entry only when
    # the caller's catalog denominator asks for it later.
    counts_with_none: dict[str, dict[str, int | None]] = nullable_counts
    if not any(value > 0 for value in counts["tui_task_requests"].values()):
        raise ProductionTelemetryError(
            "Global TUI execution telemetry is absent; low-frequency acceptance cannot waive collection"
        )
    return counts_with_none


def _validate_v3_binding(evidence: dict[str, Any]) -> None:
    """Require the complete immutable candidate identity for v3 acceptance."""

    candidate = _mapping(evidence.get("candidate"))
    binding = _mapping(candidate.get("binding"))
    keys = {
        "version",
        "candidate_version",
        "candidate_commit",
        "matrix_sha256",
        "graph_sha256",
        "schema_version",
        "runtime_version",
        "runtime_build_id",
        "runtime_manifest_sha256",
    }
    if (
        set(binding) != keys
        or binding.get("version") != BINDING_VERSION
        or binding.get("candidate_version") != candidate.get("stable_version")
        or binding.get("candidate_commit") != candidate.get("candidate_commit")
        or binding.get("matrix_sha256") != evidence.get("source_sha256")
    ):
        raise ProductionTelemetryError("v3 telemetry requires the full candidate binding")
    if any(not isinstance(binding[key], str) or not binding[key].strip() for key in keys):
        raise ProductionTelemetryError("v3 candidate binding is incomplete")
    if any(
        not SHA256_PATTERN.fullmatch(binding[key])
        for key in ("matrix_sha256", "graph_sha256", "runtime_manifest_sha256")
    ):
        raise ProductionTelemetryError("v3 candidate binding digest is invalid")


def _validate_low_frequency_acceptance(
    record: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    evidence: dict[str, Any],
    catalog: dict[str, Any],
    as_of: datetime,
    root: Path,
) -> None:
    """Require same-candidate task UAT, explicit risk acceptance and independent review."""

    candidate = _mapping(evidence.get("candidate"))
    binding = _mapping(candidate.get("binding"))
    task_key = record["task_key"]
    wave = snapshot.get("acceptance_wave_id")
    route_pages = sorted(
        str(route["url_name"])
        for route in catalog.get("classic_routes", [])
        if isinstance(route, dict) and route.get("task_key") == task_key and route.get("url_name")
    )
    validate_low_frequency_task_acceptance(
        record.get("low_frequency_exception"),
        candidate_binding=binding,
        task_key=task_key,
        wave_id=str(wave or ""),
        route_pages=route_pages,
        collected_at=parse_utc_timestamp(snapshot.get("collected_at"), field="collected_at"),
        released_at=_parse_date(candidate.get("released_at"), field="released_at"),
        as_of=as_of,
        root=root,
    )


def validate_low_frequency_task_acceptance(
    reference: object,
    *,
    candidate_binding: dict[str, Any],
    task_key: str,
    wave_id: str,
    route_pages: list[str],
    collected_at: datetime,
    released_at: date | datetime,
    as_of: datetime,
    root: Path,
) -> None:
    """Validate exact task UAT, explicit risk acceptance and independent review."""

    report = _verified_json_reference(reference, root=root)
    if (
        report.get("version") != LOW_FREQUENCY_ACCEPTANCE_VERSION
        or not candidate_binding
        or report.get("candidate_binding") != candidate_binding
        or report.get("task_key") != task_key
    ):
        raise ProductionTelemetryError("Low-frequency acceptance candidate/task mismatch")
    if (
        not wave_id.strip()
        or report.get("wave_id") != wave_id
        or not route_pages
        or report.get("route_pages") != route_pages
    ):
        raise ProductionTelemetryError("Low-frequency acceptance route/wave mismatch")
    if (
        report.get("sample_status") != "insufficient_sample"
        or report.get("error_comparison") != "not_applicable"
        or not isinstance(report.get("reason"), str)
        or not report["reason"].strip()
    ):
        raise ProductionTelemetryError(
            "Low-frequency acceptance must explicitly accept statistical uncertainty"
        )
    owner = _mapping(report.get("owner"))
    reviewer = _mapping(report.get("reviewer"))
    performer = report.get("performed_by")
    owner_actor, reviewer_actor = owner.get("actor"), reviewer.get("actor")
    if not all(
        isinstance(actor, str) and actor.strip()
        for actor in (owner_actor, reviewer_actor, performer)
    ):
        raise ProductionTelemetryError(
            "Low-frequency acceptance needs named task owner, performer and reviewer"
        )
    if (
        str(reviewer_actor).strip().casefold()
        in {str(owner_actor).strip().casefold(), str(performer).strip().casefold()}
        or owner.get("risk_accepted") is not True
        or reviewer.get("approved") is not True
    ):
        raise ProductionTelemetryError(
            "Low-frequency acceptance requires explicit risk acceptance and independent review"
        )
    performed_at = parse_utc_timestamp(report.get("performed_at"), field="performed_at")
    accepted_at = parse_utc_timestamp(owner.get("accepted_at"), field="accepted_at")
    reviewed_at = parse_utc_timestamp(reviewer.get("reviewed_at"), field="reviewed_at")
    expires_at = parse_utc_timestamp(report.get("expires_at"), field="expires_at")
    released_before_performance = (
        performed_at < released_at
        if isinstance(released_at, datetime)
        else performed_at.date() < released_at
    )
    if (
        released_before_performance
        or not performed_at <= collected_at <= accepted_at <= reviewed_at <= as_of < expires_at
    ):
        raise ProductionTelemetryError("Low-frequency acceptance is premature, stale or expired")
    scopes = _mapping(report.get("uat"))
    required_scopes = {"primary_task", "clear_result", "error_recovery", "permission"}
    if set(scopes) != required_scopes:
        raise ProductionTelemetryError("Low-frequency task UAT coverage is incomplete")
    for scope in required_scopes:
        result = _mapping(scopes[scope])
        if result.get("passed") is not True:
            raise ProductionTelemetryError("Low-frequency task UAT has no passing evidence")
        _verified_reference_bytes(result.get("evidence"), root=root)


def validate_cleanup_wave_telemetry(
    snapshot: dict[str, Any],
    *,
    task_keys: frozenset[str],
    known_task_keys: frozenset[str],
    route_pages_by_task: dict[str, list[str]],
    candidate_binding: dict[str, Any],
    wave_id: str,
    deployed_at: datetime,
    evaluated_at: datetime,
    root: Path,
) -> tuple[datetime, datetime, datetime, list[dict[str, Any]]]:
    """Validate v2 cleanup telemetry and derive per-task metrics from raw vectors."""

    expected_fields = {
        "version",
        "environment",
        "wave",
        "candidate_binding",
        "baseline_window",
        "candidate_window",
        "collected_at",
        "collection",
        "queries",
        "query_at",
        "raw_results",
        "tasks",
    }
    if (
        set(snapshot) != expected_fields
        or snapshot.get("version") != CLEANUP_LOW_FREQUENCY_SNAPSHOT_VERSION
        or snapshot.get("environment") != "production"
        or snapshot.get("wave") != wave_id
        or snapshot.get("candidate_binding") != candidate_binding
        or not candidate_binding
        or not task_keys
        or not task_keys.issubset(known_task_keys)
    ):
        raise ProductionTelemetryError("Cleanup telemetry v2 binding or schema is invalid")
    collection = _mapping(snapshot.get("collection"))
    if set(collection) != {"system", "endpoint", "query_id", "collected_by"}:
        raise ProductionTelemetryError("Cleanup telemetry collection metadata is incomplete")
    endpoint = str(collection.get("endpoint") or "").strip()
    parsed_endpoint = urlparse(endpoint)
    if (
        collection.get("system") != "prometheus"
        or collection.get("query_id") != "web-to-tui-wave-error-rate-by-task.v2"
        or not isinstance(collection.get("collected_by"), str)
        or not str(collection.get("collected_by")).strip()
        or parsed_endpoint.scheme != "https"
        or not parsed_endpoint.netloc
        or parsed_endpoint.username
        or parsed_endpoint.password
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise ProductionTelemetryError("Cleanup telemetry collector is not an approved source")

    baseline = _mapping(snapshot.get("baseline_window"))
    candidate = _mapping(snapshot.get("candidate_window"))
    if set(baseline) != {"start", "end"} or set(candidate) != {"start", "end"}:
        raise ProductionTelemetryError("Cleanup telemetry windows are malformed")
    baseline_start = parse_utc_timestamp(baseline.get("start"), field="baseline_window.start")
    baseline_end = parse_utc_timestamp(baseline.get("end"), field="baseline_window.end")
    observed_from = parse_utc_timestamp(candidate.get("start"), field="candidate_window.start")
    observed_until = parse_utc_timestamp(candidate.get("end"), field="candidate_window.end")
    collected_at = parse_utc_timestamp(snapshot.get("collected_at"), field="collected_at")
    exact_window = timedelta(hours=48)
    if (
        baseline_end - baseline_start != exact_window
        or observed_until - observed_from != exact_window
        or baseline_end > observed_from
        or observed_from < deployed_at
        or not observed_until <= collected_at <= evaluated_at
        or collected_at - observed_until > timedelta(hours=24)
    ):
        raise ProductionTelemetryError("Cleanup telemetry does not prove eligible 48-hour windows")

    queries = _mapping(snapshot.get("queries"))
    if set(queries) != CLEANUP_LOW_FREQUENCY_QUERY_KEYS or any(
        not isinstance(queries.get(key), str)
        or _normalize_query(str(queries.get(key)))
        != _normalize_query(CLEANUP_LOW_FREQUENCY_QUERIES[key])
        for key in CLEANUP_LOW_FREQUENCY_QUERY_KEYS
    ):
        raise ProductionTelemetryError(
            "Cleanup telemetry queries differ from the approved contract"
        )
    expected_query_times = {
        "baseline_requests": baseline_end,
        "baseline_errors": baseline_end,
        "candidate_requests": observed_until,
        "candidate_errors": observed_until,
    }
    raw_query_times = _mapping(snapshot.get("query_at"))
    if set(raw_query_times) != CLEANUP_LOW_FREQUENCY_QUERY_KEYS or any(
        parse_utc_timestamp(raw_query_times.get(key), field=f"query_at.{key}")
        != expected_query_times[key]
        for key in CLEANUP_LOW_FREQUENCY_QUERY_KEYS
    ):
        raise ProductionTelemetryError(
            "Cleanup telemetry query times are not the eligible endpoints"
        )
    raw_counts = parse_prometheus_result_vectors(
        snapshot.get("raw_results"),
        root=root,
        candidate_binding=candidate_binding,
        endpoint=endpoint,
        queries=cast(dict[str, str], queries),
        query_at=expected_query_times,
        query_keys=CLEANUP_LOW_FREQUENCY_QUERY_KEYS,
        expected_metadata={
            "collected_at": snapshot.get("collected_at"),
            "baseline_window": baseline,
            "candidate_window": candidate,
        },
    )
    if any(not set(values).issubset(known_task_keys) for values in raw_counts.values()):
        raise ProductionTelemetryError("Cleanup raw telemetry contains an unknown catalog task")
    if not any(value > 0 for value in raw_counts["candidate_requests"].values()):
        raise ProductionTelemetryError("Global TUI request collection is empty")

    raw_tasks = snapshot.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ProductionTelemetryError("Cleanup telemetry tasks must be an array")
    records: dict[str, dict[str, Any]] = {}
    count_keys = (
        "baseline_requests",
        "baseline_errors",
        "candidate_requests",
        "candidate_errors",
    )
    for raw_task in cast(list[object], raw_tasks):
        task = _mapping(raw_task)
        if not set(task).issubset({"task_key", *count_keys, "low_frequency_exception"}) or not set(
            {"task_key", *count_keys}
        ).issubset(task):
            raise ProductionTelemetryError("Cleanup telemetry task fields are malformed")
        task_key = task.get("task_key")
        if not isinstance(task_key, str) or not task_key or task_key in records:
            raise ProductionTelemetryError("Cleanup telemetry task keys are blank or duplicated")
        records[task_key] = task
    if set(records) != task_keys or set(route_pages_by_task) != task_keys:
        raise ProductionTelemetryError("Cleanup telemetry task coverage differs from exact routes")

    metrics: list[dict[str, Any]] = []
    for task_key in sorted(task_keys):
        task = records[task_key]
        counts: dict[str, int | None] = {}
        for key in count_keys:
            value = task.get(key)
            if value is not None:
                value = _non_negative_int(value, field=f"{task_key}.{key}")
            if raw_counts[key].get(task_key) != value:
                raise ProductionTelemetryError("Cleanup declared telemetry differs from raw query")
            counts[key] = cast(int | None, value)
        baseline_requests = counts["baseline_requests"]
        baseline_errors = counts["baseline_errors"]
        candidate_requests = counts["candidate_requests"]
        candidate_errors = counts["candidate_errors"]
        if (
            baseline_errors is not None
            and baseline_requests is not None
            and baseline_errors > baseline_requests
        ) or (
            candidate_errors is not None
            and candidate_requests is not None
            and candidate_errors > candidate_requests
        ):
            raise ProductionTelemetryError("Cleanup telemetry errors exceed request counts")
        sufficient = (
            all(
                isinstance(value, int) and value >= 20
                for value in (baseline_requests, candidate_requests)
            )
            and baseline_errors is not None
            and candidate_errors is not None
        )
        metric: dict[str, Any] = {"task_key": task_key, **counts}
        if sufficient:
            assert isinstance(baseline_requests, int)
            assert isinstance(candidate_requests, int)
            assert isinstance(baseline_errors, int)
            assert isinstance(candidate_errors, int)
            if candidate_errors / candidate_requests - baseline_errors / baseline_requests > 0.005:
                raise ProductionTelemetryError(
                    f"Cleanup error regression threshold failed: {task_key}"
                )
            if "low_frequency_exception" in task:
                raise ProductionTelemetryError(
                    "Sufficient samples cannot use low-frequency acceptance"
                )
            metric.update(sample_status="sufficient_sample", error_comparison="passed")
        else:
            if not isinstance(candidate_requests, int) or candidate_requests <= 0:
                raise ProductionTelemetryError("Low-frequency task needs a real candidate request")
            if any(
                error is not None and error > 0 for error in (baseline_errors, candidate_errors)
            ):
                raise ProductionTelemetryError("Observed cleanup telemetry errors cannot be waived")
            reference = task.get("low_frequency_exception")
            if reference is None:
                raise ProductionTelemetryError(
                    "Low-frequency task lacks independent UAT acceptance"
                )
            validate_low_frequency_task_acceptance(
                reference,
                candidate_binding=candidate_binding,
                task_key=task_key,
                wave_id=wave_id,
                route_pages=route_pages_by_task[task_key],
                collected_at=collected_at,
                released_at=deployed_at,
                as_of=evaluated_at,
                root=root,
            )
            metric.update(
                sample_status="insufficient_sample",
                error_comparison="not_applicable",
                low_frequency_exception=task["low_frequency_exception"],
            )
        metrics.append(metric)
    return observed_from, observed_until, collected_at, metrics


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
    *,
    evidence: dict[str, Any],
    catalog: dict[str, Any],
    as_of: datetime,
    root: Path,
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
    v3 = snapshot.get("version") == LOW_FREQUENCY_SNAPSHOT_VERSION
    raw_counts = (
        _raw_task_counts(
            snapshot,
            _mapping(_mapping(evidence.get("candidate")).get("binding")),
            query_at=parse_retained_observation(_mapping(evidence.get("candidate"))).eligible_at,
            root=root,
        )
        if v3
        else None
    )
    for task_key in sorted(required_tasks):
        record = records[task_key]
        try:
            counts: dict[str, int | None] = {}
            for key in QUERY_KEYS:
                value = record.get(key)
                if key not in record:
                    raise ProductionTelemetryError("Missing count field")
                counts[key] = (
                    None
                    if v3 and value is None
                    else _non_negative_int(value, field=f"{task_key}.{key}")
                )
                if raw_counts is not None and counts[key] != raw_counts[key].get(task_key):
                    raise ProductionTelemetryError("Task counts do not match raw query series")
        except ProductionTelemetryError:
            invalid.append(task_key)
            continue

        classic_entries, tui_entries = counts["classic_entries"], counts["tui_entries"]
        classic_requests, tui_requests = (
            counts["classic_task_requests"],
            counts["tui_task_requests"],
        )
        classic_errors, tui_errors = counts["classic_task_errors"], counts["tui_task_errors"]
        entry_samples = (
            classic_entries + tui_entries
            if classic_entries is not None and tui_entries is not None
            else None
        )
        exception = record.get("low_frequency_exception")
        insufficient = (
            entry_samples is None
            or entry_samples < 20
            or classic_requests is None
            or classic_requests < 20
            or tui_requests is None
            or tui_requests < 20
        )
        if (
            entry_samples is not None
            and entry_samples >= 20
            and classic_entries is not None
            and classic_entries / entry_samples > 0.05
        ):
            invalid.append(task_key)
            continue
        if insufficient:
            if (
                not v3
                or not exception
                or tui_requests is None
                or tui_requests <= 0
                or any(error is not None and error > 0 for error in (classic_errors, tui_errors))
            ):
                invalid.append(task_key)
                continue
            _validate_low_frequency_acceptance(
                record,
                snapshot=snapshot,
                evidence=evidence,
                catalog=catalog,
                as_of=as_of,
                root=root,
            )
        elif (
            classic_requests is None
            or tui_requests is None
            or classic_errors is None
            or tui_errors is None
            or classic_errors > classic_requests
            or tui_errors > tui_requests
            or tui_errors / tui_requests - classic_errors / classic_requests > 0.005
            or exception is not None
        ):
            invalid.append(task_key)
            continue
        result: dict[str, Any] = {
            "task_key": task_key,
            **counts,
            "low_frequency_exception": exception,
        }
        if v3:
            result.update(
                sample_status="insufficient_sample" if insufficient else "sufficient",
                error_comparison="not_applicable" if insufficient else "passed",
            )
        validated.append(result)
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
    evidence_root: Path = ROOT,
) -> dict[str, Any]:
    """Return cutover evidence populated from one fully validated production snapshot."""

    if snapshot.get("version") not in {SNAPSHOT_VERSION, LOW_FREQUENCY_SNAPSHOT_VERSION}:
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
    if snapshot.get("version") == LOW_FREQUENCY_SNAPSHOT_VERSION:
        _validate_v3_binding(evidence)
    task_records = _validated_task_records(
        snapshot,
        _required_task_keys(catalog),
        evidence=evidence,
        catalog=catalog,
        as_of=reviewed_at,
        root=evidence_root,
    )
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
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
        snapshot = _parse_object_bytes(snapshot_bytes)
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
