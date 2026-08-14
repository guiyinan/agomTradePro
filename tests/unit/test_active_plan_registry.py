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
    assert report.workstream_count == 7
    assert report.primary_plan_count == 16
    assert report.supporting_document_count == 21
    assert report.review_queue_count == 9
    assert report.registered_path_count == report.active_path_count == 46


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
