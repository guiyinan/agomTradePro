#!/usr/bin/env python
"""Record one candidate-bound M5-B cleanup wave from raw production evidence.

The recorder derives deletion scope, route count, task coverage, rollback
commits, error comparisons, defect counts, and observation duration itself. It
does not accept a caller-authored pass flag or caller-authored observation
dates. A wave is written only when one immutable candidate adds exactly one
contiguous M5-B wave and a deployment preflight plus three structured
production snapshots prove at least 48 hours of post-deployment observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_web_to_tui_cleanup_guard as cleanup_guard  # noqa: E402
from scripts import start_web_to_tui_observation as observation_start  # noqa: E402
from scripts.web_to_tui_candidate_binding import (  # noqa: E402
    CandidateBinding,
    binding_matches,
)

DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
DEFAULT_GRAPH = ROOT / "config/tui/published/tui_operation_graph.published.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/tui/agomtui-runtime.manifest.json"
DEFAULT_SCHEMA = ROOT / "config/tui/schema/web_to_tui_cleanup_wave_recording.v1.schema.json"
DEFAULT_DEPLOYMENT_SCHEMA = (
    ROOT / "config/tui/schema/web_to_tui_deployment_preflight_attestation.v1.schema.json"
)
DEFAULT_ARTIFACT_ROOT = ROOT / "config/tui/migration/evidence/cleanup-waves"

TELEMETRY_VERSION = "web-to-tui-cleanup-wave-telemetry-snapshot.v1"
DEFECT_VERSION = "web-to-tui-cleanup-wave-defect-snapshot.v1"
SCHEDULED_CYCLE_VERSION = "web-to-tui-cleanup-wave-scheduled-cycle-snapshot.v1"
WAVE_RECORD_VERSION = "web-to-tui-cleanup-wave-record.v1"
DEFECT_QUERY_SCOPE = "created_or_open_during_wave_window"
TELEMETRY_QUERY_ID = "web-to-tui-wave-error-rate-by-task.v1"
SCHEDULED_CYCLE_QUERY_ID = "web-to-tui-wave-scheduled-cycle.v1"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_COLLECTION_LAG = timedelta(hours=24)


class CleanupWaveRecordingError(RuntimeError):
    """Raised when a cleanup wave cannot be proven from immutable evidence."""


@dataclass(frozen=True)
class WaveScope:
    """One matrix-derived M5-B deletion wave and its comparable tasks."""

    wave: str
    deleted_paths: tuple[str, ...]
    route_count: int
    task_keys: frozenset[str]
    rollback_commits: dict[str, str]
    owners: tuple[str, ...]
    reviewers: tuple[str, ...]


@dataclass(frozen=True)
class RawArtifact:
    """One validated source snapshot and its external SHA reference."""

    path: Path
    reference: str
    sha256: str
    payload: dict[str, Any]
    git_commit: str | None = None
    git_committed_at: datetime | None = None


@dataclass(frozen=True)
class WaveBundle:
    """Fully derived artifacts and cutover projection for one wave."""

    rollback_manifest: dict[str, Any]
    observation_ledger: dict[str, Any]
    wave_record: dict[str, Any]
    projection: dict[str, Any]


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one JSON value to an object."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise CleanupWaveRecordingError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _normalized_bytes(value: bytes) -> bytes:
    """Normalize UTF-8 line endings for Git-compatible source identity."""

    text = value.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    """Return one canonical SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    """Serialize one deterministic JSON evidence artifact."""

    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_datetime(value: object, *, field: str) -> datetime:
    """Parse one required timezone-aware ISO-8601 timestamp."""

    if not isinstance(value, str) or not value.strip():
        raise CleanupWaveRecordingError(f"{field} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CleanupWaveRecordingError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CleanupWaveRecordingError(f"{field} must include a timezone offset")
    return parsed


def _iso_utc(value: datetime) -> str:
    """Return one aware timestamp normalized to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise CleanupWaveRecordingError("recorder clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _non_negative_int(value: object, *, field: str) -> int:
    """Return one non-negative integer while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CleanupWaveRecordingError(f"{field} must be a non-negative integer")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], *, label: str) -> None:
    """Reject caller-added assertions and incomplete raw records."""

    actual = set(value)
    if actual != expected:
        raise CleanupWaveRecordingError(
            f"{label} fields mismatch: missing={sorted(expected - actual)}; "
            f"extra={sorted(actual - expected)}"
        )


def _credential_free_https(value: object, *, field: str) -> str:
    """Validate an auditable HTTPS origin without embedded credentials."""

    text = str(value or "").strip()
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise CleanupWaveRecordingError(f"{field} must be a credential-free HTTPS origin")
    return text


def _resolve_commit(revision: str) -> str:
    """Resolve one full candidate commit reachable from the current HEAD."""

    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    commit = result.stdout.strip().lower()
    if result.returncode or not COMMIT_PATTERN.fullmatch(commit):
        raise CleanupWaveRecordingError(f"candidate ref is not a full commit: {revision}")
    if not cleanup_guard._git_commit_is_ancestor(commit, root=ROOT):
        raise CleanupWaveRecordingError("cleanup candidate is not reachable from HEAD")
    return commit


def _git_blob(commit: str, path: Path) -> bytes:
    """Read one required repository source from an immutable candidate."""

    content = cleanup_guard._git_source_bytes(commit, path, root=ROOT)
    if content is None:
        raise CleanupWaveRecordingError(f"candidate source is missing: {path}")
    return cast(bytes, content)


def build_candidate_snapshot(
    *,
    candidate_version: str,
    candidate_revision: str,
    matrix_path: Path = DEFAULT_MATRIX,
    catalog_path: Path = DEFAULT_CATALOG,
    graph_path: Path = DEFAULT_GRAPH,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
) -> cleanup_guard.CandidateSnapshot:
    """Build a cleanup candidate entirely from its committed Git snapshot."""

    if not VERSION_PATTERN.fullmatch(candidate_version):
        raise CleanupWaveRecordingError("candidate version is invalid")
    commit = _resolve_commit(candidate_revision)
    matrix = _git_blob(commit, matrix_path)
    graph_bytes = _git_blob(commit, graph_path)
    runtime_bytes = _git_blob(commit, runtime_manifest_path)
    try:
        graph = _mapping(json.loads(graph_bytes))
        runtime = _mapping(json.loads(runtime_bytes))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanupWaveRecordingError("candidate graph/runtime JSON is invalid") from exc
    binding: CandidateBinding = {
        "version": cleanup_guard.BINDING_VERSION,
        "candidate_version": candidate_version,
        "candidate_commit": commit,
        "matrix_sha256": _sha256(_normalized_bytes(matrix)),
        "graph_sha256": _sha256(_normalized_bytes(graph_bytes)),
        "schema_version": str(graph.get("schema_version") or "").strip(),
        "runtime_version": str(runtime.get("version") or "").strip(),
        "runtime_build_id": str(runtime.get("build_id") or "").strip(),
        "runtime_manifest_sha256": _sha256(_normalized_bytes(runtime_bytes)),
    }
    snapshot = cleanup_guard._candidate_snapshot(
        binding,
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_manifest_path,
        repository_root=ROOT,
    )
    if snapshot is None:
        raise CleanupWaveRecordingError("cleanup candidate binding/catalog is invalid")
    for path in (matrix_path, catalog_path, graph_path, runtime_manifest_path):
        candidate_bytes = _git_blob(commit, path)
        if not path.is_file() or _normalized_bytes(path.read_bytes()) != _normalized_bytes(
            candidate_bytes
        ):
            raise CleanupWaveRecordingError(
                f"working source differs from cleanup candidate: {path.relative_to(ROOT)}"
            )
    return snapshot


def _rows_by_path(matrix_bytes: bytes) -> dict[str, dict[str, str]]:
    """Return unique matrix rows keyed by normalized template path."""

    rows: dict[str, dict[str, str]] = {}
    for row in cleanup_guard._matrix_rows_from_bytes(matrix_bytes):
        path = str(row.get("template_path") or "").strip().replace("\\", "/")
        if not path or path in rows:
            raise CleanupWaveRecordingError("matrix contains a blank or duplicate template path")
        rows[path] = row
    return rows


def _catalog_task_map(catalog_payload: dict[str, Any]) -> dict[str, set[str]]:
    """Map each candidate route template to its bounded telemetry task keys."""

    raw_routes = catalog_payload.get("classic_routes")
    if not isinstance(raw_routes, list):
        raise CleanupWaveRecordingError("candidate catalog lacks classic_routes")
    tasks_by_path: dict[str, set[str]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for raw_route in raw_routes:
        route = _mapping(raw_route)
        path = str(route.get("template_path") or "").strip()
        task_key = str(route.get("task_key") or "").strip()
        if not path or not task_key:
            raise CleanupWaveRecordingError("candidate catalog has blank route identity")
        pair = (path, task_key)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        tasks_by_path.setdefault(path, set()).add(task_key)
    return tasks_by_path


def derive_wave_scope(
    *,
    authorized_matrix: bytes,
    candidate_matrix: bytes,
    candidate_catalog: dict[str, Any],
    candidate_binding: CandidateBinding,
    existing_wave_values: object,
) -> WaveScope:
    """Derive exactly one next wave from cumulative committed matrix state."""

    authorized_rows = _rows_by_path(authorized_matrix)
    candidate_rows = _rows_by_path(candidate_matrix)
    new_deleted = {
        path
        for path, row in candidate_rows.items()
        if row.get("status") == "deleted" and path not in cleanup_guard.M0_D_BASELINE_PATHS
    }
    if not new_deleted:
        raise CleanupWaveRecordingError("candidate contains no M5-B cleanup deletion")
    expected_by_wave: dict[str, set[str]] = {}
    for path in new_deleted:
        row = candidate_rows[path]
        base = authorized_rows.get(path)
        wave = str(row.get("wave") or "").strip()
        if (
            base is None
            or base.get("status") == "deleted"
            or row.get("destination_class") not in {"A", "B"}
            or cleanup_guard.WAVE_PATTERN.fullmatch(wave) is None
            or not str(row.get("owner") or "").strip()
            or not str(row.get("reviewer") or "").strip()
            or str(row.get("owner") or "").strip() == str(row.get("reviewer") or "").strip()
        ):
            raise CleanupWaveRecordingError(f"invalid M5-B deletion lifecycle: {path}")
        expected_by_wave.setdefault(wave, set()).add(path)
    wave_numbers = {
        wave: int(cast(re.Match[str], cleanup_guard.WAVE_PATTERN.fullmatch(wave)).group(1))
        for wave in expected_by_wave
    }
    if sorted(wave_numbers.values()) != list(range(1, len(wave_numbers) + 1)):
        raise CleanupWaveRecordingError("M5-B waves must be contiguous from M5-B-W1")
    ordered_waves = sorted(expected_by_wave, key=wave_numbers.__getitem__)
    existing_values = existing_wave_values if isinstance(existing_wave_values, list) else []
    existing_waves = [str(_mapping(value).get("wave") or "").strip() for value in existing_values]
    if len(existing_waves) != len(set(existing_waves)):
        raise CleanupWaveRecordingError("existing cleanup waves are duplicated")
    if existing_waves != ordered_waves[: len(existing_waves)]:
        raise CleanupWaveRecordingError(
            "existing cleanup waves are not the exact contiguous prefix"
        )
    missing_waves = ordered_waves[len(existing_waves) :]
    if len(missing_waves) != 1:
        raise CleanupWaveRecordingError(
            "candidate must add exactly one cleanup wave beyond existing evidence"
        )
    wave = missing_waves[0]
    if wave != ordered_waves[-1]:
        raise CleanupWaveRecordingError("only the latest matrix wave can be recorded")
    deleted_paths = tuple(sorted(expected_by_wave[wave]))
    route_count = sum(
        candidate_rows[path].get("template_role") == "route_page" for path in deleted_paths
    )
    if route_count == 0 or route_count > 10:
        raise CleanupWaveRecordingError(
            f"cleanup wave route count must be within 1..10; actual={route_count}"
        )
    task_map = _catalog_task_map(candidate_catalog)
    route_paths = {
        path for path in deleted_paths if candidate_rows[path].get("template_role") == "route_page"
    }
    task_keys = frozenset(task for path in route_paths for task in task_map.get(path, set()))
    if not task_keys or any(path not in task_map for path in route_paths):
        raise CleanupWaveRecordingError("candidate catalog does not cover every deleted route")
    rollback_commits = {
        path: str(candidate_rows[path].get("rollback_commit") or "").strip().lower()
        for path in deleted_paths
    }
    if any(
        not COMMIT_PATTERN.fullmatch(commit)
        or not cleanup_guard._git_commit_is_ancestor(
            commit,
            root=ROOT,
            descendant=candidate_binding["candidate_commit"],
        )
        for commit in rollback_commits.values()
    ):
        raise CleanupWaveRecordingError("matrix rollback commits are invalid for candidate history")
    owners = tuple(sorted({str(candidate_rows[path]["owner"]).strip() for path in deleted_paths}))
    reviewers = tuple(
        sorted({str(candidate_rows[path]["reviewer"]).strip() for path in deleted_paths})
    )
    if ",".join(owners) == ",".join(reviewers):
        raise CleanupWaveRecordingError(
            "cleanup wave owner and reviewer sets must remain independent"
        )
    return WaveScope(
        wave=wave,
        deleted_paths=deleted_paths,
        route_count=route_count,
        task_keys=task_keys,
        rollback_commits=rollback_commits,
        owners=owners,
        reviewers=reviewers,
    )


def _validate_schema(payload: dict[str, Any], schema_path: Path) -> None:
    """Validate one raw or generated artifact against the checked-in schema."""

    try:
        schema = _load_object(schema_path)
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        validator_type(schema).validate(payload)
    except (SchemaError, ValidationError) as exc:
        message = getattr(exc, "message", str(exc))
        raise CleanupWaveRecordingError(
            f"cleanup evidence schema validation failed: {message}"
        ) from exc


def _validate_binding(
    value: object,
    *,
    binding: CandidateBinding,
    wave: str,
    payload: dict[str, Any],
) -> None:
    """Require raw production evidence to bind the exact wave candidate."""

    if payload.get("environment") != "production" or payload.get("wave") != wave:
        raise CleanupWaveRecordingError("raw evidence is not production data for this wave")
    if not binding_matches(value, binding):
        raise CleanupWaveRecordingError("raw evidence candidate binding mismatch")


def _collection(
    value: object,
    *,
    query_id: str,
    label: str,
) -> dict[str, Any]:
    """Validate secret-free production collection provenance."""

    collection = _mapping(value)
    _exact_fields(
        collection,
        frozenset({"system", "endpoint", "query_id", "collected_by"}),
        label=label,
    )
    system = str(collection.get("system") or "").strip()
    collected_by = str(collection.get("collected_by") or "").strip()
    if not system or not collected_by or collection.get("query_id") != query_id:
        raise CleanupWaveRecordingError(f"{label} provenance is incomplete")
    _credential_free_https(collection.get("endpoint"), field=f"{label}.endpoint")
    return collection


def derive_error_metrics(
    snapshot: dict[str, Any],
    *,
    scope: WaveScope,
    binding: CandidateBinding,
    recorded_at: datetime,
) -> tuple[datetime, datetime, list[dict[str, Any]]]:
    """Derive comparable task error metrics from production telemetry."""

    _validate_binding(
        snapshot.get("candidate_binding"),
        binding=binding,
        wave=scope.wave,
        payload=snapshot,
    )
    if snapshot.get("version") != TELEMETRY_VERSION:
        raise CleanupWaveRecordingError("unsupported cleanup telemetry snapshot version")
    _collection(snapshot.get("collection"), query_id=TELEMETRY_QUERY_ID, label="telemetry")
    baseline = _mapping(snapshot.get("baseline_window"))
    candidate = _mapping(snapshot.get("candidate_window"))
    _exact_fields(baseline, frozenset({"start", "end"}), label="baseline_window")
    _exact_fields(candidate, frozenset({"start", "end"}), label="candidate_window")
    baseline_start = _parse_datetime(baseline.get("start"), field="baseline_window.start")
    baseline_end = _parse_datetime(baseline.get("end"), field="baseline_window.end")
    observed_from = _parse_datetime(candidate.get("start"), field="candidate_window.start")
    observed_until = _parse_datetime(candidate.get("end"), field="candidate_window.end")
    collected_at = _parse_datetime(snapshot.get("collected_at"), field="telemetry.collected_at")
    if (
        baseline_end <= baseline_start
        or baseline_end - baseline_start < timedelta(hours=48)
        or observed_until <= observed_from
        or observed_until - observed_from < timedelta(hours=48)
        or baseline_end > observed_from
        or not observed_until <= collected_at <= recorded_at
        or collected_at - observed_until > MAX_COLLECTION_LAG
    ):
        raise CleanupWaveRecordingError("telemetry does not prove two valid 48-hour windows")
    raw_tasks = snapshot.get("tasks")
    if not isinstance(raw_tasks, list):
        raise CleanupWaveRecordingError("telemetry tasks must be an array")
    records: dict[str, dict[str, Any]] = {}
    for raw_task in raw_tasks:
        task = _mapping(raw_task)
        _exact_fields(
            task,
            frozenset(
                {
                    "task_key",
                    "baseline_requests",
                    "baseline_errors",
                    "candidate_requests",
                    "candidate_errors",
                }
            ),
            label="telemetry task",
        )
        task_key = str(task.get("task_key") or "").strip()
        if not task_key or task_key in records:
            raise CleanupWaveRecordingError("telemetry has blank or duplicate task keys")
        records[task_key] = task
    if set(records) != set(scope.task_keys):
        raise CleanupWaveRecordingError("telemetry task coverage differs from wave routes")
    metrics: list[dict[str, Any]] = []
    for task_key in sorted(records):
        task = records[task_key]
        baseline_requests = _non_negative_int(
            task.get("baseline_requests"), field=f"{task_key}.baseline_requests"
        )
        baseline_errors = _non_negative_int(
            task.get("baseline_errors"), field=f"{task_key}.baseline_errors"
        )
        candidate_requests = _non_negative_int(
            task.get("candidate_requests"), field=f"{task_key}.candidate_requests"
        )
        candidate_errors = _non_negative_int(
            task.get("candidate_errors"), field=f"{task_key}.candidate_errors"
        )
        if (
            baseline_requests < 20
            or candidate_requests < 20
            or baseline_errors > baseline_requests
            or candidate_errors > candidate_requests
            or candidate_errors / candidate_requests - baseline_errors / baseline_requests > 0.005
        ):
            raise CleanupWaveRecordingError(f"error regression threshold failed: {task_key}")
        metrics.append(
            {
                "task_key": task_key,
                "baseline_requests": baseline_requests,
                "baseline_errors": baseline_errors,
                "candidate_requests": candidate_requests,
                "candidate_errors": candidate_errors,
            }
        )
    return observed_from, observed_until, metrics


def validate_deployment_preflight(
    artifact: RawArtifact,
    *,
    binding: CandidateBinding,
    observed_from: datetime,
    recorded_at: datetime,
) -> observation_start.DeploymentPreflight:
    """Bind the observation start to a validated production deployment."""

    verified_at = _parse_datetime(
        artifact.payload.get("verified_at"), field="deployment_preflight.verified_at"
    )
    if verified_at > recorded_at:
        raise CleanupWaveRecordingError("deployment preflight is future-dated")
    try:
        deployment = cast(
            observation_start.DeploymentPreflight,
            observation_start.parse_deployment_preflight(
                artifact.payload,
                now=verified_at,
                evidence=artifact.reference,
                evidence_sha256=artifact.sha256,
            ),
        )
    except observation_start.ObservationStartError as exc:
        raise CleanupWaveRecordingError(f"deployment preflight is invalid: {exc}") from exc
    if (
        deployment.stable_version != binding["candidate_version"]
        or deployment.source_commit != binding["candidate_commit"]
        or deployment.oci_revision != binding["candidate_commit"]
    ):
        raise CleanupWaveRecordingError(
            "deployment preflight does not identify the exact cleanup candidate"
        )
    deployment_floor = max(
        deployment.deployed_at.astimezone(timezone.utc),
        deployment.verified_at.astimezone(timezone.utc),
    )
    if observed_from.astimezone(timezone.utc) < deployment_floor:
        raise CleanupWaveRecordingError(
            "cleanup observation starts before production deployment verification"
        )
    if artifact.git_commit is None or artifact.git_committed_at is None:
        raise CleanupWaveRecordingError(
            "deployment preflight was not loaded from an immutable Git snapshot"
        )
    if (
        not deployment.verified_at.astimezone(timezone.utc)
        <= artifact.git_committed_at.astimezone(timezone.utc)
        <= observed_from.astimezone(timezone.utc)
        or not cleanup_guard._git_commit_is_ancestor(
            binding["candidate_commit"],
            root=ROOT,
            descendant=artifact.git_commit,
        )
        or not cleanup_guard._git_commit_is_ancestor(artifact.git_commit, root=ROOT)
    ):
        raise CleanupWaveRecordingError(
            "deployment preflight was not committed after the candidate and before observation"
        )
    return deployment


def derive_defect_counts(
    snapshot: dict[str, Any],
    *,
    wave: str,
    binding: CandidateBinding,
    observed_from: datetime,
    observed_until: datetime,
    recorded_at: datetime,
) -> dict[str, int]:
    """Recompute P0/P1 new/open counts from exact issue records."""

    _validate_binding(
        snapshot.get("candidate_binding"), binding=binding, wave=wave, payload=snapshot
    )
    if (
        snapshot.get("version") != DEFECT_VERSION
        or snapshot.get("query_scope") != DEFECT_QUERY_SCOPE
    ):
        raise CleanupWaveRecordingError("unsupported or incomplete defect snapshot")
    window_start = _parse_datetime(snapshot.get("window_start"), field="defects.window_start")
    window_end = _parse_datetime(snapshot.get("window_end"), field="defects.window_end")
    queried_at = _parse_datetime(snapshot.get("queried_at"), field="defects.queried_at")
    if (
        window_start != observed_from
        or window_end != observed_until
        or not observed_until <= queried_at <= recorded_at
        or queried_at - observed_until > MAX_COLLECTION_LAG
    ):
        raise CleanupWaveRecordingError("defect query does not cover the exact observation window")
    tracker = _mapping(snapshot.get("tracker"))
    _exact_fields(
        tracker,
        frozenset({"system", "endpoint", "project", "query_filter", "queried_by"}),
        label="defect tracker",
    )
    if any(
        not str(tracker.get(key) or "").strip()
        for key in ("system", "project", "query_filter", "queried_by")
    ):
        raise CleanupWaveRecordingError("defect tracker provenance is incomplete")
    _credential_free_https(tracker.get("endpoint"), field="defect tracker.endpoint")
    issues = snapshot.get("issues")
    if not isinstance(issues, list):
        raise CleanupWaveRecordingError("defect issues must be an array")
    counts: dict[str, int] = {
        "new_p0": 0,
        "new_p1": 0,
        "open_p0": 0,
        "open_p1": 0,
    }
    seen_ids: set[str] = set()
    for raw_issue in issues:
        issue = _mapping(raw_issue)
        _exact_fields(
            issue,
            frozenset({"id", "priority", "state", "created_at", "closed_at"}),
            label="defect issue",
        )
        issue_id = str(issue.get("id") or "").strip()
        priority = str(issue.get("priority") or "").strip().upper()
        state = str(issue.get("state") or "").strip().lower()
        if not issue_id or issue_id in seen_ids or priority not in {"P0", "P1"}:
            raise CleanupWaveRecordingError("defect issue identity/priority is invalid")
        seen_ids.add(issue_id)
        created_at = _parse_datetime(issue.get("created_at"), field=f"{issue_id}.created_at")
        raw_closed_at = issue.get("closed_at")
        closed_at = (
            None
            if raw_closed_at is None
            else _parse_datetime(raw_closed_at, field=f"{issue_id}.closed_at")
        )
        if (
            state not in {"open", "closed"}
            or (state == "open" and closed_at is not None)
            or (state == "closed" and closed_at is None)
            or (closed_at is not None and closed_at < created_at)
        ):
            raise CleanupWaveRecordingError(f"defect issue lifecycle is invalid: {issue_id}")
        created_during = observed_from <= created_at <= observed_until
        open_during = created_at <= observed_until and (
            closed_at is None or closed_at >= observed_from
        )
        if not (created_during or open_during):
            raise CleanupWaveRecordingError(f"defect issue is outside query window: {issue_id}")
        suffix = priority.lower()
        if created_during:
            counts[f"new_{suffix}"] += 1
        if open_during:
            counts[f"open_{suffix}"] += 1
    if any(counts.values()):
        raise CleanupWaveRecordingError(f"blocking defects remain: {counts}")
    return counts


def derive_scheduled_cycles(
    snapshot: dict[str, Any],
    *,
    scope: WaveScope,
    binding: CandidateBinding,
    observed_from: datetime,
    observed_until: datetime,
    recorded_at: datetime,
) -> list[dict[str, Any]]:
    """Derive successful scheduled-cycle evidence from raw execution records."""

    _validate_binding(
        snapshot.get("candidate_binding"),
        binding=binding,
        wave=scope.wave,
        payload=snapshot,
    )
    if snapshot.get("version") != SCHEDULED_CYCLE_VERSION:
        raise CleanupWaveRecordingError("unsupported scheduled-cycle snapshot version")
    _collection(
        snapshot.get("collection"),
        query_id=SCHEDULED_CYCLE_QUERY_ID,
        label="scheduled cycles",
    )
    window_start = _parse_datetime(snapshot.get("window_start"), field="cycles.window_start")
    window_end = _parse_datetime(snapshot.get("window_end"), field="cycles.window_end")
    collected_at = _parse_datetime(snapshot.get("collected_at"), field="cycles.collected_at")
    if (
        window_start != observed_from
        or window_end != observed_until
        or not observed_until <= collected_at <= recorded_at
        or collected_at - observed_until > MAX_COLLECTION_LAG
    ):
        raise CleanupWaveRecordingError(
            "scheduled cycles do not cover the exact observation window"
        )
    raw_cycles = snapshot.get("cycles")
    if not isinstance(raw_cycles, list) or not raw_cycles:
        raise CleanupWaveRecordingError("scheduled-cycle snapshot contains no executions")
    task_keys: set[str] = set()
    run_ids: set[str] = set()
    cycles: list[dict[str, Any]] = []
    for raw_cycle in raw_cycles:
        cycle = _mapping(raw_cycle)
        _exact_fields(
            cycle,
            frozenset({"task_key", "run_id", "observed_at", "outcome"}),
            label="scheduled cycle",
        )
        task_key = str(cycle.get("task_key") or "").strip()
        run_id = str(cycle.get("run_id") or "").strip()
        observed_at = _parse_datetime(cycle.get("observed_at"), field="cycle.observed_at")
        if (
            task_key not in scope.task_keys
            or task_key in task_keys
            or not run_id
            or run_id in run_ids
            or cycle.get("outcome") != "success"
            or not observed_from <= observed_at <= observed_until
        ):
            raise CleanupWaveRecordingError("scheduled-cycle execution is invalid or duplicated")
        task_keys.add(task_key)
        run_ids.add(run_id)
        cycles.append(
            {
                "task_key": task_key,
                "observed_at": _iso_utc(observed_at),
                "outcome": "success",
            }
        )
    if task_keys != set(scope.task_keys):
        raise CleanupWaveRecordingError("scheduled-cycle coverage differs from wave routes")
    return sorted(cycles, key=lambda value: str(value["task_key"]))


def load_raw_artifact(path: Path, *, schema_path: Path) -> RawArtifact:
    """Load, schema-check, and hash one repository-contained raw snapshot."""

    resolved = path.resolve()
    try:
        reference = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CleanupWaveRecordingError(
            "raw evidence must be stored inside the repository"
        ) from exc
    if not resolved.is_file():
        raise CleanupWaveRecordingError(f"raw evidence file does not exist: {resolved}")
    payload = _load_object(resolved)
    _validate_schema(payload, schema_path)
    return RawArtifact(
        path=resolved,
        reference=reference,
        sha256=_sha256(_normalized_bytes(resolved.read_bytes())),
        payload=payload,
    )


def _latest_blob_commit(path: Path, current: bytes) -> tuple[str, datetime]:
    """Find the latest HEAD-lineage commit that introduced the current blob."""

    relative = _repository_reference(path)
    history = subprocess.run(
        ["git", "log", "--format=%H", "--", relative],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if history.returncode:
        raise CleanupWaveRecordingError("deployment preflight Git history is unavailable")
    selected: str | None = None
    for raw_commit in history.stdout.splitlines():
        commit = raw_commit.strip().lower()
        content = cleanup_guard._git_source_bytes(commit, path, root=ROOT)
        if content == current:
            selected = commit
            break
    if selected is None or not COMMIT_PATTERN.fullmatch(selected):
        raise CleanupWaveRecordingError(
            "deployment preflight exact blob is not committed in HEAD history"
        )
    timestamp = subprocess.run(
        ["git", "show", "-s", "--format=%cI", selected],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if timestamp.returncode:
        raise CleanupWaveRecordingError("deployment preflight commit time is unavailable")
    return selected, _parse_datetime(
        timestamp.stdout.strip(), field="deployment_preflight.git_committed_at"
    )


def load_committed_deployment_preflight(
    path: Path,
    *,
    schema_path: Path = DEFAULT_DEPLOYMENT_SCHEMA,
) -> RawArtifact:
    """Load the exact committed deployment attestation used to start observation."""

    resolved = path.resolve()
    try:
        reference = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CleanupWaveRecordingError(
            "deployment preflight must be stored inside the repository"
        ) from exc
    if not resolved.is_file():
        raise CleanupWaveRecordingError("deployment preflight file does not exist")
    payload = _load_object(resolved)
    _validate_schema(payload, schema_path)
    verified_at = _parse_datetime(
        payload.get("verified_at"), field="deployment_preflight.verified_at"
    )
    try:
        deployment = observation_start._load_committed_deployment_preflight(
            resolved,
            now=verified_at,
            root=ROOT,
        )
    except observation_start.ObservationStartError as exc:
        raise CleanupWaveRecordingError(
            f"deployment preflight is not exact committed evidence: {exc}"
        ) from exc
    current = resolved.read_bytes()
    git_commit, git_committed_at = _latest_blob_commit(resolved, current)
    return RawArtifact(
        path=resolved,
        reference=reference,
        sha256=_sha256(_normalized_bytes(current)),
        payload=payload,
        git_commit=git_commit,
        git_committed_at=git_committed_at,
    )


def build_wave_bundle(
    *,
    scope: WaveScope,
    authorization: cleanup_guard.FinalAuthorization,
    candidate: cleanup_guard.CandidateSnapshot,
    deployment_preflight: RawArtifact | None,
    telemetry: RawArtifact,
    defects: RawArtifact,
    scheduled_cycles: RawArtifact,
    artifact_directory: Path,
    recorded_at: datetime,
    schema_path: Path = DEFAULT_SCHEMA,
) -> WaveBundle:
    """Build and revalidate all external artifacts for one cleanup wave."""

    observed_from, observed_until, metrics = derive_error_metrics(
        telemetry.payload,
        scope=scope,
        binding=candidate.binding,
        recorded_at=recorded_at,
    )
    if deployment_preflight is None:
        raise CleanupWaveRecordingError("deployment preflight snapshot is required")
    deployment = validate_deployment_preflight(
        deployment_preflight,
        binding=candidate.binding,
        observed_from=observed_from,
        recorded_at=recorded_at,
    )
    if observed_from.date() < authorization.approved_at:
        raise CleanupWaveRecordingError("cleanup observation predates final cutover authorization")
    defect_counts = derive_defect_counts(
        defects.payload,
        wave=scope.wave,
        binding=candidate.binding,
        observed_from=observed_from,
        observed_until=observed_until,
        recorded_at=recorded_at,
    )
    cycles = derive_scheduled_cycles(
        scheduled_cycles.payload,
        scope=scope,
        binding=candidate.binding,
        observed_from=observed_from,
        observed_until=observed_until,
        recorded_at=recorded_at,
    )
    rollback_manifest = {
        "version": cleanup_guard.CLEANUP_ROLLBACK_VERSION,
        "wave": scope.wave,
        "authorized_candidate_commit": authorization.binding["candidate_commit"],
        "cleanup_candidate_commit": candidate.binding["candidate_commit"],
        "deleted_paths": list(scope.deleted_paths),
        "route_rollback_commits": dict(sorted(scope.rollback_commits.items())),
    }
    observation_ledger = {
        "version": cleanup_guard.CLEANUP_OBSERVATION_VERSION,
        "wave": scope.wave,
        "candidate_binding": candidate.binding,
        "observed_from": _iso_utc(observed_from),
        "observed_until": _iso_utc(observed_until),
        "scheduled_cycles": cycles,
        "defects": defect_counts,
        "error_metrics": metrics,
    }
    rollback_path = artifact_directory / "rollback-manifest.v1.json"
    observation_path = artifact_directory / "observation-ledger.v1.json"
    wave_record_path = artifact_directory / "wave-record.v1.json"
    rollback_sha = _sha256(_json_bytes(rollback_manifest))
    observation_sha = _sha256(_json_bytes(observation_ledger))
    rollback_reference = _repository_reference(rollback_path)
    observation_reference = _repository_reference(observation_path)
    wave_record_reference = _repository_reference(wave_record_path)
    wave_record = {
        "version": WAVE_RECORD_VERSION,
        "wave": scope.wave,
        "authorized_candidate_binding": authorization.binding,
        "candidate_binding": candidate.binding,
        "catalog_sha256": candidate.catalog["sha256"],
        "deleted_paths": list(scope.deleted_paths),
        "route_count": scope.route_count,
        "matrix_owners": list(scope.owners),
        "matrix_reviewers": list(scope.reviewers),
        "verified_at": recorded_at.date().isoformat(),
        "source_artifacts": {
            "deployment_preflight": {
                "path": deployment_preflight.reference,
                "sha256": deployment_preflight.sha256,
            },
            "telemetry": {"path": telemetry.reference, "sha256": telemetry.sha256},
            "defects": {"path": defects.reference, "sha256": defects.sha256},
            "scheduled_cycles": {
                "path": scheduled_cycles.reference,
                "sha256": scheduled_cycles.sha256,
            },
        },
        "rollback_manifest": {"path": rollback_reference, "sha256": rollback_sha},
        "observation_ledger": {
            "path": observation_reference,
            "sha256": observation_sha,
        },
        "deployment": {
            "release_id": deployment.release_id,
            "source_commit": deployment.source_commit,
            "image_id": deployment.image_id,
            "oci_revision": deployment.oci_revision,
            "deployed_at": _iso_utc(deployment.deployed_at),
            "verified_at": _iso_utc(deployment.verified_at),
            "attestation_commit": deployment_preflight.git_commit,
            "attestation_committed_at": _iso_utc(
                cast(datetime, deployment_preflight.git_committed_at)
            ),
        },
        "derived_summary": {
            "observed_from": _iso_utc(observed_from),
            "observed_until": _iso_utc(observed_until),
            "observation_seconds": int((observed_until - observed_from).total_seconds()),
            "task_metrics": len(metrics),
            "scheduled_cycles": len(cycles),
            "blocking_defects": sum(defect_counts.values()),
        },
    }
    wave_record_sha = _sha256(_json_bytes(wave_record))
    projection = {
        "version": cleanup_guard.CLEANUP_WAVE_VERSION,
        "wave": scope.wave,
        "authorized_candidate_binding": authorization.binding,
        "candidate_binding": candidate.binding,
        "catalog_sha256": candidate.catalog["sha256"],
        "deleted_paths": list(scope.deleted_paths),
        "owner": ",".join(scope.owners),
        "reviewer": ",".join(scope.reviewers),
        "verified_at": recorded_at.date().isoformat(),
        "evidence": wave_record_reference,
        "evidence_sha256": wave_record_sha,
        "rollback_manifest": rollback_reference,
        "rollback_manifest_sha256": rollback_sha,
        "observation_ledger": observation_reference,
        "observation_ledger_sha256": observation_sha,
    }
    for artifact in (rollback_manifest, observation_ledger, wave_record):
        _validate_schema(artifact, schema_path)
    if (
        cleanup_guard._observation_window(
            observation_ledger,
            wave=scope.wave,
            candidate=candidate,
            as_of=recorded_at.date(),
        )
        is None
    ):
        raise CleanupWaveRecordingError("derived observation does not satisfy cleanup guard")
    rows_by_path = _rows_by_path(candidate.matrix_bytes)
    if not cleanup_guard._rollback_manifest_matches(
        rollback_manifest,
        wave=scope.wave,
        authorization=authorization,
        candidate_binding=candidate.binding,
        deleted_paths=set(scope.deleted_paths),
        rows_by_path=rows_by_path,
        repository_root=ROOT,
    ):
        raise CleanupWaveRecordingError("derived rollback manifest does not satisfy cleanup guard")
    return WaveBundle(
        rollback_manifest=rollback_manifest,
        observation_ledger=observation_ledger,
        wave_record=wave_record,
        projection=projection,
    )


def _repository_reference(path: Path) -> str:
    """Return a repository-relative artifact path without traversal."""

    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CleanupWaveRecordingError(
            "output artifacts must remain inside the repository"
        ) from exc


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically write one deterministic JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(_json_bytes(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_wave_bundle(
    *,
    bundle: WaveBundle,
    evidence: dict[str, Any],
    evidence_path: Path,
    artifact_directory: Path,
) -> None:
    """Recoverably write SHA artifacts before atomically replacing evidence."""

    root = ROOT.resolve()
    resolved_evidence = evidence_path.resolve()
    resolved_artifact_directory = artifact_directory.resolve()
    if (
        not resolved_evidence.is_relative_to(root)
        or not resolved_artifact_directory.is_relative_to(root)
        or not resolved_evidence.is_file()
        or not resolved_evidence.parent.is_dir()
        or not os.access(resolved_evidence.parent, os.W_OK)
    ):
        raise CleanupWaveRecordingError(
            "evidence target is missing, outside the repository, or not writable"
        )
    writable_ancestor = resolved_artifact_directory
    while not writable_ancestor.exists() and writable_ancestor != root:
        writable_ancestor = writable_ancestor.parent
    if not writable_ancestor.is_dir() or not os.access(writable_ancestor, os.W_OK):
        raise CleanupWaveRecordingError("cleanup artifact parent is not writable")
    paths = (
        resolved_artifact_directory / "rollback-manifest.v1.json",
        resolved_artifact_directory / "observation-ledger.v1.json",
        resolved_artifact_directory / "wave-record.v1.json",
    )
    if any(path.exists() for path in paths):
        raise CleanupWaveRecordingError("cleanup wave artifacts already exist and are immutable")
    prepared = json.loads(json.dumps(evidence))
    cleanup = _mapping(prepared.get("cleanup"))
    if not cleanup:
        prepared["cleanup"] = cleanup
    raw_waves = cleanup.get("waves")
    waves = list(raw_waves) if isinstance(raw_waves, list) else []
    if any(_mapping(value).get("wave") == bundle.projection["wave"] for value in waves):
        raise CleanupWaveRecordingError("cleanup wave evidence already exists")
    waves.append(bundle.projection)
    cleanup["waves"] = waves
    created: list[Path] = []
    directory_existed = resolved_artifact_directory.exists()
    try:
        for path, value in zip(
            paths,
            (bundle.rollback_manifest, bundle.observation_ledger, bundle.wave_record),
            strict=True,
        ):
            _write_atomic(path, value)
            created.append(path)
        _write_atomic(resolved_evidence, cast(dict[str, Any], prepared))
    except Exception:
        for path in created:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        if not directory_existed:
            with suppress(OSError):
                resolved_artifact_directory.rmdir()
        raise


def _candidate_catalog_payload(commit: str, catalog_path: Path) -> dict[str, Any]:
    """Load the bounded telemetry catalog from the cleanup candidate."""

    try:
        return _mapping(json.loads(_git_blob(commit, catalog_path)))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanupWaveRecordingError("candidate telemetry catalog is invalid JSON") from exc


def _validate_candidate_lineage(
    *,
    evidence: dict[str, Any],
    authorization: cleanup_guard.FinalAuthorization,
    candidate: cleanup_guard.CandidateSnapshot,
) -> None:
    """Require a new candidate commit that seals authorization and prior wave artifacts."""

    cleanup = _mapping(evidence.get("cleanup"))
    raw_waves = cleanup.get("waves")
    waves = raw_waves if isinstance(raw_waves, list) else []
    previous_commit = authorization.binding["candidate_commit"]
    if waves:
        previous_binding = _mapping(_mapping(waves[-1]).get("candidate_binding"))
        previous_commit = str(previous_binding.get("candidate_commit") or "").strip()
    current_commit = candidate.binding["candidate_commit"]
    if (
        previous_commit == current_commit
        or not cleanup_guard._git_commit_is_ancestor(
            previous_commit,
            root=ROOT,
            descendant=current_commit,
        )
        or not cleanup_guard._commit_contains_artifacts(
            current_commit,
            authorization.artifact_digests,
            repository_root=ROOT,
        )
    ):
        raise CleanupWaveRecordingError("cleanup candidate lineage/authorization seal is invalid")
    for raw_wave in waves:
        wave = _mapping(raw_wave)
        for reference_field, digest_field in (
            ("evidence", "evidence_sha256"),
            ("rollback_manifest", "rollback_manifest_sha256"),
            ("observation_ledger", "observation_ledger_sha256"),
        ):
            artifact = cleanup_guard._verified_repo_file(
                wave.get(reference_field),
                wave.get(digest_field),
                evidence_root=ROOT,
            )
            if artifact is None:
                raise CleanupWaveRecordingError("prior cleanup wave artifact is invalid")
            content = cleanup_guard._git_source_bytes(current_commit, artifact, root=ROOT)
            if content is None:
                raise CleanupWaveRecordingError(
                    "cleanup candidate does not seal prior wave artifacts"
                )
            if artifact.suffix.lower() in cleanup_guard.NORMALIZED_EVIDENCE_SUFFIXES:
                content = _normalized_bytes(content)
            if _sha256(content) != str(wave.get(digest_field) or ""):
                raise CleanupWaveRecordingError(
                    "prior cleanup artifact digest changed in candidate"
                )


def prepare_cleanup_wave(
    *,
    candidate_version: str,
    candidate_revision: str,
    evidence_path: Path,
    matrix_path: Path,
    catalog_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
    deployment_preflight_path: Path,
    telemetry_path: Path,
    defect_path: Path,
    scheduled_cycle_path: Path,
    artifact_root: Path,
    schema_path: Path,
    recorded_at: datetime,
) -> tuple[WaveBundle, dict[str, Any], Path]:
    """Validate repository state and prepare one immutable cleanup wave."""

    candidate = build_candidate_snapshot(
        candidate_version=candidate_version,
        candidate_revision=candidate_revision,
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_manifest_path,
    )
    candidate_rows = _rows_by_path(candidate.matrix_bytes)
    current_m5_deletions = {
        path
        for path, row in candidate_rows.items()
        if row.get("status") == "deleted" and path not in cleanup_guard.M0_D_BASELINE_PATHS
    }
    if not current_m5_deletions:
        raise CleanupWaveRecordingError("candidate contains no M5-B cleanup deletion")
    evidence = _load_object(evidence_path)
    authorization = cleanup_guard._final_authorization(
        evidence,
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_manifest_path,
        as_of=recorded_at.date(),
        evidence_root=ROOT,
        repository_root=ROOT,
    )
    if authorization is None:
        raise CleanupWaveRecordingError("final cutover authorization is missing or invalid")
    _validate_candidate_lineage(
        evidence=evidence,
        authorization=authorization,
        candidate=candidate,
    )
    authorized_matrix = _git_blob(authorization.binding["candidate_commit"], matrix_path)
    catalog_payload = _candidate_catalog_payload(
        candidate.binding["candidate_commit"], catalog_path
    )
    cleanup = _mapping(evidence.get("cleanup"))
    scope = derive_wave_scope(
        authorized_matrix=authorized_matrix,
        candidate_matrix=candidate.matrix_bytes,
        candidate_catalog=catalog_payload,
        candidate_binding=candidate.binding,
        existing_wave_values=cleanup.get("waves"),
    )
    for path in scope.deleted_paths:
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT.resolve()) or resolved.exists():
            raise CleanupWaveRecordingError(f"deleted template still exists in worktree: {path}")
        if (
            cleanup_guard._git_source_bytes(
                candidate.binding["candidate_commit"], resolved, root=ROOT
            )
            is not None
        ):
            raise CleanupWaveRecordingError(f"deleted template still exists in candidate: {path}")
    deployment_preflight = load_committed_deployment_preflight(deployment_preflight_path)
    telemetry = load_raw_artifact(telemetry_path, schema_path=schema_path)
    defects = load_raw_artifact(defect_path, schema_path=schema_path)
    cycles = load_raw_artifact(scheduled_cycle_path, schema_path=schema_path)
    artifact_directory = artifact_root.resolve() / scope.wave.lower()
    bundle = build_wave_bundle(
        scope=scope,
        authorization=authorization,
        candidate=candidate,
        deployment_preflight=deployment_preflight,
        telemetry=telemetry,
        defects=defects,
        scheduled_cycles=cycles,
        artifact_directory=artifact_directory,
        recorded_at=recorded_at,
        schema_path=schema_path,
    )
    return bundle, evidence, artifact_directory


def _build_parser() -> argparse.ArgumentParser:
    """Build the recorder CLI without caller-controlled pass state or dates."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--candidate-ref", default="HEAD")
    parser.add_argument("--deployment-attestation", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--defects", type=Path)
    parser.add_argument("--scheduled-cycles", type=Path)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write validated external artifacts and cleanup.waves; default is dry-run.",
    )
    return parser


def main() -> int:
    """Prepare or atomically record one M5-B cleanup wave."""

    args = _build_parser().parse_args()
    try:
        candidate = build_candidate_snapshot(
            candidate_version=args.candidate_version,
            candidate_revision=args.candidate_ref,
            matrix_path=args.matrix.resolve(),
            catalog_path=args.catalog.resolve(),
            graph_path=args.graph.resolve(),
            runtime_manifest_path=args.runtime_manifest.resolve(),
        )
        rows = _rows_by_path(candidate.matrix_bytes)
        if not any(
            row.get("status") == "deleted" and path not in cleanup_guard.M0_D_BASELINE_PATHS
            for path, row in rows.items()
        ):
            raise CleanupWaveRecordingError("candidate contains no M5-B cleanup deletion")
        if (
            args.deployment_attestation is None
            or args.telemetry is None
            or args.defects is None
            or args.scheduled_cycles is None
        ):
            raise CleanupWaveRecordingError(
                "deployment preflight, telemetry, defects, and scheduled-cycle snapshots "
                "are required"
            )
        bundle, evidence, artifact_directory = prepare_cleanup_wave(
            candidate_version=args.candidate_version,
            candidate_revision=args.candidate_ref,
            evidence_path=args.evidence.resolve(),
            matrix_path=args.matrix.resolve(),
            catalog_path=args.catalog.resolve(),
            graph_path=args.graph.resolve(),
            runtime_manifest_path=args.runtime_manifest.resolve(),
            deployment_preflight_path=args.deployment_attestation.resolve(),
            telemetry_path=args.telemetry.resolve(),
            defect_path=args.defects.resolve(),
            scheduled_cycle_path=args.scheduled_cycles.resolve(),
            artifact_root=args.artifact_root.resolve(),
            schema_path=args.schema.resolve(),
            recorded_at=datetime.now(timezone.utc),
        )
        if args.write:
            write_wave_bundle(
                bundle=bundle,
                evidence=evidence,
                evidence_path=args.evidence.resolve(),
                artifact_directory=artifact_directory,
            )
    except (
        CleanupWaveRecordingError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"Web-to-TUI cleanup wave recorder: FAIL - {exc}")
        return 1
    mode = "WRITTEN" if args.write else "READY (dry-run)"
    print(
        f"Web-to-TUI cleanup wave recorder: {mode} - "
        f"wave={bundle.projection['wave']} routes={len(bundle.projection['deleted_paths'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
