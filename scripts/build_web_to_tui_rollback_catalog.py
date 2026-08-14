"""Build and verify per-route Web-to-TUI rollback commit evidence.

The command is deliberately fail-closed: it never invents a commit and refuses
to write cutover evidence while any migrated route still uses ``pending_commit``
or a commit outside the current branch history.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts.web_to_tui_candidate_binding import CandidateBinding
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from web_to_tui_candidate_binding import CandidateBinding

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_EVIDENCE_PATH = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MIGRATED_DESTINATIONS = {"A", "B"}
MIGRATED_STATUSES = {"migrated", "deleted"}
REQUIRED_CLEANUP_SCOPES = (
    "primary_task",
    "permission",
    "empty_state",
    "error_state",
    "legacy_url",
    "rollback",
)


class RollbackCatalogError(RuntimeError):
    """Raised when rollback evidence cannot be derived safely."""


def _required_route_rows(matrix_path: Path) -> list[dict[str, str]]:
    """Return the exact active migrated route set used by the M5 checker."""

    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle)
            if row.get("template_role") == "route_page"
            and row.get("destination_class") in MIGRATED_DESTINATIONS
            and row.get("status") in MIGRATED_STATUSES
        ]
    template_paths = [str(row.get("template_path") or "").strip() for row in rows]
    if not template_paths or any(not path for path in template_paths):
        raise RollbackCatalogError("migrated route set is empty or contains a blank template path")
    if len(template_paths) != len(set(template_paths)):
        raise RollbackCatalogError("migrated route set contains duplicate template paths")
    return rows


def _git_commit_is_usable(commit: str, *, root: Path = ROOT) -> bool:
    """Return whether a full commit exists and belongs to the current branch history."""

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


def build_rollback_catalog(
    matrix_path: Path,
    *,
    root: Path = ROOT,
) -> dict[str, str]:
    """Build an exact route-to-commit mapping or report every unsafe row."""

    rows = _required_route_rows(matrix_path)
    invalid: list[str] = []
    catalog: dict[str, str] = {}
    for row in rows:
        template_path = str(row.get("template_path") or "").strip()
        commit = str(row.get("rollback_commit") or "").strip().lower()
        if not _git_commit_is_usable(commit, root=root):
            invalid.append(f"{template_path}: {commit or '<blank>'}")
            continue
        catalog[template_path] = commit
    if invalid:
        preview = "\n".join(invalid[:20])
        remainder = len(invalid) - min(len(invalid), 20)
        suffix = f"\n... and {remainder} more" if remainder else ""
        raise RollbackCatalogError(
            f"rollback commits are not ready for {len(invalid)}/{len(rows)} routes:\n"
            f"{preview}{suffix}"
        )
    return dict(sorted(catalog.items()))


def _scope_routes(scope: dict[str, Any], required: set[str]) -> set[str]:
    """Resolve one checker-compatible scope entry to its reviewed route set."""

    explicit = {
        str(value).strip() for value in scope.get("route_pages") or [] if str(value).strip()
    }
    if scope.get("all_required") is True and not explicit:
        return set(required)
    return explicit


def synchronize_evidence(
    evidence: dict[str, Any],
    catalog: dict[str, str],
) -> dict[str, Any]:
    """Return evidence with rollback and fully-closed route sets synchronized."""

    cleanup = evidence.get("cleanup")
    if not isinstance(cleanup, dict):
        raise RollbackCatalogError("cutover evidence is missing cleanup")
    scopes = cleanup.get("scope_coverage")
    if not isinstance(scopes, dict):
        raise RollbackCatalogError("cutover evidence is missing cleanup.scope_coverage")
    required = set(catalog)
    rollback_scope = scopes.get("rollback")
    if not isinstance(rollback_scope, dict):
        raise RollbackCatalogError("cutover evidence is missing rollback scope")
    rollback_scope["all_required"] = True
    rollback_scope["route_pages"] = sorted(required)
    cleanup["route_rollback_commits"] = dict(sorted(catalog.items()))

    scope_sets: list[set[str]] = []
    for scope_name in REQUIRED_CLEANUP_SCOPES:
        scope = scopes.get(scope_name)
        if not isinstance(scope, dict):
            raise RollbackCatalogError(f"cutover evidence is missing {scope_name} scope")
        scope_sets.append(_scope_routes(scope, required))
    fully_closed = set.intersection(*scope_sets) if scope_sets else set()
    cleanup["passed_route_pages"] = sorted(fully_closed)
    return evidence


def synchronize_candidate_evidence(
    evidence: dict[str, Any],
    catalog: dict[str, str],
    *,
    candidate_binding: CandidateBinding,
    report_path: str,
    report_sha256: str,
) -> dict[str, Any]:
    """Replace cleanup projection with one recorder-derived candidate snapshot."""

    cleanup = evidence.get("cleanup")
    if not isinstance(cleanup, dict):
        raise RollbackCatalogError("cutover evidence is missing cleanup")
    required_routes = sorted(catalog)
    cleanup.clear()
    cleanup.update(
        {
            "candidate_binding": candidate_binding,
            "evidence": report_path,
            "evidence_sha256": report_sha256,
            "passed_route_pages": required_routes,
            "scope_coverage": {
                scope: {"all_required": True, "route_pages": []}
                for scope in REQUIRED_CLEANUP_SCOPES
            },
            "route_rollback_commits": dict(sorted(catalog.items())),
        }
    )
    return evidence


def verify_evidence(
    evidence: dict[str, Any],
    catalog: dict[str, str],
) -> None:
    """Fail unless checked-in evidence exactly mirrors the validated catalog."""

    cleanup = evidence.get("cleanup")
    if not isinstance(cleanup, dict):
        raise RollbackCatalogError("cutover evidence is missing cleanup")
    actual_mapping = cleanup.get("route_rollback_commits")
    if actual_mapping != catalog:
        raise RollbackCatalogError("route_rollback_commits does not match the matrix catalog")
    scopes = cleanup.get("scope_coverage")
    rollback_scope = scopes.get("rollback") if isinstance(scopes, dict) else None
    if not isinstance(rollback_scope, dict):
        raise RollbackCatalogError("cutover evidence is missing rollback scope")
    required = set(catalog)
    if rollback_scope.get("all_required") is not True:
        raise RollbackCatalogError("rollback scope is not marked all_required")
    if _scope_routes(rollback_scope, required) != required:
        raise RollbackCatalogError("rollback scope does not cover the exact migrated route set")


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RollbackCatalogError(f"JSON root must be an object: {path}")
    return payload


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Build or check exact Web-to-TUI route rollback commit evidence."
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Write rollback scope/mapping only after every matrix commit is valid.",
    )
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    evidence_path = args.evidence.resolve()
    try:
        catalog = build_rollback_catalog(matrix_path)
        evidence = _read_json(evidence_path)
        if args.write_evidence:
            synchronized = synchronize_evidence(evidence, catalog)
            evidence_path.write_text(
                json.dumps(synchronized, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            verify_evidence(evidence, catalog)
    except (OSError, json.JSONDecodeError, RollbackCatalogError) as exc:
        print(f"Web-to-TUI rollback catalog: FAIL - {exc}")
        return 1

    commits = sorted(set(catalog.values()))
    print("Web-to-TUI rollback catalog: PASS - " f"routes={len(catalog)} commits={len(commits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
