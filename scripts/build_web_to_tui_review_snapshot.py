#!/usr/bin/env python
"""Build the immutable M5 pre-approval review snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_CATALOG = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
DEFAULT_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
SNAPSHOT_VERSION = "web-to-tui-cutover-review-snapshot.v1"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_PRE_APPROVAL_GATES = frozenset(
    {
        "source_consistency",
        "execution_dependency",
        "stable_version_window",
        "route_task_uat",
        "route_cleanup_readiness",
        "blocking_defects",
        "production_telemetry",
        "rollback_drill",
        "production_registry_backup",
    }
)

module_prefix = "scripts." if __package__ else ""
readiness_checker: Any = importlib.import_module(
    f"{module_prefix}check_web_to_tui_cutover_readiness"
)


class ReviewSnapshotError(RuntimeError):
    """Raised when the pre-approval gate set is incomplete or unsafe."""


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ReviewSnapshotError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _mapping(value: object) -> dict[str, Any]:
    """Narrow one dynamic JSON value to a mapping."""

    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _parse_date(value: object, *, field: str) -> date:
    """Parse one required ISO date."""

    if not isinstance(value, str) or not value.strip():
        raise ReviewSnapshotError(f"Missing date field: {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ReviewSnapshotError(f"Invalid date field: {field}") from exc


def build_review_snapshot(
    *,
    evidence: dict[str, Any],
    readiness: Any,
    reviewed_at: date,
) -> dict[str, Any]:
    """Return a candidate-bound snapshot only when all pre-approval gates pass."""

    candidate = _mapping(evidence.get("candidate"))
    candidate_version = str(candidate.get("stable_version") or "").strip()
    candidate_commit = str(candidate.get("candidate_commit") or "").strip()
    source_sha256 = str(evidence.get("source_sha256") or "").strip()
    observation_end = _parse_date(
        candidate.get("observation_end"), field="candidate.observation_end"
    )
    if (
        not candidate_version
        or not COMMIT_PATTERN.fullmatch(candidate_commit)
        or not SHA256_PATTERN.fullmatch(source_sha256)
    ):
        raise ReviewSnapshotError("Cutover evidence does not contain a complete candidate")
    if reviewed_at < observation_end or str(readiness.as_of) != reviewed_at.isoformat():
        raise ReviewSnapshotError("Review date must be the evaluated post-observation date")

    gates = [gate for gate in readiness.gates if gate.key != "cutover_approvals"]
    gate_keys = {str(gate.key) for gate in gates}
    if gate_keys != REQUIRED_PRE_APPROVAL_GATES:
        raise ReviewSnapshotError("Readiness result has an unexpected pre-approval gate set")
    failed = [str(gate.key) for gate in gates if gate.passed is not True]
    if failed:
        raise ReviewSnapshotError(f"Pre-approval gates are not ready: {', '.join(sorted(failed))}")

    return {
        "version": SNAPSHOT_VERSION,
        "candidate_version": candidate_version,
        "candidate_commit": candidate_commit,
        "source_sha256": source_sha256,
        "reviewed_at": reviewed_at.isoformat(),
        "as_of": str(readiness.as_of),
        "required_route_pages": int(readiness.required_route_pages),
        "required_tasks": int(readiness.required_tasks),
        "gates": [
            {
                "key": str(gate.key),
                "passed": bool(gate.passed),
                "detail": str(gate.detail),
            }
            for gate in gates
        ],
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one JSON object on disk."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--snapshot-output", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write the snapshot and update cutover evidence; default is a dry run.",
    )
    args = parser.parse_args()

    try:
        evidence_path = args.evidence.resolve()
        evidence = _load_object(evidence_path)
        result = readiness_checker.evaluate_readiness(
            matrix_path=args.matrix.resolve(),
            catalog_path=args.catalog.resolve(),
            evidence_path=evidence_path,
            as_of=args.as_of,
            evidence_root=ROOT,
        )
        snapshot = build_review_snapshot(
            evidence=evidence,
            readiness=result,
            reviewed_at=args.as_of,
        )
        output_path = args.snapshot_output.resolve()
        root = ROOT.resolve()
        if not output_path.is_relative_to(root):
            raise ReviewSnapshotError("Review snapshot must be written inside the repository")
        if output_path.exists() and not args.replace:
            raise ReviewSnapshotError(f"Refusing to overwrite review snapshot: {output_path}")
        serialized = (
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        evidence_reference = output_path.relative_to(root).as_posix()
        prepared = copy.deepcopy(evidence)
        prepared["review_snapshot"] = {
            "evidence": evidence_reference,
            "sha256": hashlib.sha256(serialized).hexdigest(),
        }
        prepared["approvals"] = {"owner": None, "reviewer": None}
        if args.write_evidence:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(output_path, snapshot)
            _write_json_atomic(evidence_path, prepared)
    except (OSError, ValueError, json.JSONDecodeError, ReviewSnapshotError) as exc:
        print(f"Web-to-TUI cutover review snapshot: FAIL - {exc}")
        return 1

    mode = "WRITTEN" if args.write_evidence else "READY (dry-run)"
    print(
        f"Web-to-TUI cutover review snapshot: {mode} - "
        f"candidate={snapshot['candidate_version']} gates={len(snapshot['gates'])} "
        f"sha256={hashlib.sha256(serialized).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
