#!/usr/bin/env python
"""Build candidate-bound M5 blocking-defect evidence from a reviewed snapshot."""

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

DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
SNAPSHOT_VERSION = "web-to-tui-blocking-defect-snapshot.v2"
QUERY_SCOPE = "created_or_open_during_candidate_window"
TRACKER_SYSTEMS = frozenset({"github", "jira", "linear"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?$")


class DefectEvidenceError(RuntimeError):
    """Raised when a defect snapshot is incomplete, stale, or unbound."""


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise DefectEvidenceError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _parse_date(value: object, *, field: str) -> date:
    """Parse one required ISO date field."""

    if not isinstance(value, str) or not value.strip():
        raise DefectEvidenceError(f"Missing date field: {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DefectEvidenceError(f"Invalid date field: {field}") from exc


def _optional_date(value: object, *, field: str) -> date | None:
    """Parse one nullable ISO date field."""

    if value is None:
        return None
    return _parse_date(value, field=field)


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


def _validate_tracker(snapshot: dict[str, Any]) -> str:
    """Validate the secret-free tracker query description and return its filter."""

    tracker = _mapping(snapshot.get("tracker"))
    if tracker.get("system") not in TRACKER_SYSTEMS:
        raise DefectEvidenceError("tracker.system is not approved")
    project = str(tracker.get("project") or "").strip()
    if not PROJECT_PATTERN.fullmatch(project):
        raise DefectEvidenceError("tracker.project is invalid")
    endpoint = str(tracker.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise DefectEvidenceError("tracker.endpoint must be a credential-free HTTPS URL")
    query_filter = str(tracker.get("query_filter") or "").strip()
    queried_by = str(tracker.get("queried_by") or "").strip()
    if not query_filter or not queried_by:
        raise DefectEvidenceError("tracker query_filter and queried_by are required")
    if snapshot.get("query_scope") != QUERY_SCOPE:
        raise DefectEvidenceError("snapshot query_scope is incomplete")
    return query_filter


def _derive_counts(
    snapshot: dict[str, Any],
    *,
    window_start: date,
    window_end: date,
) -> dict[str, int]:
    """Derive new and open-during-window P0/P1 counts from exact issue records."""

    raw_issues = snapshot.get("issues")
    if not isinstance(raw_issues, list):
        raise DefectEvidenceError("Snapshot issues must be a list")
    counts = {"new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0}
    issue_ids: set[str] = set()
    for index, raw_issue in enumerate(raw_issues):
        issue = _mapping(raw_issue)
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            raise DefectEvidenceError(f"Issue {index} has no id")
        if issue_id in issue_ids:
            raise DefectEvidenceError(f"Duplicate issue id: {issue_id}")
        issue_ids.add(issue_id)
        priority = str(issue.get("priority") or "").strip().upper()
        if priority not in {"P0", "P1"}:
            raise DefectEvidenceError(f"Issue {issue_id} is outside the P0/P1 query scope")
        state = str(issue.get("state") or "").strip().lower()
        if state not in {"open", "closed"}:
            raise DefectEvidenceError(f"Issue {issue_id} has an invalid state")
        created_at = _parse_date(issue.get("created_at"), field=f"{issue_id}.created_at")
        closed_at = _optional_date(issue.get("closed_at"), field=f"{issue_id}.closed_at")
        if state == "open" and closed_at is not None:
            raise DefectEvidenceError(f"Open issue {issue_id} cannot have closed_at")
        if state == "closed" and closed_at is None:
            raise DefectEvidenceError(f"Closed issue {issue_id} requires closed_at")
        if closed_at is not None and closed_at < created_at:
            raise DefectEvidenceError(f"Issue {issue_id} closes before it was created")

        created_during = window_start <= created_at <= window_end
        open_during = created_at <= window_end and (closed_at is None or closed_at >= window_start)
        if not (created_during or open_during):
            raise DefectEvidenceError(f"Issue {issue_id} is outside the declared query window")
        suffix = priority.lower()
        if created_during:
            counts[f"new_{suffix}"] += 1
        if open_during:
            counts[f"open_{suffix}"] += 1
    return counts


def build_defect_evidence(
    *,
    snapshot: dict[str, Any],
    evidence: dict[str, Any],
    snapshot_evidence_path: str,
    snapshot_sha256: str,
    as_of: datetime,
) -> dict[str, Any]:
    """Return cutover evidence populated from one validated issue-tracker snapshot."""

    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise DefectEvidenceError("Unsupported blocking-defect snapshot version")
    if not SHA256_PATTERN.fullmatch(snapshot_sha256):
        raise DefectEvidenceError("Snapshot SHA-256 is invalid")
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    if str(snapshot.get("source_sha256") or "").strip() != source_sha256:
        raise DefectEvidenceError("Snapshot and cutover evidence source SHA do not match")

    candidate = _mapping(evidence.get("candidate"))
    stable_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    if not stable_version or not _git_commit_is_usable(candidate_commit):
        raise DefectEvidenceError("Cutover evidence does not contain a usable candidate")
    if (
        str(snapshot.get("candidate_version") or "").strip() != stable_version
        or str(snapshot.get("candidate_commit") or "").strip() != candidate_commit
    ):
        raise DefectEvidenceError("Snapshot is bound to a different candidate")

    try:
        retained_observation = parse_retained_observation(candidate)
    except RetainedObservationError as exc:
        raise DefectEvidenceError(str(exc)) from exc
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise DefectEvidenceError("as_of must include an explicit UTC offset")
    reviewed_at = as_of.astimezone(UTC)

    released_at = _parse_date(candidate.get("released_at"), field="candidate.released_at")
    observation_end = _parse_date(
        candidate.get("observation_end"), field="candidate.observation_end"
    )
    window_start = _parse_date(snapshot.get("window_start"), field="snapshot.window_start")
    window_end = _parse_date(snapshot.get("window_end"), field="snapshot.window_end")
    try:
        queried_at = parse_utc_timestamp(snapshot.get("queried_at"), field="snapshot.queried_at")
    except RetainedObservationError as exc:
        raise DefectEvidenceError(str(exc)) from exc
    expected_window_start = retained_observation.first_retained_sample_at.date()
    expected_window_end = retained_observation.eligible_at.date()
    if (
        released_at > expected_window_start
        or observation_end != expected_window_end
        or window_start != expected_window_start
        or window_end != expected_window_end
    ):
        raise DefectEvidenceError("Snapshot window must exactly match the candidate window")
    if (window_end - window_start).days < 14:
        raise DefectEvidenceError("Candidate defect window is shorter than 14 days")
    if not retained_observation.eligible_at <= queried_at <= reviewed_at:
        raise DefectEvidenceError("Snapshot query timestamp is outside the exact review window")

    query_filter = _validate_tracker(snapshot)
    counts = _derive_counts(snapshot, window_start=window_start, window_end=window_end)
    prepared = copy.deepcopy(evidence)
    prepared["defects"] = {
        "candidate_version": stable_version,
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "new_p0": counts["new_p0"],
        "new_p1": counts["new_p1"],
        "open_p0": counts["open_p0"],
        "open_p1": counts["open_p1"],
        "evidence": snapshot_evidence_path,
        "query_scope": QUERY_SCOPE,
        "query_filter": query_filter,
        "snapshot_sha256": snapshot_sha256,
        "queried_at": utc_text(queried_at),
    }
    return prepared


def _repository_evidence_path(path: Path, *, root: Path = ROOT) -> str:
    """Return a repository-relative evidence path without allowing traversal."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise DefectEvidenceError("Defect snapshot must be stored inside the repository") from exc
    if not resolved.is_file():
        raise DefectEvidenceError(f"Defect snapshot file does not exist: {resolved}")
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
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--as-of",
        help="Exact UTC review timestamp; defaults to the current UTC time.",
    )
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write validated defect counts into cutover evidence; default is a dry run.",
    )
    parser.add_argument(
        "--require-clear",
        action="store_true",
        help="Exit non-zero when the validated snapshot contains any blocking defect.",
    )
    args = parser.parse_args()

    try:
        snapshot_path = args.snapshot.resolve()
        snapshot_evidence_path = _repository_evidence_path(snapshot_path)
        snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        snapshot = _load_object(snapshot_path)
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        current_time = datetime.now(UTC)
        as_of = parse_utc_timestamp(args.as_of, field="--as-of") if args.as_of else current_time
        if as_of > current_time:
            raise DefectEvidenceError("--as-of cannot be in the future")
        prepared = build_defect_evidence(
            snapshot=snapshot,
            evidence=evidence,
            snapshot_evidence_path=snapshot_evidence_path,
            snapshot_sha256=snapshot_sha256,
            as_of=as_of,
        )
        defects = cast(dict[str, Any], prepared["defects"])
        blocking = sum(
            cast(int, defects[key]) for key in ("new_p0", "new_p1", "open_p0", "open_p1")
        )
        if args.write_evidence:
            _write_json_atomic(evidence_path, prepared)
        if args.require_clear and blocking:
            raise DefectEvidenceError(f"Snapshot contains {blocking} blocking defect observations")
    except (
        OSError,
        json.JSONDecodeError,
        DefectEvidenceError,
        RetainedObservationError,
        ValueError,
    ) as exc:
        print(f"Web-to-TUI blocking defects: FAIL - {exc}")
        return 1

    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    decision = "CLEAR" if blocking == 0 else f"BLOCKED ({blocking})"
    print(f"Web-to-TUI blocking defects: {mode} - {decision} " f"snapshot_sha256={snapshot_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
