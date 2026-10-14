"""Unified Data Center generated-governance projection gate tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import check_data_center_governance_projections as projections

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_projection_gate_runs_every_checker_after_one_failure(monkeypatch) -> None:
    """One stale projection cannot hide the status of later generated artifacts."""

    calls: list[str] = []

    def fake_run(script_path: str) -> int:
        calls.append(script_path)
        return 1 if script_path.endswith("data_center_architecture_inventory.py") else 0

    monkeypatch.setattr(projections, "_run_projection", fake_run)

    failures = projections.check_data_center_governance_projections()

    assert failures == ("architecture inventory",)
    assert calls == [script_path for _name, script_path in projections.PROJECTION_CHECKS]


def test_projection_gate_matches_committed_repository_state() -> None:
    """The same single command used by CI passes against committed projections."""

    completed = subprocess.run(
        [sys.executable, "scripts/check_data_center_governance_projections.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout or completed.stderr
    assert "Data Center governance projections OK" in completed.stdout


def test_local_and_ci_guards_use_the_unified_projection_gate() -> None:
    """Local pre-push and both CI gates cannot drift into partial checklists."""

    guarded_files = (
        REPO_ROOT / ".pre-commit-config.yaml",
        REPO_ROOT / ".github" / "workflows" / "consistency-check.yml",
        REPO_ROOT / ".github" / "workflows" / "ci-fast-feedback.yml",
    )
    unified_command = "python scripts/check_data_center_governance_projections.py"
    direct_commands = (
        "python scripts/check_module_map.py",
        "python scripts/data_center_architecture_inventory.py",
        "python scripts/data_center_entrypoint_inventory.py",
    )

    for path in guarded_files:
        content = path.read_text(encoding="utf-8")
        assert content.count(unified_command) == 1, path
        assert all(command not in content for command in direct_commands), path
