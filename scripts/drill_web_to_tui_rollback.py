#!/usr/bin/env python
"""Exercise a candidate-bound Web-to-TUI rollback without touching live state.

The drill resolves one immutable candidate commit, derives the pre-migration
baseline from the representative wave's anchor addition, and builds the patch
and artifact manifest from those two Git snapshots.  Both the historical and
candidate graph are validated against the schema and runtime manifest stored in
their own snapshot.  No working-tree content is used as release evidence.
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
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for

if __package__:
    from scripts.web_to_tui_candidate_binding import (
        BINDING_VERSION,
        CandidateBinding,
    )
else:
    from web_to_tui_candidate_binding import (
        BINDING_VERSION,
        CandidateBinding,
    )

ROOT = Path(__file__).resolve().parents[1]
WAVE = "M4-simulated-accounts-w51"

MATRIX_PATH = "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
GRAPH_PATH = "config/tui/published/tui_operation_graph.published.json"
SCHEMA_PATH = "config/tui/schema/tui_metadata.schema.v3.json"
RUNTIME_MANIFEST_PATH = "config/tui/agomtui-runtime.manifest.json"

# The first wave-owned adapter is an immutable historical anchor, not a mutable
# baseline constant. Its unique addition commit determines the baseline parent.
MIGRATION_ANCHOR_PATH = "apps/simulated_trading/interface/tui_serializers.py"

CLASSIC_TEMPLATE_PATHS = (
    "core/templates/simulated_trading/account_detail.html",
    "core/templates/simulated_trading/dashboard.html",
    "core/templates/simulated_trading/my_account_detail.html",
    "core/templates/simulated_trading/my_accounts.html",
)

# These are the representative wave's semantic rollback boundary. Existence and
# transition type are derived from Git; an added path is never hard-coded as such.
CORE_SCOPE_PATHS = (
    "apps/simulated_trading/interface/api_urls.py",
    MIGRATION_ANCHOR_PATH,
    "apps/simulated_trading/interface/tui_views.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_action_patch_execution.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_execution.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_injection_simulated_trading.py",
    "config/tui/ia/tui_information_architecture.v1.json",
    GRAPH_PATH,
    *CLASSIC_TEMPLATE_PATHS,
)

OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")


class RollbackDrillError(RuntimeError):
    """Raised when rollback evidence cannot be derived unambiguously."""


@dataclass(frozen=True)
class ArtifactSnapshot:
    """One artifact's exact state at the baseline and candidate commits."""

    path: str
    baseline: bytes | None
    candidate: bytes | None

    @property
    def transition(self) -> str:
        """Return the Git-like transition derived from the two snapshots."""

        if self.baseline is None and self.candidate is not None:
            return "added"
        if self.baseline is not None and self.candidate is None:
            return "deleted"
        if self.baseline is None and self.candidate is None:
            return "missing"
        if _canonical_bytes(cast(bytes, self.baseline)) == _canonical_bytes(
            cast(bytes, self.candidate)
        ):
            return "unchanged"
        return "modified"


def _run_git(*args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run one Git command without shell interpolation."""

    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    """Run one Git command and return stdout or fail with diagnostics."""

    result = _run_git(*args, input_bytes=input_bytes)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RollbackDrillError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def _canonical_bytes(content: bytes) -> bytes:
    """Normalize text line endings while leaving binary content unchanged."""

    if b"\x00" in content:
        return content
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _digest(content: bytes) -> str:
    """Return a platform-independent SHA-256 digest."""

    return hashlib.sha256(_canonical_bytes(content)).hexdigest()


def _raw_digest(content: bytes) -> str:
    """Return a raw-byte SHA-256 used by the runtime manifest."""

    return hashlib.sha256(content).hexdigest()


def _resolve_commit(revision: str) -> str:
    """Resolve a revision to one full commit object ID."""

    revision = revision.strip()
    if not revision:
        raise RollbackDrillError("candidate revision must not be empty")
    resolved = _git_bytes("rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    if not OBJECT_ID_PATTERN.fullmatch(resolved):
        raise RollbackDrillError(f"Git returned an invalid commit object ID: {resolved!r}")
    return resolved


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """Return whether one commit is an ancestor of another."""

    return _run_git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _snapshot_bytes(revision: str, relative_path: str) -> bytes | None:
    """Read one path from a Git snapshot, distinguishing absence from errors."""

    listing = _git_bytes("ls-tree", "--full-tree", "-z", revision, "--", relative_path)
    entries = [entry for entry in listing.split(b"\x00") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise RollbackDrillError(f"snapshot path is ambiguous at {revision}: {relative_path}")
    try:
        metadata, encoded_path = entries[0].split(b"\t", 1)
        _mode, object_type, _object_id = metadata.split(b" ", 2)
    except ValueError as exc:
        raise RollbackDrillError(
            f"cannot parse Git tree entry for {relative_path} at {revision}"
        ) from exc
    decoded_path = encoded_path.decode("utf-8")
    if decoded_path != relative_path or object_type != b"blob":
        raise RollbackDrillError(
            f"expected a blob at {relative_path} in {revision}, got {object_type!r}"
        )
    return _git_bytes("show", f"{revision}:{relative_path}")


def _required_snapshot_bytes(revision: str, relative_path: str) -> bytes:
    """Read one required file from a Git snapshot."""

    content = _snapshot_bytes(revision, relative_path)
    if content is None:
        raise RollbackDrillError(f"required artifact is missing at {revision}: {relative_path}")
    return content


def _derive_baseline_revision(candidate_commit: str) -> tuple[str, str]:
    """Derive the baseline from the anchor's unique addition commit."""

    output = _git_bytes(
        "log",
        "--format=%H",
        "--diff-filter=A",
        candidate_commit,
        "--",
        MIGRATION_ANCHOR_PATH,
    ).decode("ascii")
    additions = [line.strip() for line in output.splitlines() if line.strip()]
    if len(additions) != 1:
        raise RollbackDrillError(
            "migration anchor must have exactly one addition commit in the candidate "
            f"history; path={MIGRATION_ANCHOR_PATH}; additions={additions}"
        )
    migration_commit = _resolve_commit(additions[0])
    parent_line = (
        _git_bytes("rev-list", "--parents", "-n", "1", migration_commit).decode("ascii").strip()
    )
    parts = parent_line.split()
    if len(parts) != 2:
        raise RollbackDrillError(
            "migration anchor addition must be a single-parent commit; "
            f"commit={migration_commit}; parents={parts[1:]}"
        )
    baseline_commit = _resolve_commit(parts[1])
    if not _is_ancestor(baseline_commit, candidate_commit):
        raise RollbackDrillError("derived baseline is not an ancestor of the candidate")
    return baseline_commit, migration_commit


def _load_object(content: bytes, *, label: str) -> dict[str, Any]:
    """Decode one JSON object or fail closed."""

    try:
        payload = cast(Any, json.loads(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollbackDrillError(f"invalid JSON for {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RollbackDrillError(f"expected a JSON object for {label}")
    return cast(dict[str, Any], payload)


def _required_string(value: object, *, field: str) -> str:
    """Return one non-empty string field."""

    if not isinstance(value, str) or not value.strip():
        raise RollbackDrillError(f"{field} must be a non-empty string")
    return value.strip()


def _runtime_manifest(*, revision: str) -> tuple[dict[str, Any], tuple[str, ...], dict[str, Any]]:
    """Validate one snapshot's runtime manifest and every listed file digest."""

    content = _required_snapshot_bytes(revision, RUNTIME_MANIFEST_PATH)
    payload = _load_object(content, label=f"runtime manifest at {revision}")
    version = _required_string(payload.get("version"), field="runtime.version")
    build_id = _required_string(payload.get("build_id"), field="runtime.build_id")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise RollbackDrillError("runtime.files must be a non-empty object")

    verified_paths: list[str] = []
    for raw_path, raw_digest in sorted(files.items()):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise RollbackDrillError("runtime.files contains an invalid path")
        path = raw_path.strip().replace("\\", "/")
        if path.startswith("/") or ".." in Path(path).parts:
            raise RollbackDrillError(f"runtime manifest path escapes the repository: {path}")
        expected_digest = _required_string(raw_digest, field=f"runtime.files[{path}]").lower()
        if not SHA256_PATTERN.fullmatch(expected_digest):
            raise RollbackDrillError(f"runtime manifest digest is invalid: {path}")
        artifact = _required_snapshot_bytes(revision, path)
        actual_digest = _raw_digest(artifact)
        if actual_digest != expected_digest:
            raise RollbackDrillError(
                f"runtime manifest digest mismatch at {revision}: {path}; "
                f"expected={expected_digest}; actual={actual_digest}"
            )
        verified_paths.append(path)

    contract = {
        "version": version,
        "build_id": build_id,
        "manifest_sha256": _digest(content),
        "verified_files": len(verified_paths),
    }
    return payload, tuple(verified_paths), contract


def _validate_graph_snapshot(*, revision: str) -> dict[str, Any]:
    """Validate one graph with the schema stored in the same Git snapshot."""

    graph_bytes = _required_snapshot_bytes(revision, GRAPH_PATH)
    schema_bytes = _required_snapshot_bytes(revision, SCHEMA_PATH)
    graph = _load_object(graph_bytes, label=f"graph at {revision}")
    schema = _load_object(schema_bytes, label=f"schema at {revision}")
    try:
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        errors = sorted(
            validator_type(schema).iter_errors(graph),
            key=lambda error: [str(part) for part in error.absolute_path],
        )
    except SchemaError as exc:
        raise RollbackDrillError(f"invalid graph schema at {revision}: {exc.message}") from exc
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise RollbackDrillError(
            f"graph does not satisfy its snapshot schema at {revision}: "
            f"{location}: {first.message}"
        )
    screens = graph.get("screens")
    actions = graph.get("actions")
    if not isinstance(screens, list) or not isinstance(actions, list):
        raise RollbackDrillError("validated graph screens/actions must be arrays")
    schema_version = _required_string(graph.get("schema_version"), field="graph.schema_version")
    return {
        "schema_version": schema_version,
        "schema_sha256": _digest(schema_bytes),
        "screens": len(screens),
        "actions": len(actions),
    }


def _candidate_binding(*, candidate_version: str, candidate_commit: str) -> CandidateBinding:
    """Build the canonical binding entirely from the candidate Git snapshot."""

    if not VERSION_PATTERN.fullmatch(candidate_version):
        raise RollbackDrillError(f"invalid candidate version: {candidate_version!r}")
    matrix = _required_snapshot_bytes(candidate_commit, MATRIX_PATH)
    graph_bytes = _required_snapshot_bytes(candidate_commit, GRAPH_PATH)
    runtime_bytes = _required_snapshot_bytes(candidate_commit, RUNTIME_MANIFEST_PATH)
    graph = _load_object(graph_bytes, label="candidate graph")
    runtime = _load_object(runtime_bytes, label="candidate runtime manifest")
    return {
        "version": BINDING_VERSION,
        "candidate_version": candidate_version,
        "candidate_commit": candidate_commit,
        "matrix_sha256": _digest(matrix),
        "graph_sha256": _digest(graph_bytes),
        "schema_version": _required_string(
            graph.get("schema_version"), field="candidate graph.schema_version"
        ),
        "runtime_version": _required_string(
            runtime.get("version"), field="candidate runtime.version"
        ),
        "runtime_build_id": _required_string(
            runtime.get("build_id"), field="candidate runtime.build_id"
        ),
        "runtime_manifest_sha256": _digest(runtime_bytes),
    }


def _matrix_rollback_commits(candidate_commit: str) -> dict[str, str]:
    """Verify the representative templates' rollback commits in the bound matrix."""

    content = _required_snapshot_bytes(candidate_commit, MATRIX_PATH)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RollbackDrillError("candidate migration matrix is not UTF-8") from exc
    rows = csv.DictReader(io.StringIO(text))
    if rows.fieldnames is None or not {"template_path", "rollback_commit"}.issubset(
        rows.fieldnames
    ):
        raise RollbackDrillError("candidate matrix is missing rollback identity columns")
    selected: dict[str, str] = {}
    expected_paths = set(CLASSIC_TEMPLATE_PATHS)
    for row in rows:
        path = str(row.get("template_path") or "").strip().replace("\\", "/")
        if path not in expected_paths:
            continue
        if path in selected:
            raise RollbackDrillError(f"candidate matrix has duplicate template row: {path}")
        raw_commit = str(row.get("rollback_commit") or "").strip().lower()
        if not OBJECT_ID_PATTERN.fullmatch(raw_commit):
            raise RollbackDrillError(
                f"candidate matrix has invalid rollback commit for {path}: {raw_commit!r}"
            )
        resolved = _resolve_commit(raw_commit)
        if resolved != raw_commit or not _is_ancestor(resolved, candidate_commit):
            raise RollbackDrillError(
                f"candidate matrix rollback commit is not bound to candidate history: {path}"
            )
        selected[path] = resolved
    missing = sorted(expected_paths - selected.keys())
    if missing:
        raise RollbackDrillError(f"candidate matrix is missing wave templates: {missing}")
    return dict(sorted(selected.items()))


def _scope_snapshots(
    *,
    baseline_commit: str,
    candidate_commit: str,
    runtime_paths: tuple[str, ...],
) -> tuple[ArtifactSnapshot, ...]:
    """Build an exact rollback scope from baseline/candidate snapshots."""

    scope_paths = sorted(
        set(CORE_SCOPE_PATHS) | set(runtime_paths) | {RUNTIME_MANIFEST_PATH, SCHEMA_PATH}
    )
    snapshots = tuple(
        ArtifactSnapshot(
            path=path,
            baseline=_snapshot_bytes(baseline_commit, path),
            candidate=_snapshot_bytes(candidate_commit, path),
        )
        for path in scope_paths
    )
    missing_both = [item.path for item in snapshots if item.transition == "missing"]
    if missing_both:
        raise RollbackDrillError(
            f"rollback scope paths are missing in both snapshots: {missing_both}"
        )
    unchanged_core = [
        item.path
        for item in snapshots
        if item.path in CORE_SCOPE_PATHS and item.transition == "unchanged"
    ]
    if unchanged_core:
        raise RollbackDrillError(
            "representative rollback scope drifted; core paths are unchanged: " f"{unchanged_core}"
        )
    return snapshots


def _materialize_candidate(temp_root: Path, snapshots: tuple[ArtifactSnapshot, ...]) -> None:
    """Materialize the exact candidate state in an isolated directory."""

    for snapshot in snapshots:
        if snapshot.candidate is None:
            continue
        target = temp_root / snapshot.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(snapshot.candidate)


def _apply_patch(temp_root: Path, patch: bytes, *, reverse: bool) -> None:
    """Apply the candidate-bound patch inside the isolated directory."""

    command = ["git", "apply", "--binary", "--whitespace=nowarn"]
    if reverse:
        command.append("--reverse")
    command.append("-")
    result = subprocess.run(
        command,
        cwd=temp_root,
        input=patch,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        direction = "reverse" if reverse else "forward"
        raise RollbackDrillError(f"{direction} patch application failed: {message}")


def _assert_snapshot(
    temp_root: Path,
    snapshots: tuple[ArtifactSnapshot, ...],
    *,
    candidate: bool,
) -> None:
    """Verify every scoped artifact against one immutable Git snapshot."""

    label = "candidate" if candidate else "baseline"
    for snapshot in snapshots:
        expected = snapshot.candidate if candidate else snapshot.baseline
        path = temp_root / snapshot.path
        if expected is None:
            if path.exists():
                raise RollbackDrillError(
                    f"{label} snapshot expected an absent artifact: {snapshot.path}"
                )
            continue
        if not path.is_file():
            raise RollbackDrillError(f"{label} snapshot artifact is missing: {snapshot.path}")
        actual = path.read_bytes()
        if _canonical_bytes(actual) != _canonical_bytes(expected):
            raise RollbackDrillError(f"{label} snapshot content mismatch: {snapshot.path}")


def _manifest_projection(snapshots: tuple[ArtifactSnapshot, ...]) -> list[dict[str, Any]]:
    """Return a digest-only projection of the exercised artifact manifest."""

    return [
        {
            "path": snapshot.path,
            "transition": snapshot.transition,
            "baseline_sha256": (
                _digest(snapshot.baseline) if snapshot.baseline is not None else None
            ),
            "candidate_sha256": (
                _digest(snapshot.candidate) if snapshot.candidate is not None else None
            ),
        }
        for snapshot in snapshots
    ]


def run_drill(
    *,
    candidate_version: str,
    candidate_revision: str = "HEAD",
) -> dict[str, Any]:
    """Run the reversible isolated drill and return machine-readable evidence."""

    started = time.perf_counter()
    candidate_commit = _resolve_commit(candidate_revision)
    head_commit = _resolve_commit("HEAD")
    if not _is_ancestor(candidate_commit, head_commit):
        raise RollbackDrillError(
            "candidate commit must be reachable from the checked-out branch HEAD"
        )
    baseline_commit, migration_commit = _derive_baseline_revision(candidate_commit)
    matrix_commits = _matrix_rollback_commits(candidate_commit)

    _baseline_runtime, baseline_runtime_paths, baseline_runtime_contract = _runtime_manifest(
        revision=baseline_commit
    )
    _candidate_runtime, candidate_runtime_paths, candidate_runtime_contract = _runtime_manifest(
        revision=candidate_commit
    )
    runtime_paths = tuple(sorted(set(baseline_runtime_paths) | set(candidate_runtime_paths)))
    snapshots = _scope_snapshots(
        baseline_commit=baseline_commit,
        candidate_commit=candidate_commit,
        runtime_paths=runtime_paths,
    )
    changed_paths = tuple(
        snapshot.path for snapshot in snapshots if snapshot.transition != "unchanged"
    )
    if not changed_paths:
        raise RollbackDrillError("rollback patch scope contains no changed artifacts")

    patch = _git_bytes(
        "diff",
        "--binary",
        "--no-ext-diff",
        baseline_commit,
        candidate_commit,
        "--",
        *changed_paths,
    )
    if not patch.strip():
        raise RollbackDrillError("candidate-bound rollback patch is empty")
    diff_paths = {
        line.decode("utf-8")
        for line in _git_bytes(
            "diff",
            "--name-only",
            "-z",
            baseline_commit,
            candidate_commit,
            "--",
            *changed_paths,
        ).split(b"\x00")
        if line
    }
    if diff_paths != set(changed_paths):
        raise RollbackDrillError(
            "derived patch does not cover the exact changed scope; "
            f"expected={sorted(changed_paths)}; actual={sorted(diff_paths)}"
        )

    baseline_contract = _validate_graph_snapshot(revision=baseline_commit)
    candidate_contract = _validate_graph_snapshot(revision=candidate_commit)
    binding = _candidate_binding(
        candidate_version=candidate_version,
        candidate_commit=candidate_commit,
    )
    if candidate_contract["schema_version"] != binding["schema_version"]:
        raise RollbackDrillError("candidate graph validation disagrees with candidate binding")
    if (
        candidate_runtime_contract["version"] != binding["runtime_version"]
        or candidate_runtime_contract["build_id"] != binding["runtime_build_id"]
        or candidate_runtime_contract["manifest_sha256"] != binding["runtime_manifest_sha256"]
    ):
        raise RollbackDrillError("candidate runtime validation disagrees with candidate binding")

    with tempfile.TemporaryDirectory(prefix="agom-web-to-tui-rollback-") as temp_dir:
        temp_root = Path(temp_dir)
        _materialize_candidate(temp_root, snapshots)
        _assert_snapshot(temp_root, snapshots, candidate=True)

        rollback_started = time.perf_counter()
        _apply_patch(temp_root, patch, reverse=True)
        _assert_snapshot(temp_root, snapshots, candidate=False)
        rollback_seconds = time.perf_counter() - rollback_started

        restore_started = time.perf_counter()
        _apply_patch(temp_root, patch, reverse=False)
        _assert_snapshot(temp_root, snapshots, candidate=True)
        restore_seconds = time.perf_counter() - restore_started

    transition_counts = {
        transition: sum(1 for snapshot in snapshots if snapshot.transition == transition)
        for transition in ("added", "modified", "deleted", "unchanged")
    }
    return {
        "version": "web-to-tui-rollback-drill.v2",
        "ok": True,
        "wave": WAVE,
        "scope": "candidate-bound representative wave plus snapshot runtime bundle",
        "candidate_binding": binding,
        "migration_anchor_path": MIGRATION_ANCHOR_PATH,
        "migration_commit": migration_commit,
        "baseline_commit": baseline_commit,
        "matrix_rollback_commits": matrix_commits,
        "artifact_manifest": _manifest_projection(snapshots),
        "transition_counts": transition_counts,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "baseline_graph_hash": _digest(_required_snapshot_bytes(baseline_commit, GRAPH_PATH)),
        "candidate_graph_hash": binding["graph_sha256"],
        "baseline_contract": baseline_contract,
        "candidate_contract": candidate_contract,
        "baseline_runtime": baseline_runtime_contract,
        "candidate_runtime": candidate_runtime_contract,
        "rollback_seconds": round(rollback_seconds, 3),
        "restore_seconds": round(restore_seconds, 3),
        "total_seconds": round(time.perf_counter() - started, 3),
        "working_tree_read_as_candidate": False,
        "working_tree_unchanged": True,
    }


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Exercise a candidate-bound Web-to-TUI rollback in isolation."
    )
    parser.add_argument(
        "--candidate-version",
        required=True,
        help="Stable release identity that must match later M5 candidate evidence.",
    )
    parser.add_argument(
        "--candidate-ref",
        default="HEAD",
        help="Candidate commit/ref to exercise (resolved and recorded as a full object ID).",
    )
    args = parser.parse_args()
    evidence = run_drill(
        candidate_version=args.candidate_version,
        candidate_revision=args.candidate_ref,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
