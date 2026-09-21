"""Regression tests for the repository-wide version retirement inventory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_versioned_surface_retirement import validate

ROOT = Path(__file__).resolve().parents[2]


def test_repository_versioned_surface_retirement_guard_passes() -> None:
    """The checked-in inventory must match every parallel source family."""

    result = subprocess.run(
        [sys.executable, "scripts/check_versioned_surface_retirement.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 families, 3 multi-writer, 24 module groups" in result.stdout


def test_new_parallel_version_requires_manifest_update(tmp_path: Path) -> None:
    """Adding V3 beside governed V1/V2 must fail until lifecycle data changes."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2, 3):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")

    manifest = {
        "schema_version": "2026-09-22.v1",
        "owner": "architecture-governance",
        "scope": "apps/**/*.py and core/**/*.py excluding migrations; _vN module tokens",
        "families": [
            {
                "id": "sample-policy",
                "owner": "sample",
                "state": "blocked_retirement",
                "preferred_current_version": 2,
                "write_surface_versions": [1, 2],
                "retained_read_versions": [1, 2],
                "blocked_by": ["SAMPLE-01"],
                "retirement_gate": ["Remove the old writer after production acceptance."],
                "evidence": ["evidence.json"],
                "module_groups": {"apps/sample/application/policy_v#.py": [1, 2]},
            }
        ],
        "linked_retirement_gates": [
            {
                "id": "sample-linked",
                "owner": "sample",
                "blocked_by": ["SAMPLE-01"],
                "deletion_allowed": False,
                "guard_command": "python guard.py",
                "retirement_gate": ["Wait for production acceptance."],
            }
        ],
    }
    active_plan = {
        "closure_backlog": {"units": [{"id": "SAMPLE-01", "status": "awaiting_production"}]}
    }
    (repository / "evidence.json").write_text("{}\n", encoding="utf-8")
    manifest_path = repository / "manifest.json"
    active_plan_path = repository / "active.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    active_plan_path.write_text(json.dumps(active_plan), encoding="utf-8")

    violations, _summary = validate(
        manifest_path=manifest_path,
        active_plan_path=active_plan_path,
        repository_root=repository,
    )

    assert any(item.startswith("module_group_versions_changed:") for item in violations)


def test_completed_blocker_forces_retirement_review(tmp_path: Path) -> None:
    """A closed production dependency must not leave old versions indefinitely blocked."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "evidence.json").write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema_version": "2026-09-22.v1",
        "owner": "architecture-governance",
        "scope": "apps/**/*.py and core/**/*.py excluding migrations; _vN module tokens",
        "families": [
            {
                "id": "sample-policy",
                "owner": "sample",
                "state": "blocked_retirement",
                "preferred_current_version": 2,
                "write_surface_versions": [1, 2],
                "retained_read_versions": [1, 2],
                "blocked_by": ["SAMPLE-01"],
                "retirement_gate": ["Remove V1 after the gate."],
                "evidence": ["evidence.json"],
                "module_groups": {"apps/sample/application/policy_v#.py": [1, 2]},
            }
        ],
        "linked_retirement_gates": [
            {
                "id": "sample-linked",
                "owner": "sample",
                "blocked_by": ["SAMPLE-01"],
                "deletion_allowed": False,
                "guard_command": "python guard.py",
                "retirement_gate": ["Wait for production acceptance."],
            }
        ],
    }
    active_plan = {"closure_backlog": {"units": [{"id": "SAMPLE-01", "status": "completed"}]}}
    manifest_path = repository / "manifest.json"
    active_plan_path = repository / "active.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    active_plan_path.write_text(json.dumps(active_plan), encoding="utf-8")

    violations, _summary = validate(
        manifest_path=manifest_path,
        active_plan_path=active_plan_path,
        repository_root=repository,
    )

    assert "sample-policy.retirement_review_due" in violations
    assert "sample-linked.retirement_review_due" in violations
