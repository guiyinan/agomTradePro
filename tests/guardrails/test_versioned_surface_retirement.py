"""Regression tests for the repository-wide version retirement inventory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_versioned_surface_retirement import validate

ROOT = Path(__file__).resolve().parents[2]
SCOPE = (
    "apps/**/*.py and core/**/*.py excluding migrations; _vN module groups plus "
    "explicit no-suffix, runtime-schema and composition-route legacy surfaces"
)


def _pending_retirement_evidence() -> dict[str, dict[str, str | None]]:
    return {
        key: {"status": "pending", "artifact": None}
        for key in (
            "zero_runtime_callers",
            "production_row_inventory",
            "backup_restore",
            "historical_hash_replay",
        )
    }


def _sample_legacy_surface() -> dict[str, object]:
    return {
        "id": "sample-runtime-route",
        "owner": "sample",
        "state": "blocked_retirement",
        "versions": [1, 2],
        "preferred_current_version": 2,
        "active_default_version": 2,
        "write_surface_versions": [1, 2],
        "retained_read_versions": [1, 2],
        "blocked_by": ["SAMPLE-01"],
        "retirement_gate": ["Remove V1 after production acceptance."],
        "tracked_paths": [
            {
                "path": "apps/sample/application/legacy_policy.py",
                "versions": [1],
                "role": "compatibility_entrypoint",
                "markers": ["LEGACY_POLICY = 1"],
            },
            {
                "path": "apps/sample/application/legacy_policy_v2.py",
                "versions": [2],
                "role": "preferred_entrypoint",
                "markers": ["CURRENT_POLICY = 2"],
            },
        ],
        "retirement_evidence": _pending_retirement_evidence(),
    }


def _write_sample_legacy_paths(application: Path) -> None:
    (application / "legacy_policy.py").write_text("LEGACY_POLICY = 1\n", encoding="utf-8")
    (application / "legacy_policy_v2.py").write_text("CURRENT_POLICY = 2\n", encoding="utf-8")


def _sample_no_suffix_groups() -> dict[str, dict[str, object]]:
    return {
        "apps/sample/application/legacy_policy{_v#}.py": {
            "versions": [1, 2],
            "legacy_surface_id": "sample-runtime-route",
        }
    }


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
    assert (
        "5 families, 3 multi-writer, 24 module groups, 23 no-suffix groups, "
        "6 explicit legacy surfaces, 24 pending retirement proofs" in result.stdout
    )


def test_new_parallel_version_requires_manifest_update(tmp_path: Path) -> None:
    """Adding V3 beside governed V1/V2 must fail until lifecycle data changes."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2, 3):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_sample_legacy_paths(application)
    (application / "extra_policy.py").write_text("VALUE = 1\n", encoding="utf-8")
    (application / "extra_policy_v2.py").write_text("VALUE = 2\n", encoding="utf-8")

    manifest = {
        "schema_version": "2026-09-22.v2",
        "owner": "architecture-governance",
        "scope": SCOPE,
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
        "legacy_surfaces": [_sample_legacy_surface()],
        "no_suffix_module_groups": _sample_no_suffix_groups(),
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
    assert (
        "unregistered_no_suffix_version_group:"
        "apps/sample/application/extra_policy{_v#}.py" in violations
    )


def test_completed_blocker_forces_retirement_review(tmp_path: Path) -> None:
    """A closed production dependency must not leave old versions indefinitely blocked."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_sample_legacy_paths(application)
    (repository / "evidence.json").write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema_version": "2026-09-22.v2",
        "owner": "architecture-governance",
        "scope": SCOPE,
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
        "legacy_surfaces": [_sample_legacy_surface()],
        "no_suffix_module_groups": _sample_no_suffix_groups(),
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
    assert "sample-runtime-route.retirement_review_due" in violations
    assert "sample-linked.retirement_review_due" in violations


def test_tracked_no_suffix_legacy_path_must_still_exist(tmp_path: Path) -> None:
    """A removed no-suffix V1 surface must fail even without an _v1 filename."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_sample_legacy_paths(application)
    (application / "legacy_policy.py").unlink()
    (repository / "evidence.json").write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema_version": "2026-09-22.v2",
        "owner": "architecture-governance",
        "scope": SCOPE,
        "families": [
            {
                "id": "sample-policy",
                "owner": "sample",
                "state": "blocked_retirement",
                "preferred_current_version": 2,
                "write_surface_versions": [1, 2],
                "retained_read_versions": [1, 2],
                "blocked_by": ["SAMPLE-01"],
                "retirement_gate": ["Wait for production acceptance."],
                "evidence": ["evidence.json"],
                "module_groups": {"apps/sample/application/policy_v#.py": [1, 2]},
            }
        ],
        "legacy_surfaces": [_sample_legacy_surface()],
        "no_suffix_module_groups": _sample_no_suffix_groups(),
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
    manifest_path = repository / "manifest.json"
    active_plan_path = repository / "active.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    active_plan_path.write_text(json.dumps(active_plan), encoding="utf-8")

    violations, _summary = validate(
        manifest_path=manifest_path,
        active_plan_path=active_plan_path,
        repository_root=repository,
    )

    assert (
        "sample-runtime-route.tracked_path_missing:apps/sample/application/legacy_policy.py"
        in violations
    )


def test_verified_retirement_proof_must_resolve_to_an_artifact(tmp_path: Path) -> None:
    """A verified proof slot cannot point at a missing receipt."""

    repository = tmp_path / "repository"
    application = repository / "apps" / "sample" / "application"
    application.mkdir(parents=True)
    for version in (1, 2):
        (application / f"policy_v{version}.py").write_text("VALUE = 1\n", encoding="utf-8")
    _write_sample_legacy_paths(application)
    (repository / "evidence.json").write_text("{}\n", encoding="utf-8")
    surface = _sample_legacy_surface()
    evidence = surface["retirement_evidence"]
    assert isinstance(evidence, dict)
    evidence["zero_runtime_callers"] = {
        "status": "verified",
        "artifact": "missing-proof.json",
    }
    manifest = {
        "schema_version": "2026-09-22.v2",
        "owner": "architecture-governance",
        "scope": SCOPE,
        "families": [
            {
                "id": "sample-policy",
                "owner": "sample",
                "state": "blocked_retirement",
                "preferred_current_version": 2,
                "write_surface_versions": [1, 2],
                "retained_read_versions": [1, 2],
                "blocked_by": ["SAMPLE-01"],
                "retirement_gate": ["Wait for production acceptance."],
                "evidence": ["evidence.json"],
                "module_groups": {"apps/sample/application/policy_v#.py": [1, 2]},
            }
        ],
        "legacy_surfaces": [surface],
        "no_suffix_module_groups": _sample_no_suffix_groups(),
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
    manifest_path = repository / "manifest.json"
    active_plan_path = repository / "active.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    active_plan_path.write_text(json.dumps(active_plan), encoding="utf-8")

    violations, _summary = validate(
        manifest_path=manifest_path,
        active_plan_path=active_plan_path,
        repository_root=repository,
    )

    assert (
        "sample-runtime-route.zero_runtime_callers_artifact_missing:missing-proof.json"
        in violations
    )
