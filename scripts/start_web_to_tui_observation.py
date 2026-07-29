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
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
MINIMUM_OBSERVATION_DAYS = 14
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")


class ObservationStartError(RuntimeError):
    """Raised when a candidate observation window cannot be started safely."""


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ObservationStartError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        raise ObservationStartError(
            f"Candidate commit does not contain the migration matrix: {commit}"
        )
    return result.stdout


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
    evidence: dict[str, Any],
    require_clean: bool,
    root: Path = ROOT,
) -> None:
    """Validate that the candidate, matrix, evidence, and worktree are consistent."""

    if not _commit_is_ancestor(candidate_commit, root=root):
        raise ObservationStartError(
            "Candidate commit is not an ancestor of the current branch HEAD"
        )
    current_matrix = matrix_path.read_bytes()
    committed_matrix = _file_at_commit(candidate_commit, matrix_path, root=root)
    if hashlib.sha256(current_matrix).digest() != hashlib.sha256(committed_matrix).digest():
        raise ObservationStartError(
            "Candidate commit contains a different migration matrix; commit the current M5 "
            "scope before starting observation"
        )
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    if source_sha256 != hashlib.sha256(current_matrix).hexdigest():
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
    rollback = payload.get("rollback")
    if not isinstance(rollback, dict):
        raise ObservationStartError("Cutover evidence is missing rollback")
    rollback["production_registry_backup"] = None
    payload["review_snapshot"] = {"evidence": None, "sha256": None}
    payload["approvals"] = {"owner": None, "reviewer": None}


def prepare_observation_evidence(
    evidence: dict[str, Any],
    *,
    stable_version: str,
    candidate_commit: str,
    released_at: date,
    replace: bool,
) -> dict[str, Any]:
    """Return evidence bound to one candidate and a complete 14-day window."""

    if not VERSION_PATTERN.fullmatch(stable_version):
        raise ObservationStartError(f"Invalid stable version: {stable_version!r}")
    if not COMMIT_PATTERN.fullmatch(candidate_commit):
        raise ObservationStartError("Candidate commit must be a full Git object ID")

    observation_end = released_at + timedelta(days=MINIMUM_OBSERVATION_DAYS)
    requested = {
        "stable_version": stable_version,
        "candidate_commit": candidate_commit,
        "released_at": released_at.isoformat(),
        "observation_end": observation_end.isoformat(),
    }
    current = evidence.get("candidate")
    current_candidate = current if isinstance(current, dict) else {}
    has_current = any(value not in {None, ""} for value in current_candidate.values())
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
    parser.add_argument("--stable-version", required=True)
    parser.add_argument("--candidate-commit", default="HEAD")
    parser.add_argument("--released-at", required=True, type=date.fromisoformat)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
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
        if args.released_at > args.as_of:
            raise ObservationStartError("released-at cannot be in the future")
        matrix_path = args.matrix.resolve()
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        candidate_commit = _resolve_commit(args.candidate_commit)
        validate_candidate_source(
            candidate_commit=candidate_commit,
            matrix_path=matrix_path,
            evidence=evidence,
            require_clean=True,
        )
        prepared = prepare_observation_evidence(
            evidence,
            stable_version=args.stable_version,
            candidate_commit=candidate_commit,
            released_at=args.released_at,
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
        f"window={candidate['released_at']}..{candidate['observation_end']} "
        f"matrix_sha256={_sha256(matrix_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
