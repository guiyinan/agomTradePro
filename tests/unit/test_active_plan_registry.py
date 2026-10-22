from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

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


def test_repository_active_plan_registry_is_closed_world() -> None:
    """Verify registry coverage without copying changing inventory counts."""
    module = _load_module()
    registry_path = REPO_ROOT / "governance" / "active_plan_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    report = module.evaluate_registry(
        REPO_ROOT,
        registry_path,
        REPO_ROOT / "docs" / "plans" / "README.md",
    )

    assert report.violation_count == 0, report.violations
    documents = [
        document for workstream in registry["workstreams"] for document in workstream["documents"]
    ]
    registered_paths = [document["path"] for document in documents] + [
        review["path"] for review in registry["review_queue"]
    ]
    plan_root = REPO_ROOT / "docs" / "plans"
    actual_paths = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in plan_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".md", ".csv"}
        and path != plan_root / "README.md"
    }
    assert len(registered_paths) == len(set(registered_paths))
    assert set(registered_paths) == actual_paths
    assert report.workstream_count == len(registry["workstreams"])
    assert report.primary_plan_count == sum(document["role"] == "primary" for document in documents)
    assert report.supporting_document_count == sum(
        document["role"] != "primary" for document in documents
    )
    assert report.review_queue_count == len(registry["review_queue"])
    assert report.closure_unit_count == len(registry["closure_backlog"]["units"])
    assert report.registered_path_count == report.active_path_count == len(actual_paths)


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


def test_registry_accepts_owner_dispositions_without_scheduling_work(tmp_path: Path) -> None:
    """Deferred and archived units may remain recorded without becoming executable."""
    module = _load_module()
    for status in ("deferred", "archived"):
        fixture_root = tmp_path / status
        registry_path, index_path = _write_fixture_repository(fixture_root)
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        payload["execution_focus"]["unit_id"] = None
        payload["closure_backlog"]["units"][1]["status"] = status
        registry_path.write_text(json.dumps(payload), encoding="utf-8")
        report = module.evaluate_registry(fixture_root, registry_path, index_path)
        assert report.violation_count == 0, report.violations


def test_registry_rejects_owner_disposition_as_execution_focus(tmp_path: Path) -> None:
    """An owner disposition cannot silently keep a unit selected for execution."""
    module = _load_module()
    for status in ("deferred", "archived"):
        fixture_root = tmp_path / status
        registry_path, index_path = _write_fixture_repository(fixture_root)
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        payload["closure_backlog"]["units"][1]["status"] = status
        registry_path.write_text(json.dumps(payload), encoding="utf-8")
        report = module.evaluate_registry(fixture_root, registry_path, index_path)
        codes = {violation.code for violation in report.violations}
        assert "closure_unit_status" not in codes
        assert "execution_focus_not_active" in codes


def test_registry_owner_dispositions_do_not_satisfy_dependencies(tmp_path: Path) -> None:
    """Retained dispositions do not count as completed prerequisites."""
    module = _load_module()
    for status in ("deferred", "archived"):
        fixture_root = tmp_path / status
        registry_path, index_path = _write_fixture_repository(fixture_root)
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        payload["execution_focus"]["unit_id"] = None
        payload["closure_backlog"]["units"][1]["status"] = status
        dependent = dict(payload["closure_backlog"]["units"][1])
        dependent.update(id="EXAMPLE-02", status="planned", depends_on=["EXAMPLE-01"])
        payload["closure_backlog"]["units"].append(dependent)
        registry_path.write_text(json.dumps(payload), encoding="utf-8")
        report = module.evaluate_registry(fixture_root, registry_path, index_path)
        assert report.violation_count == 0, report.violations


def test_registry_rejects_unknown_unit_disposition(tmp_path: Path) -> None:
    """The two owner states do not turn the status contract into a wildcard."""
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"][1]["status"] = "obsolete"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert any(violation.code == "closure_unit_status" for violation in report.violations)


def _add_preparation_fixture(registry_path: Path) -> None:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    unit = dict(payload["closure_backlog"]["units"][1])
    unit.update(id="EXAMPLE-02", status="planned", depends_on=["EXAMPLE-01"])
    payload["closure_backlog"]["units"].append(unit)
    payload["execution_focus"]["parallel_preparation"] = [
        {
            "unit_id": "EXAMPLE-02",
            "scope": "Prepare caller adaptation while the shared contract is unfinished.",
            "owner": "isolated-worker",
            "isolated_workspace": True,
            "shared_git_serialized": True,
            "isolated_test_resources": True,
        }
    ]
    registry_path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_allows_bounded_preparation_with_unfinished_dependencies(tmp_path: Path) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_preparation_fixture(registry_path)
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert report.violation_count == 0, report.violations


@pytest.mark.parametrize(
    "failure",
    [
        "second_active",
        "unknown",
        "deferred",
        "archived",
        "completed",
        "duplicate",
        "workspace",
        "git",
        "resources",
        "numeric_true",
        "missing_scope",
        "extra_field",
    ],
)
def test_registry_rejects_unbounded_preparation(tmp_path: Path, failure: str) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_preparation_fixture(registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = payload["execution_focus"]["parallel_preparation"][0]
    expected = "parallel_preparation_unit"
    if failure == "second_active":
        payload["closure_backlog"]["units"][-1]["status"] = "active"
        expected = "execution_focus_repository_lock"
    elif failure == "unknown":
        entry["unit_id"] = "MISSING-99"
    elif failure in {"deferred", "archived", "completed"}:
        payload["closure_backlog"]["units"][-1]["status"] = failure
    elif failure == "duplicate":
        payload["execution_focus"]["parallel_preparation"].append(dict(entry))
        expected = "parallel_preparation_duplicate"
    elif failure in {"workspace", "git", "resources", "numeric_true"}:
        field = {
            "workspace": "isolated_workspace",
            "git": "shared_git_serialized",
            "resources": "isolated_test_resources",
            "numeric_true": "isolated_workspace",
        }[failure]
        entry[field] = 1 if failure == "numeric_true" else False
        expected = "parallel_preparation_isolation"
    elif failure == "missing_scope":
        entry["scope"] = " "
        expected = "parallel_preparation_scope"
    else:
        entry["bypass_dependencies"] = True
        expected = "parallel_preparation_keys"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert expected in {violation.code for violation in report.violations}


def _add_m1_fixture(registry_path: Path) -> None:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    template = payload["closure_backlog"]["units"][1]
    for unit_id, status, dependencies in [
        ("ASH-02", "completed", []),
        ("ASH-03", "planned", ["ASH-02"]),
        ("ASH-04", "planned", []),
        ("ASH-07", "planned", ["ASH-03", "ASH-04"]),
        ("ASH-08", "planned", ["ASH-03", "ASH-04", "ASH-07"]),
    ]:
        unit = dict(template, id=unit_id, status=status, depends_on=dependencies)
        payload["closure_backlog"]["units"].append(unit)
    payload["closure_backlog"]["units"][-1]["early_delivery"] = {
        "milestone": "M1",
        "status": "active",
        "depends_on": ["ASH-02"],
        "scope_ref": "docs/plans/a-share-usability-implementation-plan-2026-10-16.md#1996-m1-first-delivery",
        "required_checks": [
            "account_authorization",
            "qualified_current_source",
            "correct_quantities_costs_cash",
            "risk_and_sell_buy_dependencies",
            "ordinary_user_real_entry",
            "nonempty_positive_plan",
            "unknown_and_cross_account_denials",
            "no_execution_or_ledger_mutation",
            "same_candidate_evidence",
        ],
        "acceptance_evidence": None,
    }
    registry_path.write_text(json.dumps(payload), encoding="utf-8")


def _write_m1_acceptance(root: Path, registry_path: Path) -> Path:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    delivery = payload["closure_backlog"]["units"][-1]["early_delivery"]
    report_path = root / "artifacts" / "m1" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "schema": "m1.acceptance.v1",
                "candidate_sha": "a" * 40,
                "checks": dict.fromkeys(delivery["required_checks"], True),
                "positive_plan_count": 1,
                "execution_count": 0,
                "ledger_mutation_count": 0,
            }
        ),
        encoding="utf-8",
    )
    delivery["status"] = "passed"
    delivery["acceptance_evidence"] = {
        "candidate_sha": "a" * 40,
        "report_path": "artifacts/m1/report.json",
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return report_path


def test_registry_accepts_m1_preparation_before_whole_unit_dependencies(tmp_path: Path) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert report.violation_count == 0, report.violations


@pytest.mark.parametrize(
    "failure",
    [
        "missing_dependency",
        "deferred_dependency",
        "remove_full_dependency",
        "missing_check",
        "duplicate_check",
        "unknown_check",
        "wrong_scope",
        "wrong_milestone",
        "wrong_unit",
        "unapproved_status",
        "early_evidence",
        "extra_key",
    ],
)
def test_registry_rejects_m1_scope_or_correctness_waivers(tmp_path: Path, failure: str) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    unit = payload["closure_backlog"]["units"][-1]
    delivery = unit["early_delivery"]
    if failure == "missing_dependency":
        delivery["depends_on"] = []
    elif failure == "deferred_dependency":
        payload["closure_backlog"]["units"][2]["status"] = "deferred"
    elif failure == "remove_full_dependency":
        unit["depends_on"].remove("ASH-03")
    elif failure == "missing_check":
        delivery["required_checks"].remove("qualified_current_source")
    elif failure == "duplicate_check":
        delivery["required_checks"].append("qualified_current_source")
    elif failure == "unknown_check":
        delivery["required_checks"][0] = "accept_any_account"
    elif failure == "wrong_scope":
        delivery["scope_ref"] = "docs/plans/primary.md"
    elif failure == "wrong_milestone":
        delivery["milestone"] = "M2"
    elif failure == "wrong_unit":
        unit["id"] = "ASH-09"
    elif failure == "unapproved_status":
        delivery["status"] = "approved"
    elif failure == "early_evidence":
        delivery["acceptance_evidence"] = {"passed": True}
    else:
        delivery["bypass"] = True
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert any(violation.code.startswith("early_delivery_") for violation in report.violations)


def test_registry_accepts_retained_candidate_bound_m1_report(tmp_path: Path) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    _write_m1_acceptance(tmp_path, registry_path)
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert report.violation_count == 0, report.violations


@pytest.mark.parametrize("parent_status", ["deferred", "archived"])
@pytest.mark.parametrize("delivery_status", ["active", "passed"])
def test_registry_rejects_m1_reactivating_inactive_parent(
    tmp_path: Path, parent_status: str, delivery_status: str
) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    if delivery_status == "passed":
        _write_m1_acceptance(tmp_path, registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"][-1]["status"] = parent_status
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert "early_delivery_parent_status" in {violation.code for violation in report.violations}


@pytest.mark.parametrize(
    "failure",
    [
        "absent",
        "hash",
        "candidate",
        "short_candidate",
        "empty_plan",
        "bool_plan",
        "float_plan",
        "unknown_denial",
        "missing_check",
        "numeric_check",
        "execution",
        "ledger_mutation",
        "bool_execution",
        "float_mutation",
        "escape",
        "absolute",
        "backslash",
        "schema",
    ],
)
def test_registry_rejects_unproven_or_mutating_m1_pass(tmp_path: Path, failure: str) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    report_path = _write_m1_acceptance(tmp_path, registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    evidence = payload["closure_backlog"]["units"][-1]["early_delivery"]["acceptance_evidence"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if failure == "absent":
        evidence["report_path"] = "artifacts/m1/absent.json"
    elif failure == "hash":
        evidence["report_sha256"] = "0" * 64
    elif failure == "short_candidate":
        evidence["candidate_sha"] = "a" * 8
    elif failure in {"escape", "absolute", "backslash"}:
        evidence["report_path"] = {
            "escape": "artifacts/../../outside.json",
            "absolute": str(report_path.resolve()),
            "backslash": "artifacts\\m1\\report.json",
        }[failure]
    else:
        if failure == "candidate":
            report["candidate_sha"] = "b" * 40
        elif failure in {"empty_plan", "bool_plan", "float_plan"}:
            report["positive_plan_count"] = {"empty_plan": 0, "bool_plan": True, "float_plan": 1.0}[
                failure
            ]
        elif failure == "unknown_denial":
            report["checks"]["unknown_and_cross_account_denials"] = False
        elif failure == "missing_check":
            del report["checks"]["qualified_current_source"]
        elif failure == "numeric_check":
            report["checks"]["correct_quantities_costs_cash"] = 1
        elif failure == "execution":
            report["execution_count"] = 1
        elif failure == "ledger_mutation":
            report["ledger_mutation_count"] = 1
        elif failure == "bool_execution":
            report["execution_count"] = False
        elif failure == "float_mutation":
            report["ledger_mutation_count"] = 0.0
        else:
            report["schema"] = "release.acceptance.v1"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        evidence["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    result = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert any(violation.code.startswith("m1_evidence") for violation in result.violations)


def test_registry_m1_pass_cannot_close_ash08_with_unfinished_prerequisites(tmp_path: Path) -> None:
    module = _load_module()
    registry_path, index_path = _write_fixture_repository(tmp_path)
    _add_m1_fixture(registry_path)
    _write_m1_acceptance(tmp_path, registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["closure_backlog"]["units"][-1]["status"] = "completed"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    report = module.evaluate_registry(tmp_path, registry_path, index_path)
    assert "early_delivery_whole_unit" in {violation.code for violation in report.violations}
