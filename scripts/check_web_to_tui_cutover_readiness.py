#!/usr/bin/env python
"""Evaluate the machine-readable Web-to-TUI M5 cutover gates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import urlparse

module_prefix = "scripts." if __package__ else ""
defect_evidence_builder: Any = importlib.import_module(
    f"{module_prefix}build_web_to_tui_defect_evidence"
)
production_telemetry_builder: Any = importlib.import_module(
    f"{module_prefix}build_web_to_tui_production_telemetry"
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
BACKUP_LOCATION_SCHEMES = frozenset({"artifact", "s3", "sftp", "https"})
LEGACY_URL_POLICIES = frozenset({"redirect_to_tui", "retain", "remove_410", "remove_404"})
REQUIRED_ROUTE_CLOSURE_SCOPES = frozenset(
    {"primary_task", "permission", "empty_state", "error_state", "legacy_url", "rollback"}
)
DEFECT_QUERY_SCOPE = "created_or_open_during_candidate_window"


class ClassicRouteRecord(TypedDict):
    """Minimal telemetry catalog route used by the cutover gate."""

    task_key: str


class TelemetryCatalog(TypedDict):
    """Minimal bounded telemetry catalog used by the cutover gate."""

    source_sha256: str
    classic_routes: list[ClassicRouteRecord]


@dataclass(frozen=True)
class GateResult:
    """One independently auditable M5 gate result."""

    key: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReadinessResult:
    """Complete machine-readable M5 decision."""

    decision: str
    as_of: str
    required_route_pages: int
    required_tasks: int
    gates: list[GateResult]


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _parse_date(value: object) -> date | None:
    """Parse one optional ISO date without accepting datetimes implicitly."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _string_set(value: object) -> set[str]:
    """Return a normalized string set for one JSON array boundary."""

    if not isinstance(value, list):
        return set()
    return {item.strip() for item in value if isinstance(item, str) and item.strip()}


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _non_negative_int(value: object) -> int | None:
    """Return one non-negative integer while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _repo_evidence_path(value: object, *, root: Path = ROOT) -> Path | None:
    """Resolve an existing repository evidence file without allowing traversal."""

    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute():
        return None
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        return None
    return resolved


def _valid_sha256(value: object) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""

    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value.strip()))


def _valid_candidate_commit(value: object) -> bool:
    """Return whether a value is a full SHA-1 or SHA-256 Git object ID."""

    return isinstance(value, str) and bool(COMMIT_PATTERN.fullmatch(value.strip()))


def _candidate_commit_exists(value: object) -> bool:
    """Return whether a full object ID resolves to a commit in this repository."""

    if not _valid_candidate_commit(value):
        return False
    commit = str(value).strip()
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _candidate_commit_is_ancestor(value: object) -> bool:
    """Return whether a full commit belongs to the current branch history."""

    if not _candidate_commit_exists(value):
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", str(value).strip(), "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _candidate_contains_matrix(
    value: object,
    *,
    matrix_path: Path,
    matrix_sha256: str,
) -> bool:
    """Return whether a commit stores the exact migration matrix under review."""

    if not _candidate_commit_is_ancestor(value):
        return False
    try:
        relative = matrix_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "show", f"{str(value).strip()}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and hashlib.sha256(result.stdout).hexdigest() == matrix_sha256


def _valid_backup_location(value: object) -> bool:
    """Return whether a backup uses an explicit approved external locator."""

    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in BACKUP_LOCATION_SCHEMES and bool(parsed.netloc or parsed.path)


def _verified_repo_evidence(
    value: object,
    digest: object,
    *,
    root: Path = ROOT,
) -> Path | None:
    """Resolve one evidence file only when its checked-in SHA-256 matches."""

    path = _repo_evidence_path(value, root=root)
    if path is None or not _valid_sha256(digest):
        return None
    expected = str(digest).strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return path if actual == expected else None


def _bound_approval(
    value: object,
    *,
    stable_version: str,
    candidate_commit: str,
    source_sha256: str,
    evidence_snapshot_sha256: str,
    observation_end: date | None,
    as_of: date,
) -> tuple[str, bool]:
    """Validate one approval and bind it to the exact cutover candidate."""

    approval = _mapping(value)
    name = str(approval.get("name") or "").strip()
    approved_at = _parse_date(approval.get("approved_at"))
    passed = bool(
        name
        and approval.get("decision") == "approve"
        and str(approval.get("candidate_version") or "").strip() == stable_version
        and str(approval.get("candidate_commit") or "").strip() == candidate_commit
        and str(approval.get("source_sha256") or "").strip() == source_sha256
        and str(approval.get("evidence_snapshot_sha256") or "").strip() == evidence_snapshot_sha256
        and approved_at
        and observation_end
        and observation_end <= approved_at <= as_of
    )
    return name, passed


def required_route_pages(matrix_path: Path) -> set[str]:
    """Derive every migrated A/B route page that requires task UAT."""

    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            str(row.get("template_path") or "").strip()
            for row in rows
            if row.get("template_role") == "route_page"
            and row.get("destination_class") in {"A", "B"}
            and row.get("status") in {"migrated", "deleted"}
            and str(row.get("template_path") or "").strip()
        }


def _route_cleanup_gate(
    matrix_path: Path,
    cleanup: dict[str, Any],
    required_routes: set[str],
    *,
    evidence_root: Path,
) -> GateResult:
    """Require per-route closure evidence before any Classic cleanup is allowed."""

    evidence_ok = (
        _verified_repo_evidence(
            cleanup.get("evidence"),
            cleanup.get("evidence_sha256"),
            root=evidence_root,
        )
        is not None
    )
    passed_routes = _string_set(cleanup.get("passed_route_pages"))
    scope_values = _mapping(cleanup.get("scope_coverage"))
    scope_schema_ok = set(scope_values) == REQUIRED_ROUTE_CLOSURE_SCOPES
    scope_routes: dict[str, set[str]] = {}
    scope_extras: set[str] = set()
    for scope in sorted(REQUIRED_ROUTE_CLOSURE_SCOPES):
        coverage = _mapping(scope_values.get(scope))
        explicit_routes = _string_set(coverage.get("route_pages"))
        scope_extras.update(explicit_routes - required_routes)
        if coverage.get("all_required") is True and not explicit_routes:
            scope_routes[scope] = set(required_routes)
        else:
            scope_routes[scope] = explicit_routes & required_routes
    fully_closed_routes = set.intersection(*scope_routes.values()) if scope_routes else set()
    passed_routes_ok = passed_routes == fully_closed_routes
    scope_ok = bool(
        scope_schema_ok
        and not scope_extras
        and all(routes == required_routes for routes in scope_routes.values())
    )

    rollback_values = _mapping(cleanup.get("route_rollback_commits"))
    rollback_mapping = {
        str(key).strip(): str(value).strip()
        for key, value in rollback_values.items()
        if isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
    }
    rollback_routes = set(rollback_mapping)
    rollback_key_ok = rollback_routes == required_routes
    rollback_scope_ok = rollback_routes == scope_routes.get("rollback", set())
    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        rows = {
            str(row.get("template_path") or "").strip(): row
            for row in csv.DictReader(handle)
            if str(row.get("template_path") or "").strip() in required_routes
        }
    matrix_rollback_mapping = {
        template_path: str(row.get("rollback_commit") or "").strip()
        for template_path, row in rows.items()
    }
    rollback_commits = set(rollback_mapping.values())
    rollback_matrix_ok = rollback_mapping == matrix_rollback_mapping
    rollback_ok = bool(
        rollback_key_ok
        and rollback_scope_ok
        and rollback_matrix_ok
        and len(rollback_commits) > 0
        and all(_candidate_commit_is_ancestor(commit) for commit in rollback_commits)
    )
    lifecycle_ok = len(rows) == len(required_routes) and all(
        str(row.get("legacy_url_policy") or "").strip() in LEGACY_URL_POLICIES
        and str(row.get("owner") or "").strip()
        and str(row.get("reviewer") or "").strip()
        and str(row.get("owner") or "").strip() != str(row.get("reviewer") or "").strip()
        for row in rows.values()
    )

    passed = bool(evidence_ok and passed_routes_ok and scope_ok and rollback_ok and lifecycle_ok)
    return GateResult(
        "route_cleanup_readiness",
        passed,
        f"covered={len(fully_closed_routes)}/{len(required_routes)}; "
        f"scope_counts={','.join(f'{scope}:{len(scope_routes[scope])}' for scope in sorted(scope_routes))}; "
        f"scopes={str(scope_ok).lower()}; "
        f"rollback={str(rollback_ok).lower()}; "
        f"rollback_matrix={str(rollback_matrix_ok).lower()}; "
        f"lifecycle={str(lifecycle_ok).lower()}; "
        f"evidence={str(evidence_ok).lower()}",
    )


def _load_catalog(path: Path) -> TelemetryCatalog:
    """Load the checked-in bounded task catalog."""

    payload = _load_object(path)
    route_values = payload.get("classic_routes")
    if not isinstance(route_values, list):
        raise ValueError("Telemetry catalog classic_routes must be a list")
    routes: list[ClassicRouteRecord] = []
    for value in route_values:
        record = _mapping(value)
        task_key = str(record.get("task_key") or "").strip()
        if not task_key:
            raise ValueError("Telemetry catalog route lacks task_key")
        routes.append({"task_key": task_key})
    return {
        "source_sha256": str(payload.get("source_sha256") or "").strip(),
        "classic_routes": routes,
    }


def required_task_keys(catalog: TelemetryCatalog) -> set[str]:
    """Derive the unique comparable tasks that require production evidence."""

    return {record["task_key"] for record in catalog["classic_routes"]}


def _valid_exception(value: object) -> bool:
    """Return whether one low-frequency exception has independent dual sign-off."""

    exception = _mapping(value)
    reason = str(exception.get("reason") or "").strip()
    owner = str(exception.get("owner") or "").strip()
    reviewer = str(exception.get("reviewer") or "").strip()
    return bool(reason and owner and reviewer and owner != reviewer)


def _telemetry_gate(
    telemetry: dict[str, Any],
    required_tasks: set[str],
    observation_start: date | None,
    observation_end: date | None,
    *,
    evidence_root: Path,
    structured_snapshot_ok: bool,
) -> GateResult:
    """Evaluate per-task traffic, error regression, and low-frequency exceptions."""

    window_start = _parse_date(telemetry.get("window_start"))
    window_end = _parse_date(telemetry.get("window_end"))
    collected_at = _parse_date(telemetry.get("collected_at"))
    evidence_ok = (
        _verified_repo_evidence(
            telemetry.get("evidence"),
            telemetry.get("snapshot_sha256"),
            root=evidence_root,
        )
        is not None
    )
    environment_ok = telemetry.get("environment") == "production"
    raw_tasks = telemetry.get("tasks")
    task_values = raw_tasks if isinstance(raw_tasks, list) else []
    task_records: dict[str, dict[str, Any]] = {}
    duplicate_keys: set[str] = set()
    for value in task_values:
        record = _mapping(value)
        task_key = str(record.get("task_key") or "").strip()
        if not task_key:
            continue
        if task_key in task_records:
            duplicate_keys.add(task_key)
        task_records[task_key] = record

    missing = required_tasks - set(task_records)
    extras = set(task_records) - required_tasks
    invalid_tasks: list[str] = []
    for task_key in sorted(required_tasks & set(task_records)):
        record = task_records[task_key]
        classic_entries = _non_negative_int(record.get("classic_entries"))
        tui_entries = _non_negative_int(record.get("tui_entries"))
        classic_requests = _non_negative_int(record.get("classic_task_requests"))
        tui_requests = _non_negative_int(record.get("tui_task_requests"))
        classic_errors = _non_negative_int(record.get("classic_task_errors"))
        tui_errors = _non_negative_int(record.get("tui_task_errors"))
        counts = (
            classic_entries,
            tui_entries,
            classic_requests,
            tui_requests,
            classic_errors,
            tui_errors,
        )
        if any(value is None for value in counts):
            invalid_tasks.append(task_key)
            continue
        assert classic_entries is not None
        assert tui_entries is not None
        assert classic_requests is not None
        assert tui_requests is not None
        assert classic_errors is not None
        assert tui_errors is not None
        if classic_errors > classic_requests or tui_errors > tui_requests:
            invalid_tasks.append(task_key)
            continue

        entry_samples = classic_entries + tui_entries
        task_invalid = False
        if entry_samples < 20:
            if not _valid_exception(record.get("low_frequency_exception")):
                task_invalid = True
        elif classic_entries / entry_samples > 0.05:
            task_invalid = True

        if classic_requests < 20 or tui_requests < 20:
            task_invalid = True
        else:
            classic_error_rate = classic_errors / classic_requests
            tui_error_rate = tui_errors / tui_requests
            if tui_error_rate - classic_error_rate > 0.005:
                task_invalid = True
        if task_invalid:
            invalid_tasks.append(task_key)

    window_ok = bool(
        window_start
        and window_end
        and observation_start
        and observation_end
        and window_start <= observation_start
        and window_end >= observation_end
        and (window_end - window_start).days >= 14
        and collected_at
        and collected_at >= window_end
    )
    passed = not (
        missing
        or extras
        or duplicate_keys
        or invalid_tasks
        or not window_ok
        or not evidence_ok
        or not environment_ok
        or not structured_snapshot_ok
    )
    detail = (
        f"covered={len(required_tasks) - len(missing)}/{len(required_tasks)}; "
        f"invalid={len(invalid_tasks)}; extras={len(extras)}; "
        f"duplicates={len(duplicate_keys)}; window_ok={str(window_ok).lower()}; "
        f"production_evidence={str(evidence_ok and environment_ok).lower()}; "
        f"structured_snapshot={str(structured_snapshot_ok).lower()}"
    )
    return GateResult("production_telemetry", passed, detail)


def _defect_snapshot_matches(
    *,
    defects: dict[str, Any],
    evidence: dict[str, Any],
    evidence_root: Path,
    as_of: date,
) -> bool:
    """Rebuild defect evidence from its structured snapshot and compare exactly."""

    snapshot_path = _verified_repo_evidence(
        defects.get("evidence"),
        defects.get("snapshot_sha256"),
        root=evidence_root,
    )
    if snapshot_path is None:
        return False
    try:
        snapshot = _load_object(snapshot_path)
        prepared = defect_evidence_builder.build_defect_evidence(
            snapshot=snapshot,
            evidence=evidence,
            snapshot_evidence_path=str(defects.get("evidence") or "").strip(),
            snapshot_sha256=str(defects.get("snapshot_sha256") or "").strip(),
            as_of=as_of,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        defect_evidence_builder.DefectEvidenceError,
    ):
        return False
    return _mapping(prepared.get("defects")) == defects


def _telemetry_snapshot_matches(
    *,
    telemetry: dict[str, Any],
    catalog: dict[str, Any],
    evidence: dict[str, Any],
    evidence_root: Path,
    as_of: date,
) -> bool:
    """Rebuild telemetry evidence from its structured snapshot and compare exactly."""

    snapshot_path = _verified_repo_evidence(
        telemetry.get("evidence"),
        telemetry.get("snapshot_sha256"),
        root=evidence_root,
    )
    if snapshot_path is None:
        return False
    try:
        snapshot = _load_object(snapshot_path)
        prepared = production_telemetry_builder.build_production_telemetry_evidence(
            snapshot=snapshot,
            catalog=catalog,
            evidence=evidence,
            snapshot_evidence_path=str(telemetry.get("evidence") or "").strip(),
            snapshot_sha256=str(telemetry.get("snapshot_sha256") or "").strip(),
            as_of=as_of,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        production_telemetry_builder.ProductionTelemetryError,
    ):
        return False
    return _mapping(prepared.get("telemetry")) == telemetry


def evaluate_readiness(
    *,
    matrix_path: Path,
    catalog_path: Path,
    evidence_path: Path,
    as_of: date,
    evidence_root: Path = ROOT,
) -> ReadinessResult:
    """Evaluate every M5 cutover requirement against current evidence."""

    matrix_bytes = matrix_path.read_bytes()
    matrix_sha256 = hashlib.sha256(matrix_bytes).hexdigest()
    catalog_payload = _load_object(catalog_path)
    catalog = _load_catalog(catalog_path)
    evidence = _load_object(evidence_path)
    routes = required_route_pages(matrix_path)
    tasks = required_task_keys(catalog)
    gates: list[GateResult] = []

    evidence_sha = str(evidence.get("source_sha256") or "").strip()
    source_ok = catalog["source_sha256"] == matrix_sha256 == evidence_sha
    gates.append(
        GateResult(
            "source_consistency",
            source_ok,
            f"matrix={matrix_sha256}; catalog={catalog['source_sha256']}; evidence={evidence_sha}",
        )
    )

    candidate = _mapping(evidence.get("candidate"))
    stable_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    released_at = _parse_date(candidate.get("released_at"))
    observation_end = _parse_date(candidate.get("observation_end"))
    candidate_source_ok = _candidate_contains_matrix(
        candidate_commit,
        matrix_path=matrix_path,
        matrix_sha256=matrix_sha256,
    )
    stable_window_ok = bool(
        stable_version
        and candidate_source_ok
        and released_at
        and observation_end
        and observation_end <= as_of
        and (observation_end - released_at).days >= 14
    )
    gates.append(
        GateResult(
            "stable_version_window",
            stable_window_ok,
            f"version={stable_version or 'missing'}; "
            f"commit={'verified_with_matrix' if candidate_source_ok else 'missing_or_source_mismatch'}; "
            f"released_at={released_at}; "
            f"observation_end={observation_end}; minimum_days=14",
        )
    )

    uat = _mapping(evidence.get("uat"))
    uat_evidence_ok = (
        _verified_repo_evidence(
            uat.get("evidence"),
            uat.get("evidence_sha256"),
            root=evidence_root,
        )
        is not None
    )
    passed_routes = _string_set(uat.get("passed_route_pages"))
    missing_routes = routes - passed_routes
    extra_routes = passed_routes - routes
    uat_ok = uat_evidence_ok and not missing_routes and not extra_routes
    gates.append(
        GateResult(
            "route_task_uat",
            uat_ok,
            f"covered={len(routes) - len(missing_routes)}/{len(routes)}; "
            f"extras={len(extra_routes)}; evidence={str(uat_evidence_ok).lower()}",
        )
    )
    gates.append(
        _route_cleanup_gate(
            matrix_path,
            _mapping(evidence.get("cleanup")),
            routes,
            evidence_root=evidence_root,
        )
    )

    defects = _mapping(evidence.get("defects"))
    defect_start = _parse_date(defects.get("window_start"))
    defect_end = _parse_date(defects.get("window_end"))
    new_p0 = _non_negative_int(defects.get("new_p0"))
    new_p1 = _non_negative_int(defects.get("new_p1"))
    open_p0 = _non_negative_int(defects.get("open_p0"))
    open_p1 = _non_negative_int(defects.get("open_p1"))
    defect_evidence_ok = (
        _verified_repo_evidence(
            defects.get("evidence"),
            defects.get("snapshot_sha256"),
            root=evidence_root,
        )
        is not None
    )
    defect_snapshot_ok = _defect_snapshot_matches(
        defects=defects,
        evidence=evidence,
        evidence_root=evidence_root,
        as_of=as_of,
    )
    defect_filter = str(defects.get("query_filter") or "").strip()
    defect_scope = str(defects.get("query_scope") or "").strip()
    defect_queried_at = _parse_date(defects.get("queried_at"))
    defect_binding_ok = bool(
        str(defects.get("candidate_version") or "").strip() == stable_version
        and str(defects.get("candidate_commit") or "").strip() == candidate_commit
        and str(defects.get("source_sha256") or "").strip() == evidence_sha
    )
    defects_ok = bool(
        released_at
        and observation_end
        and defect_start
        and defect_end
        and defect_start <= released_at
        and defect_end >= observation_end
        and new_p0 == 0
        and new_p1 == 0
        and open_p0 == 0
        and open_p1 == 0
        and defect_evidence_ok
        and defect_snapshot_ok
        and defect_binding_ok
        and defect_scope == DEFECT_QUERY_SCOPE
        and defect_filter
        and defect_queried_at
        and defect_queried_at >= defect_end
        and defect_queried_at <= as_of
    )
    gates.append(
        GateResult(
            "blocking_defects",
            defects_ok,
            f"window={defect_start}..{defect_end}; new_p0={new_p0}; new_p1={new_p1}; "
            f"open_p0={open_p0}; open_p1={open_p1}; "
            f"binding={str(defect_binding_ok).lower()}; "
            f"evidence={str(defect_evidence_ok).lower()}; "
            f"structured_snapshot={str(defect_snapshot_ok).lower()}",
        )
    )

    telemetry = _mapping(evidence.get("telemetry"))
    gates.append(
        _telemetry_gate(
            telemetry,
            tasks,
            released_at,
            observation_end,
            evidence_root=evidence_root,
            structured_snapshot_ok=_telemetry_snapshot_matches(
                telemetry=telemetry,
                catalog=catalog_payload,
                evidence=evidence,
                evidence_root=evidence_root,
                as_of=as_of,
            ),
        )
    )

    rollback = _mapping(evidence.get("rollback"))
    rollback_evidence = str(rollback.get("evidence") or "").strip()
    rollback_path = _verified_repo_evidence(
        rollback_evidence,
        rollback.get("evidence_sha256"),
        root=evidence_root,
    )
    rollback_ok = bool(
        rollback.get("passed") is True
        and rollback.get("environment") in {"local", "preproduction"}
        and _parse_date(rollback.get("performed_at"))
        and rollback_path
    )
    gates.append(
        GateResult(
            "rollback_drill",
            rollback_ok,
            f"environment={rollback.get('environment')}; evidence={rollback_evidence or 'missing'}",
        )
    )

    production_backup = _mapping(rollback.get("production_registry_backup"))
    backup_created_at = _parse_date(production_backup.get("created_at"))
    backup_verified_at = _parse_date(production_backup.get("restore_verified_at"))
    backup_retention_until = _parse_date(production_backup.get("retention_until"))
    backup_generation = _non_negative_int(production_backup.get("registry_generation"))
    backup_evidence_ok = (
        _verified_repo_evidence(
            production_backup.get("evidence"),
            production_backup.get("evidence_sha256"),
            root=evidence_root,
        )
        is not None
    )
    backup_ok = bool(
        backup_evidence_ok
        and _valid_backup_location(production_backup.get("location"))
        and _valid_sha256(production_backup.get("payload_sha256"))
        and _valid_sha256(production_backup.get("graph_hash"))
        and backup_generation is not None
        and backup_generation > 0
        and str(production_backup.get("schema_version") or "").strip()
        and str(production_backup.get("runtime_version") or "").strip()
        and str(production_backup.get("candidate_version") or "").strip() == stable_version
        and str(production_backup.get("candidate_commit") or "").strip() == candidate_commit
        and str(production_backup.get("source_sha256") or "").strip() == evidence_sha
        and production_backup.get("restore_dry_run_passed") is True
        and str(production_backup.get("verified_by") or "").strip()
        and backup_created_at
        and observation_end
        and backup_created_at >= observation_end
        and backup_verified_at
        and backup_created_at <= backup_verified_at <= as_of
        and backup_retention_until
        and backup_retention_until > as_of
    )
    gates.append(
        GateResult(
            "production_registry_backup",
            backup_ok,
            f"evidence={str(backup_evidence_ok).lower()}; "
            f"integrity={str(_valid_sha256(production_backup.get('payload_sha256'))).lower()}; "
            f"restore_verified={str(production_backup.get('restore_dry_run_passed') is True).lower()}",
        )
    )

    review_snapshot = _mapping(evidence.get("review_snapshot"))
    review_snapshot_sha256 = str(review_snapshot.get("sha256") or "").strip()
    review_snapshot_ok = (
        _verified_repo_evidence(
            review_snapshot.get("evidence"),
            review_snapshot_sha256,
            root=evidence_root,
        )
        is not None
    )
    approvals = _mapping(evidence.get("approvals"))
    owner, owner_ok = _bound_approval(
        approvals.get("owner"),
        stable_version=stable_version,
        candidate_commit=candidate_commit,
        source_sha256=evidence_sha,
        evidence_snapshot_sha256=review_snapshot_sha256,
        observation_end=observation_end,
        as_of=as_of,
    )
    reviewer, reviewer_ok = _bound_approval(
        approvals.get("reviewer"),
        stable_version=stable_version,
        candidate_commit=candidate_commit,
        source_sha256=evidence_sha,
        evidence_snapshot_sha256=review_snapshot_sha256,
        observation_end=observation_end,
        as_of=as_of,
    )
    approvals_ok = bool(review_snapshot_ok and owner_ok and reviewer_ok and owner != reviewer)
    gates.append(
        GateResult(
            "cutover_approvals",
            approvals_ok,
            f"owner={owner or 'missing'}; reviewer={reviewer or 'missing'}; "
            f"snapshot={str(review_snapshot_ok).lower()}",
        )
    )

    decision = "ALLOW" if all(gate.passed for gate in gates) else "DENY"
    return ReadinessResult(
        decision=decision,
        as_of=as_of.isoformat(),
        required_route_pages=len(routes),
        required_tasks=len(tasks),
        gates=gates,
    )


def main() -> None:
    """Run the M5 readiness evaluator."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-allow", action="store_true")
    args = parser.parse_args()

    result = evaluate_readiness(
        matrix_path=args.matrix.resolve(),
        catalog_path=args.catalog.resolve(),
        evidence_path=args.evidence.resolve(),
        as_of=args.as_of,
    )
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(f"Web-to-TUI M5 cutover: {result.decision} (as of {result.as_of})")
        for gate in result.gates:
            marker = "PASS" if gate.passed else "FAIL"
            print(f"[{marker}] {gate.key}: {gate.detail}")
    if args.require_allow and result.decision != "ALLOW":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
