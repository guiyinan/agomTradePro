#!/usr/bin/env python
"""Fail closed unless an M5-B cleanup extends an approved cutover safely.

The seven M0-D shadow-template deletions form the immutable baseline.  A later
M5-B cleanup is a *new* source candidate: its matrix cannot be evaluated with
the pre-cleanup candidate binding without creating an impossible SHA loop.
This guard therefore verifies the immutable final cutover authorization first,
then verifies candidate-bound evidence for every cleanup wave.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.web_to_tui_candidate_binding import (  # noqa: E402
    BINDING_VERSION,
    CandidateBinding,
    binding_matches,
    build_candidate_binding,
    normalized_source_bytes,
)

DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
DEFAULT_GRAPH = ROOT / "config/tui/published/tui_operation_graph.published.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/tui/agomtui-runtime.manifest.json"

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_ATTESTATION_VERSION = "web-to-tui-cutover-approval-attestation.v1"
REVIEW_SNAPSHOT_VERSION = "web-to-tui-cutover-review-snapshot.v1"
CLEANUP_WAVE_VERSION = "web-to-tui-cleanup-wave-evidence.v1"
CLEANUP_ROLLBACK_VERSION = "web-to-tui-cleanup-wave-rollback-manifest.v1"
CLEANUP_OBSERVATION_VERSION = "web-to-tui-cleanup-wave-observation.v1"
WAVE_PATTERN = re.compile(r"^M5-B-W([1-9][0-9]*)$")
APPROVAL_PROJECTION_FIELDS = frozenset(
    {
        "role",
        "name",
        "decision",
        "approved_at",
        "candidate_version",
        "candidate_commit",
        "source_sha256",
        "review_snapshot",
        "evidence_snapshot_sha256",
        "evidence",
        "evidence_sha256",
    }
)
REVIEW_SNAPSHOT_FIELDS = frozenset(
    {
        "version",
        "candidate_version",
        "candidate_commit",
        "source_sha256",
        "reviewed_at",
        "as_of",
        "required_route_pages",
        "required_tasks",
        "gates",
    }
)
CLEANUP_WAVE_FIELDS = frozenset(
    {
        "version",
        "wave",
        "authorized_candidate_binding",
        "candidate_binding",
        "catalog_sha256",
        "deleted_paths",
        "owner",
        "reviewer",
        "verified_at",
        "evidence",
        "evidence_sha256",
        "rollback_manifest",
        "rollback_manifest_sha256",
        "observation_ledger",
        "observation_ledger_sha256",
    }
)
CLEANUP_ROLLBACK_FIELDS = frozenset(
    {
        "version",
        "wave",
        "authorized_candidate_commit",
        "cleanup_candidate_commit",
        "deleted_paths",
        "route_rollback_commits",
    }
)
REQUIRED_PRE_APPROVAL_GATES = frozenset(
    {
        "source_consistency",
        "stable_version_window",
        "route_task_uat",
        "route_cleanup_readiness",
        "blocking_defects",
        "production_telemetry",
        "rollback_drill",
        "production_registry_backup",
    }
)
LEGACY_URL_POLICIES = frozenset({"redirect_to_tui", "retain", "remove_410", "remove_404"})
NORMALIZED_EVIDENCE_SUFFIXES = frozenset({".csv", ".json", ".md", ".txt"})
M0_D_BASELINE_PATHS = frozenset(
    {
        "apps/audit/templates/audit/attribution_report.html",
        "apps/audit/templates/audit/audit_page.html",
        "apps/data_center/templates/data_center/monitor.html",
        "apps/data_center/templates/data_center/providers.html",
        "core/templates/account/create_simulated_account.html",
        "core/templates/audit/audit_page.html",
        "core/templates/macro/data_controller.html",
    }
)


class CatalogIdentity(TypedDict):
    """Validated telemetry catalog identity for one source snapshot."""

    sha256: str
    task_count: int
    task_keys: frozenset[str]


@dataclass(frozen=True)
class CleanupGuardResult:
    """One fail-closed decision for newly deleted Classic templates."""

    allowed: bool
    new_deleted_paths: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class CandidateSnapshot:
    """One Git-resolved matrix/graph/runtime/catalog candidate snapshot."""

    binding: CandidateBinding
    matrix_bytes: bytes
    catalog: CatalogIdentity


@dataclass(frozen=True)
class FinalAuthorization:
    """Verified final cutover authorization that cleanup must extend."""

    binding: CandidateBinding
    approved_at: date
    artifact_digests: tuple[tuple[Path, str], ...]


def _mapping(value: object) -> dict[str, Any]:
    """Narrow a dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    value = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], value)


def _json_object_from_bytes(value: bytes, *, label: str) -> dict[str, Any]:
    """Decode one UTF-8 JSON object from an immutable source snapshot."""

    payload = cast(Any, json.loads(value.decode("utf-8")))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {label}")
    return cast(dict[str, Any], payload)


def _parse_date(value: object) -> date | None:
    """Parse an optional ISO date without accepting datetimes."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    """Parse one required timezone-aware ISO-8601 timestamp."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _sha256(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: object) -> bool:
    """Return whether a value is a canonical SHA-256 digest."""

    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value.strip()))


def _normalized_bytes(value: bytes) -> bytes:
    """Normalize a UTF-8 Git text blob to LF for cross-platform identity."""

    text = value.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _read_matrix_rows(matrix_path: Path) -> list[dict[str, str]]:
    """Read reviewed migration rows from the CSV boundary."""

    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _matrix_rows_from_bytes(value: bytes) -> list[dict[str, str]]:
    """Read matrix rows from a Git-resolved candidate blob."""

    return list(csv.DictReader(io.StringIO(_normalized_bytes(value).decode("utf-8"))))


def _required_route_count(rows: list[dict[str, str]]) -> int:
    """Count the A/B route denominator retained across migrated/deleted states."""

    return len(
        {
            str(row.get("template_path") or "").strip()
            for row in rows
            if row.get("template_role") == "route_page"
            and row.get("destination_class") in {"A", "B"}
            and row.get("status") in {"migrated", "deleted"}
            and str(row.get("template_path") or "").strip()
        }
    )


def _git_commit_is_ancestor(
    commit: str,
    *,
    root: Path,
    descendant: str = "HEAD",
) -> bool:
    """Return whether a full commit is an ancestor of the requested candidate."""

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
        ["git", "merge-base", "--is-ancestor", commit, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return ancestor.returncode == 0


def _git_source_bytes(commit: str, source_path: Path, *, root: Path) -> bytes | None:
    """Read one repository-relative source exactly as stored by a commit."""

    try:
        relative = source_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _catalog_identity(catalog_bytes: bytes, *, matrix_sha256: str) -> CatalogIdentity | None:
    """Validate catalog-to-matrix consistency and its bounded task denominator."""

    try:
        payload = _json_object_from_bytes(catalog_bytes, label="telemetry catalog")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    routes = payload.get("classic_routes")
    if payload.get("source_sha256") != matrix_sha256 or not isinstance(routes, list):
        return None
    task_keys = {
        str(_mapping(value).get("task_key") or "").strip()
        for value in routes
        if str(_mapping(value).get("task_key") or "").strip()
    }
    if len(task_keys) != len(routes):
        return None
    return {
        "sha256": _sha256(_normalized_bytes(catalog_bytes)),
        "task_count": len(task_keys),
        "task_keys": frozenset(task_keys),
    }


def _candidate_snapshot(
    value: object,
    *,
    matrix_path: Path,
    catalog_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
    repository_root: Path,
) -> CandidateSnapshot | None:
    """Resolve and validate an exact candidate binding from immutable Git blobs."""

    binding = _mapping(value)
    candidate_version = str(binding.get("candidate_version") or "").strip()
    candidate_commit = str(binding.get("candidate_commit") or "").strip()
    if (
        binding.get("version") != BINDING_VERSION
        or not candidate_version
        or not _git_commit_is_ancestor(candidate_commit, root=repository_root)
    ):
        return None
    matrix_bytes = _git_source_bytes(candidate_commit, matrix_path, root=repository_root)
    catalog_bytes = _git_source_bytes(candidate_commit, catalog_path, root=repository_root)
    graph_bytes = _git_source_bytes(candidate_commit, graph_path, root=repository_root)
    runtime_bytes = _git_source_bytes(
        candidate_commit,
        runtime_manifest_path,
        root=repository_root,
    )
    if None in {matrix_bytes, catalog_bytes, graph_bytes, runtime_bytes}:
        return None
    assert matrix_bytes is not None
    assert catalog_bytes is not None
    assert graph_bytes is not None
    assert runtime_bytes is not None
    try:
        graph = _json_object_from_bytes(graph_bytes, label="published graph")
        runtime = _json_object_from_bytes(runtime_bytes, label="runtime manifest")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    matrix_sha256 = _sha256(_normalized_bytes(matrix_bytes))
    expected: CandidateBinding = {
        "version": BINDING_VERSION,
        "candidate_version": candidate_version,
        "candidate_commit": candidate_commit,
        "matrix_sha256": matrix_sha256,
        "graph_sha256": _sha256(_normalized_bytes(graph_bytes)),
        "schema_version": str(graph.get("schema_version") or "").strip(),
        "runtime_version": str(runtime.get("version") or "").strip(),
        "runtime_build_id": str(runtime.get("build_id") or "").strip(),
        "runtime_manifest_sha256": _sha256(_normalized_bytes(runtime_bytes)),
    }
    if (
        not expected["schema_version"]
        or not expected["runtime_version"]
        or not expected["runtime_build_id"]
        or not binding_matches(value, expected)
    ):
        return None
    catalog = _catalog_identity(catalog_bytes, matrix_sha256=matrix_sha256)
    return (
        CandidateSnapshot(binding=expected, matrix_bytes=matrix_bytes, catalog=catalog)
        if catalog is not None
        else None
    )


def _verified_repo_file(
    reference: object,
    digest: object,
    *,
    evidence_root: Path,
) -> Path | None:
    """Resolve a repository evidence file only when its SHA-256 is exact."""

    if not isinstance(reference, str) or not reference.strip() or not _valid_sha256(digest):
        return None
    relative = Path(reference.strip())
    if relative.is_absolute():
        return None
    root = evidence_root.resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    content = resolved.read_bytes()
    if resolved.suffix.lower() in NORMALIZED_EVIDENCE_SUFFIXES:
        content = _normalized_bytes(content)
    return resolved if _sha256(content) == str(digest).strip() else None


def _verified_repo_json(
    reference: object,
    digest: object,
    *,
    evidence_root: Path,
) -> tuple[Path, dict[str, Any]] | None:
    """Return one verified repository JSON artifact and its resolved path."""

    path = _verified_repo_file(reference, digest, evidence_root=evidence_root)
    if path is None:
        return None
    try:
        return path, _load_object(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _approval_attestation(
    value: object,
    *,
    role: str,
    candidate_binding: CandidateBinding,
    source_sha256: str,
    review_reference: str,
    review_sha256: str,
    observation_end: date,
    reviewed_at: date,
    as_of: date,
    evidence_root: Path,
) -> tuple[str, date, Path, str] | None:
    """Validate one external approval and its exact projection."""

    projection = _mapping(value)
    artifact = _verified_repo_json(
        projection.get("evidence"),
        projection.get("evidence_sha256"),
        evidence_root=evidence_root,
    )
    if artifact is None:
        return None
    artifact_path, attestation = artifact
    expected = {
        "version": APPROVAL_ATTESTATION_VERSION,
        **{
            key: item
            for key, item in projection.items()
            if key not in {"evidence", "evidence_sha256"}
        },
    }
    approved_at = _parse_date(projection.get("approved_at"))
    name = str(projection.get("name") or "").strip()
    if (
        set(projection) != APPROVAL_PROJECTION_FIELDS
        or attestation != expected
        or projection.get("role") != role
        or projection.get("decision") != "approve"
        or not name
        or approved_at is None
        or not observation_end <= reviewed_at <= approved_at <= as_of
        or projection.get("candidate_version") != candidate_binding["candidate_version"]
        or projection.get("candidate_commit") != candidate_binding["candidate_commit"]
        or projection.get("source_sha256") != source_sha256
        or projection.get("review_snapshot") != review_reference
        or projection.get("evidence_snapshot_sha256") != review_sha256
    ):
        return None
    return name, approved_at, artifact_path, str(projection["evidence_sha256"])


def _final_authorization(
    evidence: dict[str, Any],
    *,
    matrix_path: Path,
    catalog_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
    as_of: date,
    evidence_root: Path,
    repository_root: Path,
) -> FinalAuthorization | None:
    """Verify the immutable review and dual approval of the pre-cleanup candidate."""

    candidate = _mapping(evidence.get("candidate"))
    snapshot = _candidate_snapshot(
        candidate.get("binding"),
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_manifest_path,
        repository_root=repository_root,
    )
    if snapshot is None:
        return None
    binding = snapshot.binding
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    released_at = _parse_date(candidate.get("released_at"))
    observation_end = _parse_date(candidate.get("observation_end"))
    if (
        candidate.get("stable_version") != binding["candidate_version"]
        or candidate.get("candidate_commit") != binding["candidate_commit"]
        or source_sha256 != binding["matrix_sha256"]
        or released_at is None
        or observation_end is None
        or (observation_end - released_at).days < 14
        or observation_end > as_of
    ):
        return None

    review_projection = _mapping(evidence.get("review_snapshot"))
    review_reference = str(review_projection.get("evidence") or "").strip()
    review_sha256 = str(review_projection.get("sha256") or "").strip()
    review_artifact = _verified_repo_json(
        review_reference,
        review_sha256,
        evidence_root=evidence_root,
    )
    if review_artifact is None:
        return None
    review_path, review = review_artifact
    gate_values = review.get("gates")
    if not isinstance(gate_values, list):
        return None
    gates = [_mapping(value) for value in gate_values]
    gate_keys = {str(value.get("key") or "").strip() for value in gates}
    reviewed_at = _parse_date(review.get("reviewed_at"))
    if (
        set(review_projection) != {"evidence", "sha256"}
        or set(review) != REVIEW_SNAPSHOT_FIELDS
        or any(set(value) != {"key", "passed", "detail"} for value in gates)
        or review.get("version") != REVIEW_SNAPSHOT_VERSION
        or review.get("candidate_version") != binding["candidate_version"]
        or review.get("candidate_commit") != binding["candidate_commit"]
        or review.get("source_sha256") != source_sha256
        or reviewed_at is None
        or review.get("as_of") != reviewed_at.isoformat()
        or not observation_end <= reviewed_at <= as_of
        or gate_keys != REQUIRED_PRE_APPROVAL_GATES
        or len(gates) != len(REQUIRED_PRE_APPROVAL_GATES)
        or not all(value.get("passed") is True for value in gates)
        or review.get("required_route_pages")
        != _required_route_count(_matrix_rows_from_bytes(snapshot.matrix_bytes))
        or review.get("required_tasks") != snapshot.catalog["task_count"]
    ):
        return None

    approvals = _mapping(evidence.get("approvals"))
    owner = _approval_attestation(
        approvals.get("owner"),
        role="owner",
        candidate_binding=binding,
        source_sha256=source_sha256,
        review_reference=review_reference,
        review_sha256=review_sha256,
        observation_end=observation_end,
        reviewed_at=reviewed_at,
        as_of=as_of,
        evidence_root=evidence_root,
    )
    reviewer = _approval_attestation(
        approvals.get("reviewer"),
        role="reviewer",
        candidate_binding=binding,
        source_sha256=source_sha256,
        review_reference=review_reference,
        review_sha256=review_sha256,
        observation_end=observation_end,
        reviewed_at=reviewed_at,
        as_of=as_of,
        evidence_root=evidence_root,
    )
    if owner is None or reviewer is None or owner[0] == reviewer[0]:
        return None
    artifacts = (
        (review_path, review_sha256),
        (owner[2], owner[3]),
        (reviewer[2], reviewer[3]),
    )
    return FinalAuthorization(
        binding=binding,
        approved_at=max(owner[1], reviewer[1]),
        artifact_digests=artifacts,
    )


def _commit_contains_artifacts(
    commit: str,
    artifacts: tuple[tuple[Path, str], ...],
    *,
    repository_root: Path,
) -> bool:
    """Require final authorization artifacts to predate a cleanup candidate."""

    for path, digest in artifacts:
        content = _git_source_bytes(commit, path, root=repository_root)
        if content is None:
            return False
        if path.suffix.lower() in NORMALIZED_EVIDENCE_SUFFIXES:
            content = _normalized_bytes(content)
        if _sha256(content) != digest:
            return False
    return True


def _deleted_source_is_absent(path: str, *, repository_root: Path) -> bool:
    """Reject absolute/traversing template paths and require physical removal."""

    relative = Path(path)
    if relative.is_absolute():
        return False
    root = repository_root.resolve()
    resolved = (root / relative).resolve()
    return resolved.is_relative_to(root) and not resolved.exists()


def _rollback_manifest_matches(
    value: dict[str, Any],
    *,
    wave: str,
    authorization: FinalAuthorization,
    candidate_binding: CandidateBinding,
    deleted_paths: set[str],
    rows_by_path: dict[str, dict[str, str]],
    repository_root: Path,
) -> bool:
    """Validate the exact per-wave rollback map and source lineage."""

    rollback_values = _mapping(value.get("route_rollback_commits"))
    expected_rollbacks = {
        path: str(rows_by_path[path].get("rollback_commit") or "").strip()
        for path in sorted(deleted_paths)
    }
    return bool(
        set(value) == CLEANUP_ROLLBACK_FIELDS
        and value.get("version") == CLEANUP_ROLLBACK_VERSION
        and value.get("wave") == wave
        and value.get("authorized_candidate_commit") == authorization.binding["candidate_commit"]
        and value.get("cleanup_candidate_commit") == candidate_binding["candidate_commit"]
        and value.get("deleted_paths") == sorted(deleted_paths)
        and rollback_values == expected_rollbacks
        and all(
            commit
            and _git_commit_is_ancestor(
                commit,
                root=repository_root,
                descendant=candidate_binding["candidate_commit"],
            )
            for commit in expected_rollbacks.values()
        )
    )


def _non_negative_int(value: object) -> int | None:
    """Return one non-negative integer while rejecting booleans."""

    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _observation_window(
    value: dict[str, Any],
    *,
    wave: str,
    candidate: CandidateSnapshot,
    as_of: date,
) -> tuple[datetime, datetime] | None:
    """Recompute the 48-hour, scheduled-cycle, defect, and error gates."""

    expected_fields = {
        "version",
        "wave",
        "candidate_binding",
        "observed_from",
        "observed_until",
        "scheduled_cycles",
        "defects",
        "error_metrics",
    }
    if (
        set(value) != expected_fields
        or value.get("version") != CLEANUP_OBSERVATION_VERSION
        or value.get("wave") != wave
        or not binding_matches(value.get("candidate_binding"), candidate.binding)
    ):
        return None
    observed_from = _parse_datetime(value.get("observed_from"))
    observed_until = _parse_datetime(value.get("observed_until"))
    if (
        observed_from is None
        or observed_until is None
        or (observed_until - observed_from).total_seconds() < 48 * 60 * 60
        or observed_until.date() > as_of
    ):
        return None

    cycles = value.get("scheduled_cycles")
    if not isinstance(cycles, list) or not cycles:
        return None
    cycle_tasks: set[str] = set()
    for raw_cycle in cycles:
        cycle = _mapping(raw_cycle)
        task_key = str(cycle.get("task_key") or "").strip()
        observed_at = _parse_datetime(cycle.get("observed_at"))
        if (
            set(cycle) != {"task_key", "observed_at", "outcome"}
            or task_key not in candidate.catalog["task_keys"]
            or task_key in cycle_tasks
            or observed_at is None
            or not observed_from <= observed_at <= observed_until
            or cycle.get("outcome") != "success"
        ):
            return None
        cycle_tasks.add(task_key)

    defects = _mapping(value.get("defects"))
    if set(defects) != {"new_p0", "new_p1", "open_p0", "open_p1"} or any(
        _non_negative_int(defects.get(key)) != 0
        for key in ("new_p0", "new_p1", "open_p0", "open_p1")
    ):
        return None

    metrics = value.get("error_metrics")
    if not isinstance(metrics, list) or not metrics:
        return None
    metric_tasks: set[str] = set()
    metric_fields = {
        "task_key",
        "baseline_requests",
        "baseline_errors",
        "candidate_requests",
        "candidate_errors",
    }
    for raw_metric in metrics:
        metric = _mapping(raw_metric)
        task_key = str(metric.get("task_key") or "").strip()
        baseline_requests = _non_negative_int(metric.get("baseline_requests"))
        baseline_errors = _non_negative_int(metric.get("baseline_errors"))
        candidate_requests = _non_negative_int(metric.get("candidate_requests"))
        candidate_errors = _non_negative_int(metric.get("candidate_errors"))
        if (
            set(metric) != metric_fields
            or task_key not in candidate.catalog["task_keys"]
            or task_key in metric_tasks
            or baseline_requests is None
            or baseline_requests < 20
            or candidate_requests is None
            or candidate_requests < 20
            or baseline_errors is None
            or baseline_errors > baseline_requests
            or candidate_errors is None
            or candidate_errors > candidate_requests
            or candidate_errors / candidate_requests - baseline_errors / baseline_requests > 0.005
        ):
            return None
        metric_tasks.add(task_key)
    return observed_from, observed_until


def _cleanup_waves_are_ready(
    evidence: dict[str, Any],
    *,
    rows_by_path: dict[str, dict[str, str]],
    new_deleted_paths: tuple[str, ...],
    authorization: FinalAuthorization,
    matrix_path: Path,
    catalog_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
    as_of: date,
    evidence_root: Path,
    repository_root: Path,
) -> tuple[bool, str]:
    """Validate every post-authorization M5-B wave and the current snapshot."""

    cleanup = _mapping(evidence.get("cleanup"))
    wave_values = cleanup.get("waves")
    if not isinstance(wave_values, list):
        return False, "cleanup.waves is missing"
    expected_by_wave: dict[str, set[str]] = {}
    for path in new_deleted_paths:
        wave = str(rows_by_path[path].get("wave") or "").strip()
        expected_by_wave.setdefault(wave, set()).add(path)
    wave_numbers = {
        wave: int(match.group(1))
        for wave in expected_by_wave
        if (match := WAVE_PATTERN.fullmatch(wave)) is not None
    }
    if set(wave_numbers) != set(expected_by_wave) or sorted(wave_numbers.values()) != list(
        range(1, len(wave_numbers) + 1)
    ):
        return False, "M5-B waves must be contiguous M5-B-W1..Wn"
    route_overflow = [
        wave
        for wave, paths in expected_by_wave.items()
        if sum(rows_by_path[path].get("template_role") == "route_page" for path in paths) > 10
    ]
    if route_overflow:
        return False, f"M5-B route wave exceeds 10 pages: {sorted(route_overflow)}"

    current_matrix_sha = _sha256(normalized_source_bytes(matrix_path))
    current_catalog_bytes = normalized_source_bytes(catalog_path)
    current_catalog = _catalog_identity(current_catalog_bytes, matrix_sha256=current_matrix_sha)
    if current_catalog is None:
        return False, "current catalog is not bound to the cleanup matrix"

    records_by_wave: dict[str, dict[str, Any]] = {}
    for raw_value in wave_values:
        value = _mapping(raw_value)
        wave = str(value.get("wave") or "").strip()
        if wave not in expected_by_wave or wave in records_by_wave:
            return False, f"cleanup wave set is stale or duplicated: {wave or '<blank>'}"
        records_by_wave[wave] = value
    if set(records_by_wave) != set(expected_by_wave):
        return False, "cleanup.waves does not cover every M5-B matrix wave"

    ordered_waves = sorted(expected_by_wave, key=wave_numbers.__getitem__)
    previous_commit = authorization.binding["candidate_commit"]
    previous_observed_until: datetime | None = None
    current_snapshot_wave: str | None = None
    for wave in ordered_waves:
        value = records_by_wave[wave]
        deleted_paths = {
            str(path).strip()
            for path in value.get("deleted_paths") or []
            if isinstance(path, str) and path.strip()
        }
        if (
            value.get("deleted_paths") != sorted(deleted_paths)
            or deleted_paths != expected_by_wave[wave]
        ):
            return False, f"cleanup wave paths do not match matrix: {wave}"
        if (
            set(value) != CLEANUP_WAVE_FIELDS
            or value.get("version") != CLEANUP_WAVE_VERSION
            or not binding_matches(
                value.get("authorized_candidate_binding"),
                authorization.binding,
            )
        ):
            return False, f"cleanup wave schema or authorization binding is invalid: {wave}"

        candidate = _candidate_snapshot(
            value.get("candidate_binding"),
            matrix_path=matrix_path,
            catalog_path=catalog_path,
            graph_path=graph_path,
            runtime_manifest_path=runtime_manifest_path,
            repository_root=repository_root,
        )
        if candidate is None:
            return False, f"cleanup candidate snapshot is invalid: {wave}"
        candidate_binding = candidate.binding
        if not _git_commit_is_ancestor(
            previous_commit,
            root=repository_root,
            descendant=candidate_binding["candidate_commit"],
        ) or not _commit_contains_artifacts(
            candidate_binding["candidate_commit"],
            authorization.artifact_digests,
            repository_root=repository_root,
        ):
            return False, f"cleanup candidate predates final authorization: {wave}"
        if value.get("catalog_sha256") != candidate.catalog["sha256"]:
            return False, f"cleanup catalog binding is invalid: {wave}"

        candidate_rows = {
            str(row.get("template_path") or "").strip(): row
            for row in _matrix_rows_from_bytes(candidate.matrix_bytes)
        }
        if any(
            path not in candidate_rows
            or candidate_rows[path].get("status") != "deleted"
            or candidate_rows[path].get("wave") != wave
            or candidate_rows[path].get("destination_class") not in {"A", "B"}
            for path in deleted_paths
        ):
            return False, f"cleanup candidate does not contain the declared wave: {wave}"

        owner = str(value.get("owner") or "").strip()
        reviewer = str(value.get("reviewer") or "").strip()
        verified_at = _parse_date(value.get("verified_at"))
        if (
            not owner
            or not reviewer
            or owner == reviewer
            or verified_at is None
            or _verified_repo_file(
                value.get("evidence"),
                value.get("evidence_sha256"),
                evidence_root=evidence_root,
            )
            is None
        ):
            return False, f"cleanup wave review evidence is invalid: {wave}"

        observation_artifact = _verified_repo_json(
            value.get("observation_ledger"),
            value.get("observation_ledger_sha256"),
            evidence_root=evidence_root,
        )
        observation = (
            _observation_window(
                observation_artifact[1],
                wave=wave,
                candidate=candidate,
                as_of=as_of,
            )
            if observation_artifact is not None
            else None
        )
        if (
            observation is None
            or observation[0].date() < authorization.approved_at
            or (previous_observed_until is not None and observation[0] < previous_observed_until)
            or verified_at is None
            or not observation[1].date() <= verified_at <= as_of
        ):
            return False, f"cleanup observation ledger is invalid or incomplete: {wave}"

        rollback_artifact = _verified_repo_json(
            value.get("rollback_manifest"),
            value.get("rollback_manifest_sha256"),
            evidence_root=evidence_root,
        )
        if rollback_artifact is None or not _rollback_manifest_matches(
            rollback_artifact[1],
            wave=wave,
            authorization=authorization,
            candidate_binding=candidate_binding,
            deleted_paths=deleted_paths,
            rows_by_path=rows_by_path,
            repository_root=repository_root,
        ):
            return False, f"cleanup rollback manifest is invalid: {wave}"

        current_binding = build_candidate_binding(
            stable_version=candidate_binding["candidate_version"],
            candidate_commit=candidate_binding["candidate_commit"],
            matrix_path=matrix_path,
            graph_path=graph_path,
            runtime_manifest_path=runtime_manifest_path,
        )
        if (
            binding_matches(candidate_binding, current_binding)
            and value.get("catalog_sha256") == current_catalog["sha256"]
        ):
            current_snapshot_wave = wave
        previous_commit = candidate_binding["candidate_commit"]
        previous_observed_until = observation[1]

    if current_snapshot_wave != ordered_waves[-1]:
        return False, "no cleanup wave is bound to the current post-deletion snapshot"
    return True, f"waves={len(ordered_waves)}; current_snapshot=true; observations=complete"


def evaluate_cleanup_guard(
    *,
    matrix_path: Path,
    catalog_path: Path,
    evidence_path: Path,
    as_of: date,
    graph_path: Path = DEFAULT_GRAPH,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
    evidence_root: Path = ROOT,
    repository_root: Path = ROOT,
) -> CleanupGuardResult:
    """Authorize new cleanup only from final approval plus exact wave evidence."""

    rows = _read_matrix_rows(matrix_path)
    matrix_paths = [row.get("template_path", "").strip() for row in rows]
    if any(not path for path in matrix_paths) or len(matrix_paths) != len(set(matrix_paths)):
        return CleanupGuardResult(
            allowed=False,
            new_deleted_paths=(),
            detail="migration matrix contains blank or duplicate template paths",
        )
    rows_by_path = dict(zip(matrix_paths, rows, strict=True))
    deleted_paths = {
        path
        for path, row in rows_by_path.items()
        if path and row.get("status", "").strip() == "deleted"
    }
    missing_baseline = sorted(M0_D_BASELINE_PATHS - deleted_paths)
    if missing_baseline:
        return CleanupGuardResult(
            allowed=False,
            new_deleted_paths=(),
            detail=f"M0-D baseline drift: missing={missing_baseline}",
        )

    new_deleted_paths = tuple(sorted(deleted_paths - M0_D_BASELINE_PATHS))
    if not new_deleted_paths:
        return CleanupGuardResult(
            allowed=True,
            new_deleted_paths=(),
            detail="no cleanup beyond the reviewed M0-D baseline",
        )

    invalid_rows = [
        path
        for path in new_deleted_paths
        if rows_by_path[path].get("destination_class", "").strip() not in {"A", "B"}
        or not rows_by_path[path].get("wave", "").strip().startswith("M5-B")
        or rows_by_path[path].get("legacy_url_policy", "").strip() not in LEGACY_URL_POLICIES
        or not rows_by_path[path].get("owner", "").strip()
        or not rows_by_path[path].get("reviewer", "").strip()
        or rows_by_path[path].get("owner", "").strip()
        == rows_by_path[path].get("reviewer", "").strip()
        or not _deleted_source_is_absent(path, repository_root=repository_root)
    ]
    if invalid_rows:
        return CleanupGuardResult(
            allowed=False,
            new_deleted_paths=new_deleted_paths,
            detail=(
                "new deletions require A/B M5-B lifecycle, independent review, "
                f"valid legacy policy, and physical removal: invalid={invalid_rows}"
            ),
        )

    try:
        evidence = _load_object(evidence_path)
        authorization = _final_authorization(
            evidence,
            matrix_path=matrix_path,
            catalog_path=catalog_path,
            graph_path=graph_path,
            runtime_manifest_path=runtime_manifest_path,
            as_of=as_of,
            evidence_root=evidence_root,
            repository_root=repository_root,
        )
        if authorization is None:
            return CleanupGuardResult(
                allowed=False,
                new_deleted_paths=new_deleted_paths,
                detail="final cutover authorization is missing or invalid",
            )
        waves_ready, wave_detail = _cleanup_waves_are_ready(
            evidence,
            rows_by_path=rows_by_path,
            new_deleted_paths=new_deleted_paths,
            authorization=authorization,
            matrix_path=matrix_path,
            catalog_path=catalog_path,
            graph_path=graph_path,
            runtime_manifest_path=runtime_manifest_path,
            as_of=as_of,
            evidence_root=evidence_root,
            repository_root=repository_root,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        waves_ready = False
        wave_detail = "cleanup evidence could not be validated"
    return CleanupGuardResult(
        allowed=waves_ready,
        new_deleted_paths=new_deleted_paths,
        detail=(f"new_deleted={len(new_deleted_paths)}; final_authorization=true; {wave_detail}"),
    )


def main() -> None:
    """Run the Classic cleanup guard for CI and local release checks."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    result = evaluate_cleanup_guard(
        matrix_path=args.matrix.resolve(),
        catalog_path=args.catalog.resolve(),
        evidence_path=args.evidence.resolve(),
        graph_path=args.graph.resolve(),
        runtime_manifest_path=args.runtime_manifest.resolve(),
        as_of=args.as_of,
    )
    marker = "PASS" if result.allowed else "FAIL"
    print(f"Web-to-TUI Classic cleanup guard: {marker} - {result.detail}")
    if not result.allowed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
