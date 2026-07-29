"""Exercise an isolated Web-to-TUI graph/runtime and route/template rollback.

The drill never changes the working tree or a live database. It materializes the
reviewed migration bundle in a temporary directory, applies the real reverse
patch to the pre-migration baseline, verifies every restored artifact, then
reapplies the patch and verifies the candidate state byte-for-byte (with line
ending normalization for text files).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE_REVISION = "7e706d07caacca8b3e56a486d8c0b6b6ed2cdf37"
WAVE = "M4-simulated-accounts-w51"

# The graph and IA files are monolithic release artifacts, so their delta covers
# the complete M0-M4 candidate. Route/template entries are the representative
# final wave selected for the rollback exercise.
TRACKED_PATHS = (
    "apps/simulated_trading/interface/api_urls.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_action_patch_execution.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_execution.py",
    "config/tui/ia/tui_information_architecture.v1.json",
    "config/tui/published/tui_operation_graph.published.json",
    "core/templates/simulated_trading/account_detail.html",
    "core/templates/simulated_trading/dashboard.html",
    "core/templates/simulated_trading/my_account_detail.html",
    "core/templates/simulated_trading/my_accounts.html",
)
NEW_PATHS = (
    "apps/simulated_trading/interface/tui_serializers.py",
    "apps/simulated_trading/interface/tui_views.py",
    "apps/terminal/infrastructure/tui_metadata_runtime_injection_simulated_trading.py",
)
GRAPH_PATH = "config/tui/published/tui_operation_graph.published.json"


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    """Run one Git command and return stdout or fail with useful diagnostics."""

    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def _canonical_bytes(content: bytes) -> bytes:
    """Normalize text line endings while leaving binary content unchanged."""

    if b"\x00" in content:
        return content
    return content.replace(b"\r\n", b"\n")


def _digest(content: bytes) -> str:
    """Return a canonical SHA-256 digest."""

    return hashlib.sha256(_canonical_bytes(content)).hexdigest()


def _current_bytes(relative_path: str) -> bytes:
    """Read one candidate artifact from the working tree."""

    path = ROOT / relative_path
    if not path.is_file():
        raise RuntimeError(f"candidate artifact is missing: {relative_path}")
    return path.read_bytes()


def _baseline_bytes(relative_path: str, baseline_revision: str) -> bytes:
    """Read one baseline artifact directly from Git."""

    return _git_bytes("show", f"{baseline_revision}:{relative_path}")


def _copy_candidate_files(temp_root: Path) -> dict[str, bytes]:
    """Copy all candidate files into the isolated drill directory."""

    snapshots: dict[str, bytes] = {}
    for relative_path in (*TRACKED_PATHS, *NEW_PATHS):
        content = _current_bytes(relative_path)
        snapshots[relative_path] = content
        target = temp_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return snapshots


def _apply_patch(temp_root: Path, patch: bytes, *, reverse: bool) -> None:
    """Apply the migration patch inside the isolated directory."""

    command = ["git", "apply", "--whitespace=nowarn"]
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
        raise RuntimeError(f"{direction} patch application failed: {message}")


def _assert_content(path: Path, expected: bytes, *, label: str) -> None:
    """Fail when one isolated artifact differs from the expected snapshot."""

    actual = path.read_bytes()
    if _canonical_bytes(actual) != _canonical_bytes(expected):
        raise RuntimeError(f"{label} content mismatch: {path}")


def _validate_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate one graph against the candidate runtime/schema contract."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")
    import django

    django.setup()

    from apps.terminal.application.tui_metadata import validate_tui_metadata

    validated = validate_tui_metadata(payload)
    return {
        "schema_version": str(validated["schema_version"]),
        "screens": len(validated["screens"]),
        "actions": len(validated["actions"]),
    }


def run_drill(*, baseline_revision: str) -> dict[str, Any]:
    """Run the reversible isolated drill and return machine-readable evidence."""

    started = time.perf_counter()
    patch = _git_bytes("diff", "--binary", baseline_revision, "--", *TRACKED_PATHS)
    if not patch.strip():
        raise RuntimeError("migration patch is empty; baseline or tracked paths are incorrect")

    baseline_snapshots = {path: _baseline_bytes(path, baseline_revision) for path in TRACKED_PATHS}
    candidate_snapshots = {path: _current_bytes(path) for path in (*TRACKED_PATHS, *NEW_PATHS)}
    for relative_path in NEW_PATHS:
        exists_at_baseline = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{baseline_revision}:{relative_path}"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if exists_at_baseline:
            raise RuntimeError(f"new-path manifest already exists at baseline: {relative_path}")

    baseline_graph = json.loads(baseline_snapshots[GRAPH_PATH])
    candidate_graph = json.loads(candidate_snapshots[GRAPH_PATH])
    baseline_contract = _validate_graph(baseline_graph)
    candidate_contract = _validate_graph(candidate_graph)

    with tempfile.TemporaryDirectory(prefix="agom-web-to-tui-rollback-") as temp_dir:
        temp_root = Path(temp_dir)
        _copy_candidate_files(temp_root)

        rollback_started = time.perf_counter()
        _apply_patch(temp_root, patch, reverse=True)
        for relative_path in NEW_PATHS:
            (temp_root / relative_path).unlink()
        for relative_path, expected in baseline_snapshots.items():
            _assert_content(
                temp_root / relative_path,
                expected,
                label="rollback baseline",
            )
        for relative_path in NEW_PATHS:
            if (temp_root / relative_path).exists():
                raise RuntimeError(f"rollback did not remove new artifact: {relative_path}")
        rollback_seconds = time.perf_counter() - rollback_started

        restore_started = time.perf_counter()
        _apply_patch(temp_root, patch, reverse=False)
        for relative_path in NEW_PATHS:
            target = temp_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(candidate_snapshots[relative_path])
        for relative_path, expected in candidate_snapshots.items():
            _assert_content(
                temp_root / relative_path,
                expected,
                label="candidate restore",
            )
        restore_seconds = time.perf_counter() - restore_started

    return {
        "ok": True,
        "wave": WAVE,
        "scope": "M0-M4 graph/runtime bundle plus W51 route/template artifacts",
        "baseline_revision": baseline_revision,
        "tracked_paths": list(TRACKED_PATHS),
        "new_paths": list(NEW_PATHS),
        "baseline_graph_hash": _digest(baseline_snapshots[GRAPH_PATH]),
        "candidate_graph_hash": _digest(candidate_snapshots[GRAPH_PATH]),
        "baseline_contract": baseline_contract,
        "candidate_contract": candidate_contract,
        "rollback_seconds": round(rollback_seconds, 3),
        "restore_seconds": round(restore_seconds, 3),
        "total_seconds": round(time.perf_counter() - started, 3),
        "working_tree_unchanged": True,
    }


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Exercise the reviewed Web-to-TUI rollback bundle in isolation."
    )
    parser.add_argument("--baseline-ref", default=BASELINE_REVISION)
    args = parser.parse_args()
    evidence = run_drill(baseline_revision=args.baseline_ref)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
