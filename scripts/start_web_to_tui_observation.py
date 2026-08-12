#!/usr/bin/env python
"""Start or reset the Web-to-TUI M5 candidate observation window safely."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

if __package__:
    from scripts.web_to_tui_candidate_binding import (
        CandidateBinding,
        build_candidate_binding,
        source_sha256,
    )
else:
    from web_to_tui_candidate_binding import (  # type: ignore[no-redef]
        CandidateBinding,
        build_candidate_binding,
        source_sha256,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
DEFAULT_GRAPH = ROOT / "config/tui/published/tui_operation_graph.published.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/tui/agomtui-runtime.manifest.json"
MINIMUM_OBSERVATION_DAYS = 14
DEPLOYMENT_ATTESTATION_VERSION = "web-to-tui-production-deployment-preflight.v1"
MAXIMUM_DEPLOYMENT_AGE = timedelta(hours=24)
MAXIMUM_PREFLIGHT_AGE = timedelta(minutes=30)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
OCI_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")


class ObservationStartError(RuntimeError):
    """Raised when a candidate observation window cannot be started safely."""


@dataclass(frozen=True)
class DeploymentPreflight:
    """Validated production deployment identity and health proof."""

    stable_version: str
    release_id: str
    source_commit: str
    deployed_at: datetime
    image_id: str
    oci_revision: str
    health_checked_at: datetime
    health_response_sha256: str
    readiness_response_sha256: str
    verified_at: datetime
    evidence: str
    evidence_sha256: str

    @property
    def released_at(self) -> date:
        """Use the fresh production verification date as the observation start."""

        return self.verified_at.date()


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ObservationStartError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _sha256(path: Path) -> str:
    """Return the normalized lowercase SHA-256 digest for one text source."""

    return source_sha256(path)


def _mapping(value: object, *, field: str) -> dict[str, Any]:
    """Return one mapping or fail closed with its field name."""

    if not isinstance(value, dict):
        raise ObservationStartError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _require_exact_fields(
    payload: dict[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    """Reject missing or semantically ignored attestation fields."""

    missing = sorted(expected - payload.keys())
    extra = sorted(payload.keys() - expected)
    if missing or extra:
        raise ObservationStartError(
            f"{field} fields do not match the deployment preflight contract; "
            f"missing={missing}; extra={extra}"
        )


def _required_string(value: object, *, field: str) -> str:
    """Return one non-empty string."""

    if not isinstance(value, str) or not value.strip():
        raise ObservationStartError(f"{field} must be a non-empty string")
    return value.strip()


def _aware_datetime(value: object, *, field: str) -> datetime:
    """Parse one timezone-aware ISO-8601 timestamp."""

    raw = _required_string(value, field=field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationStartError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ObservationStartError(f"{field} must include a timezone offset")
    return parsed


def _validate_probe(payload: object, *, field: str) -> str:
    """Validate one successful production health probe and return its response hash."""

    probe = _mapping(payload, field=field)
    _require_exact_fields(
        probe,
        {"http_status", "status", "response_sha256"},
        field=field,
    )
    if probe["http_status"] != 200 or probe["status"] != "ok":
        raise ObservationStartError(f"{field} does not prove a healthy production response")
    response_sha256 = _required_string(
        probe["response_sha256"], field=f"{field}.response_sha256"
    ).lower()
    if not SHA256_PATTERN.fullmatch(response_sha256):
        raise ObservationStartError(f"{field}.response_sha256 must be a SHA-256 digest")
    return response_sha256


def parse_deployment_preflight(
    payload: dict[str, Any],
    *,
    now: datetime,
    evidence: str,
    evidence_sha256: str,
) -> DeploymentPreflight:
    """Validate a fresh, candidate-bound production deployment preflight."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ObservationStartError("Observation clock must be timezone-aware")
    _require_exact_fields(
        payload,
        {
            "version",
            "environment",
            "release",
            "oci_image",
            "production_health",
            "verified_at",
        },
        field="deployment_preflight",
    )
    if payload["version"] != DEPLOYMENT_ATTESTATION_VERSION:
        raise ObservationStartError("Unsupported deployment preflight version")
    if payload["environment"] != "production":
        raise ObservationStartError("Deployment preflight must describe production")

    release = _mapping(payload["release"], field="deployment_preflight.release")
    _require_exact_fields(
        release,
        {"stable_version", "release_id", "source_commit", "deployed_at"},
        field="deployment_preflight.release",
    )
    stable_version = _required_string(
        release["stable_version"], field="deployment_preflight.release.stable_version"
    )
    if not VERSION_PATTERN.fullmatch(stable_version):
        raise ObservationStartError(f"Invalid stable version: {stable_version!r}")
    release_id = _required_string(
        release["release_id"], field="deployment_preflight.release.release_id"
    )
    if not VERSION_PATTERN.fullmatch(release_id):
        raise ObservationStartError(f"Invalid production release ID: {release_id!r}")
    source_commit = _required_string(
        release["source_commit"], field="deployment_preflight.release.source_commit"
    ).lower()
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ObservationStartError("Deployment source commit must be a full Git object ID")
    deployed_at = _aware_datetime(
        release["deployed_at"], field="deployment_preflight.release.deployed_at"
    )

    image = _mapping(payload["oci_image"], field="deployment_preflight.oci_image")
    _require_exact_fields(
        image,
        {"image_id", "revision"},
        field="deployment_preflight.oci_image",
    )
    image_id = _required_string(
        image["image_id"], field="deployment_preflight.oci_image.image_id"
    ).lower()
    if not OCI_IMAGE_ID_PATTERN.fullmatch(image_id):
        raise ObservationStartError("OCI image ID must be a sha256 digest")
    oci_revision = _required_string(
        image["revision"], field="deployment_preflight.oci_image.revision"
    ).lower()
    if oci_revision != source_commit:
        raise ObservationStartError("OCI revision does not match the deployed source commit")

    health = _mapping(payload["production_health"], field="deployment_preflight.production_health")
    _require_exact_fields(
        health,
        {"checked_at", "health", "readiness"},
        field="deployment_preflight.production_health",
    )
    health_checked_at = _aware_datetime(
        health["checked_at"], field="deployment_preflight.production_health.checked_at"
    )
    health_response_sha256 = _validate_probe(
        health["health"], field="deployment_preflight.production_health.health"
    )
    readiness_response_sha256 = _validate_probe(
        health["readiness"], field="deployment_preflight.production_health.readiness"
    )
    verified_at = _aware_datetime(payload["verified_at"], field="deployment_preflight.verified_at")

    current = now.astimezone(timezone.utc)
    deployment_time = deployed_at.astimezone(timezone.utc)
    health_time = health_checked_at.astimezone(timezone.utc)
    verification_time = verified_at.astimezone(timezone.utc)
    if not deployment_time <= health_time <= verification_time <= current:
        raise ObservationStartError(
            "Deployment, health, verification, and current timestamps are not monotonic"
        )
    if current - deployment_time > MAXIMUM_DEPLOYMENT_AGE:
        raise ObservationStartError(
            "Production deployment is too old to start a new observation window"
        )
    if current - health_time > MAXIMUM_PREFLIGHT_AGE:
        raise ObservationStartError("Production health proof is stale")
    if current - verification_time > MAXIMUM_PREFLIGHT_AGE:
        raise ObservationStartError("Deployment preflight is stale; backfill is forbidden")
    if not SHA256_PATTERN.fullmatch(evidence_sha256):
        raise ObservationStartError("Deployment preflight evidence digest is invalid")

    return DeploymentPreflight(
        stable_version=stable_version,
        release_id=release_id,
        source_commit=source_commit,
        deployed_at=deployed_at,
        image_id=image_id,
        oci_revision=oci_revision,
        health_checked_at=health_checked_at,
        health_response_sha256=health_response_sha256,
        readiness_response_sha256=readiness_response_sha256,
        verified_at=verified_at,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
    )


def _resolve_commit(value: str, *, root: Path = ROOT) -> str:
    """Resolve one Git revision to a full commit object ID."""

    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    commit = result.stdout.strip().lower()
    if result.returncode or not COMMIT_PATTERN.fullmatch(commit):
        raise ObservationStartError(f"Candidate commit is not resolvable: {value}")
    return commit


def _commit_is_ancestor(commit: str, *, root: Path = ROOT) -> bool:
    """Return whether a commit belongs to the current branch history."""

    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _file_at_commit(commit: str, path: Path, *, root: Path = ROOT) -> bytes:
    """Read a repository file exactly as stored in one commit."""

    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ObservationStartError(f"Path is outside the repository: {path}") from exc
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ObservationStartError(f"Candidate commit does not contain {relative}: {commit}")
    return result.stdout


def _load_committed_deployment_preflight(
    path: Path,
    *,
    now: datetime,
    root: Path = ROOT,
) -> DeploymentPreflight:
    """Load deployment proof only when its current bytes are committed at HEAD."""

    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ObservationStartError(
            "Deployment preflight evidence must be inside the repository"
        ) from exc
    current = path.read_bytes()
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ObservationStartError(
            "Deployment preflight evidence must be committed before observation starts"
        )
    if result.stdout != current:
        raise ObservationStartError(
            "Deployment preflight evidence differs from its committed HEAD bytes"
        )
    try:
        payload = cast(Any, json.loads(current.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationStartError(
            "Deployment preflight evidence is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ObservationStartError("Deployment preflight evidence must be a JSON object")
    digest = hashlib.sha256(current).hexdigest()
    return parse_deployment_preflight(
        cast(dict[str, Any], payload),
        now=now,
        evidence=relative,
        evidence_sha256=digest,
    )


def _worktree_changes(*, root: Path = ROOT) -> list[str]:
    """Return every tracked or untracked worktree change."""

    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ObservationStartError("Unable to inspect the Git worktree")
    return [line for line in result.stdout.splitlines() if line.strip()]


def validate_candidate_source(
    *,
    candidate_commit: str,
    matrix_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
    evidence: dict[str, Any],
    require_clean: bool,
    root: Path = ROOT,
) -> None:
    """Validate that the candidate, matrix, evidence, and worktree are consistent."""

    if not _commit_is_ancestor(candidate_commit, root=root):
        raise ObservationStartError(
            "Candidate commit is not an ancestor of the current branch HEAD"
        )
    for path, label in (
        (matrix_path, "migration matrix"),
        (graph_path, "published TUI graph"),
        (runtime_manifest_path, "TUI runtime manifest"),
    ):
        committed = _file_at_commit(candidate_commit, path, root=root)
        if source_sha256(path) != hashlib.sha256(committed).hexdigest():
            raise ObservationStartError(
                f"Candidate commit contains a different {label}; commit the current M5 "
                "source snapshot before starting observation"
            )
    evidence_source_sha256 = str(evidence.get("source_sha256") or "").strip()
    if evidence_source_sha256 != source_sha256(matrix_path):
        raise ObservationStartError(
            "Cutover evidence source_sha256 does not match the current migration matrix"
        )
    if require_clean:
        changes = _worktree_changes(root=root)
        if changes:
            raise ObservationStartError(
                f"Worktree must be clean before observation starts ({len(changes)} changes found)"
            )


def _blank_candidate_bound_sections(payload: dict[str, Any]) -> None:
    """Clear evidence that must never carry across candidate versions."""

    payload["uat"] = {
        "candidate_binding": None,
        "evidence": None,
        "evidence_sha256": None,
        "passed_route_pages": [],
    }
    payload["cleanup"] = {
        "candidate_binding": None,
        "evidence": None,
        "evidence_sha256": None,
        "passed_route_pages": [],
        "scope_coverage": {},
        "route_rollback_commits": {},
    }
    payload["defects"] = {
        "candidate_version": None,
        "candidate_commit": None,
        "source_sha256": None,
        "window_start": None,
        "window_end": None,
        "new_p0": None,
        "new_p1": None,
        "open_p0": None,
        "open_p1": None,
        "evidence": None,
        "query_scope": None,
        "query_filter": None,
        "snapshot_sha256": None,
        "queried_at": None,
    }
    payload["telemetry"] = {
        "window_start": None,
        "window_end": None,
        "collected_at": None,
        "environment": None,
        "evidence": None,
        "snapshot_sha256": None,
        "tasks": [],
    }
    if not isinstance(payload.get("rollback"), dict):
        raise ObservationStartError("Cutover evidence is missing rollback")
    payload["rollback"] = {
        "candidate_binding": None,
        "passed": None,
        "environment": None,
        "performed_at": None,
        "evidence": None,
        "evidence_sha256": None,
        "production_registry_backup": None,
    }
    payload["review_snapshot"] = {"evidence": None, "sha256": None}
    payload["approvals"] = {"owner": None, "reviewer": None}


def prepare_observation_evidence(
    evidence: dict[str, Any],
    *,
    deployment: DeploymentPreflight,
    candidate_binding: CandidateBinding,
    replace: bool,
) -> dict[str, Any]:
    """Return evidence bound to one candidate and a complete 14-day window."""

    if (
        candidate_binding["candidate_version"] != deployment.stable_version
        or candidate_binding["candidate_commit"] != deployment.source_commit
    ):
        raise ObservationStartError("Candidate binding does not match deployment version/commit")
    released_at = deployment.released_at
    observation_end = released_at + timedelta(days=MINIMUM_OBSERVATION_DAYS)
    requested = {
        "stable_version": deployment.stable_version,
        "candidate_commit": deployment.source_commit,
        "released_at": released_at.isoformat(),
        "observation_end": observation_end.isoformat(),
        "binding": dict(candidate_binding),
        "deployment_preflight": {
            "version": DEPLOYMENT_ATTESTATION_VERSION,
            "evidence": deployment.evidence,
            "evidence_sha256": deployment.evidence_sha256,
            "release_id": deployment.release_id,
            "source_commit": deployment.source_commit,
            "deployed_at": deployment.deployed_at.isoformat(),
            "image_id": deployment.image_id,
            "oci_revision": deployment.oci_revision,
            "health_checked_at": deployment.health_checked_at.isoformat(),
            "health_response_sha256": deployment.health_response_sha256,
            "readiness_response_sha256": deployment.readiness_response_sha256,
            "verified_at": deployment.verified_at.isoformat(),
        },
    }
    current = evidence.get("candidate")
    current_candidate = current if isinstance(current, dict) else {}
    has_current = any(value is not None and value != "" for value in current_candidate.values())
    same_candidate = current_candidate == requested
    if has_current and not same_candidate and not replace:
        raise ObservationStartError(
            "A different candidate is already bound; use --replace to reset candidate-bound evidence"
        )

    prepared = copy.deepcopy(evidence)
    if not same_candidate:
        _blank_candidate_bound_sections(prepared)
    prepared["candidate"] = requested
    return prepared


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
    parser.add_argument("--deployment-attestation", required=True, type=Path)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Reset candidate-bound production evidence when changing candidate.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the validated candidate window; the default is a dry run.",
    )
    args = parser.parse_args()

    try:
        now = datetime.now(timezone.utc)
        matrix_path = args.matrix.resolve()
        graph_path = args.graph.resolve()
        runtime_manifest_path = args.runtime_manifest.resolve()
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        deployment = _load_committed_deployment_preflight(
            args.deployment_attestation.resolve(),
            now=now,
        )
        candidate_commit = _resolve_commit(deployment.source_commit)
        if candidate_commit != deployment.source_commit:
            raise ObservationStartError(
                "Deployment source commit does not resolve to its attested object ID"
            )
        validate_candidate_source(
            candidate_commit=candidate_commit,
            matrix_path=matrix_path,
            graph_path=graph_path,
            runtime_manifest_path=runtime_manifest_path,
            evidence=evidence,
            require_clean=True,
        )
        prepared = prepare_observation_evidence(
            evidence,
            deployment=deployment,
            candidate_binding=build_candidate_binding(
                stable_version=deployment.stable_version,
                candidate_commit=candidate_commit,
                matrix_path=matrix_path,
                graph_path=graph_path,
                runtime_manifest_path=runtime_manifest_path,
            ),
            replace=args.replace,
        )
        if args.write:
            _write_json_atomic(evidence_path, prepared)
    except (OSError, json.JSONDecodeError, ObservationStartError, ValueError) as exc:
        print(f"Web-to-TUI M5 observation: FAIL - {exc}")
        return 1

    mode = "STARTED" if args.write else "READY (dry-run)"
    candidate = cast(dict[str, Any], prepared["candidate"])
    print(
        f"Web-to-TUI M5 observation: {mode} - "
        f"version={candidate['stable_version']} commit={candidate['candidate_commit']} "
        f"release={deployment.release_id} image={deployment.image_id} "
        f"window={candidate['released_at']}..{candidate['observation_end']} "
        f"deployment_attestation_sha256={deployment.evidence_sha256} "
        f"matrix_sha256={_sha256(matrix_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
