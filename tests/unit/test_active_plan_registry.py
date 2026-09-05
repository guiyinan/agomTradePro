from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    script_path = REPO_ROOT / "scripts" / "check_active_plan_registry.py"
    module_name = "test_check_active_plan_registry_script"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)


def _write_fixture_repository(root: Path) -> tuple[Path, Path]:
    plan_root = root / "docs" / "plans"
    plan_root.mkdir(parents=True)
    (plan_root / "primary.md").write_text("# Primary\n", encoding="utf-8")
    (plan_root / "matrix.csv").write_text("key,value\n", encoding="utf-8")
    index_path = plan_root / "README.md"
    index_path.write_text(
        "# Plans\n\n"
        "Registry: governance/active_plan_registry.json\n\n"
        "Canonical backlog: closure_backlog\n\n"
        "Workstream: `example`\n",
        encoding="utf-8",
    )
    registry_path = root / "governance" / "active_plan_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": "test.v1",
                "updated_at": "2026-08-14",
                "execution_focus": {
                    "unit_id": "EXAMPLE-01",
                    "allowed_parallel_execution_modes": [
                        "production",
                        "external",
                        "governance",
                    ],
                    "policy": "Only the focused repository unit may be active.",
                },
                "workstreams": [
                    {
                        "id": "example",
                        "title": "Example",
                        "category": "test",
                        "priority": "P0",
                        "owner": "test_owner",
                        "status": "active",
                        "next_gate": "Pass the example gate.",
                        "documents": [
                            {"path": "docs/plans/primary.md", "role": "primary"},
                            {"path": "docs/plans/matrix.csv", "role": "matrix"},
                        ],
                    }
                ],
                "review_queue": [],
                "closure_backlog": {
                    "version": "test.v1",
                    "legacy_unchecked_count": 0,
                    "legacy_unchecked_by_workstream": {"example": 0},
                    "legacy_sources": [],
                    "waves": [
                        {"id": 0, "title": "Governance", "rule": "Review stale plans."},
                        {"id": 1, "title": "Delivery", "rule": "Deliver the example."},
                    ],
                    "units": [
                        {
                            "id": "GOV-01",
                            "workstream_id": "review-queue",
                            "wave": 0,
                            "priority": "P1",
                            "execution_mode": "governance",
                            "status": "planned",
                            "title": "Review stale plans",
                            "depends_on": [],
                            "exit_gate": "Review is complete.",
                        },
                        {
                            "id": "EXAMPLE-01",
                            "workstream_id": "example",
                            "wave": 1,
                            "priority": "P0",
                            "execution_mode": "repository",
                            "status": "active",
                            "title": "Deliver example",
                            "depends_on": [],
                            "exit_gate": "Example is complete.",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return registry_path, index_path


def test_repository_active_plan_registry_is_closed_world():
    module = _load_module()
    report = module.evaluate_registry(
        REPO_ROOT,
        REPO_ROOT / "governance" / "active_plan_registry.json",
        REPO_ROOT / "docs" / "plans" / "README.md",
    )

    assert report.violation_count == 0, report.violations
    assert report.workstream_count == 9
    assert report.primary_plan_count == 18
    assert report.supporting_document_count == 23
    assert report.review_queue_count == 0
    assert report.closure_unit_count == 42
    assert report.registered_path_count == report.active_path_count == 41


def test_registry_rejects_unregistered_active_plan(tmp_path: Path):
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    (tmp_path / "docs" / "plans" / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    assert any(
        violation.code == "unregistered_active_path" and violation.path == "docs/plans/orphan.md"
        for violation in report.violations
    )


def test_registry_rejects_duplicate_and_stale_paths(tmp_path: Path):
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["workstreams"][0]["documents"].append(
        {"path": "docs/plans/primary.md", "role": "supporting"}
    )
    payload["review_queue"].append(
        {
            "path": "docs/plans/missing.md",
            "owner": "docs",
            "status": "review_required",
            "review_by": "2026-08-21",
            "disposition": "Archive it.",
        }
    )
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    codes = {violation.code for violation in report.violations}
    assert "duplicate_path" in codes
    assert "stale_registered_path" in codes


def test_registry_rejects_legacy_checkbox_and_dependency_drift(tmp_path: Path):
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    (tmp_path / "docs" / "plans" / "primary.md").write_text(
        "# Primary\n\n- [ ] Newly added legacy item\n",
        encoding="utf-8",
    )
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"][1]["depends_on"] = ["MISSING-99"]
    payload["closure_backlog"]["units"][1]["status"] = "waiting_dependency"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    codes = {violation.code for violation in report.violations}
    assert "legacy_count_drift" in codes
    assert "legacy_total_drift" in codes
    assert "legacy_source_coverage" in codes
    assert "unknown_closure_dependency" in codes


def test_registry_requires_automatic_evidence_plan_for_production_unit(tmp_path: Path):
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"][1]["execution_mode"] = "production"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    codes = {violation.code for violation in report.violations}
    assert "closure_unit_keys" in codes
    assert "closure_unit_evidence_collection" in codes


def test_registry_rejects_multiple_active_repository_units(tmp_path: Path):
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"].append(
        {
            "id": "EXAMPLE-02",
            "workstream_id": "example",
            "wave": 1,
            "priority": "P1",
            "execution_mode": "repository",
            "status": "active",
            "title": "Expand another repository boundary",
            "depends_on": [],
            "exit_gate": "The second boundary is complete.",
        }
    )
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    assert any(
        violation.code == "execution_focus_repository_lock" for violation in report.violations
    )


def test_registry_accepts_no_focus_when_no_repository_unit_is_eligible(
    tmp_path: Path,
) -> None:
    """A completed repository backlog may publish an explicit null focus."""

    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["execution_focus"]["unit_id"] = None
    payload["closure_backlog"]["units"][1]["status"] = "completed"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    assert report.violation_count == 0, report.violations


def test_registry_rejects_no_focus_when_repository_work_is_eligible(
    tmp_path: Path,
) -> None:
    """Null focus must not hide an active or dependency-ready repository unit."""

    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["execution_focus"]["unit_id"] = None
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    report = module.evaluate_registry(tmp_path, registry_path, index_path)

    codes = {violation.code for violation in report.violations}
    assert "execution_focus_repository_lock" in codes
    assert "execution_focus_missing_eligible_unit" in codes
