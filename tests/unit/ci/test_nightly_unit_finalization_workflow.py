"""Manual Nightly scopes preserve the full-run contract and isolate unit reporting."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/nightly-tests.yml"
FULL_ONLY_IF = "${{ github.event_name != 'workflow_dispatch' || github.workflow != 'Nightly Tests' || inputs.suite != 'unit-only' }}"
FULL_ONLY_STEPS = {
    "Run registered current-data contract nodeids",
    "Run registered Celery task contract nodeids",
    "Enforce full-production mypy debt ceiling",
    "Run frontend Node contract tests",
    "Verify test-tier inventory",
    "Run Component Tests",
    "Run API And Migration Tests",
    "Run Critical Reliability (SQLite + Fake Agent)",
    "Run Integration Tests (core)",
    "Run App-Local Module Tests",
    "Run SDK client tests",
    "Run MCP contract tests",
    "Run Django E2E tests",
    "Run Guardrail Tests",
    "Build final coverage report and enforce ratchet",
    "Generate Architecture Audit Report",
    "Run Playwright Smoke Tests",
    "Full lint fallback (non-blocking)",
}
UNIT_DIAGNOSTIC_ALLOWED_STEPS = {
    "Checkout",
    "Prepare pytest temp parent",
    "Setup Python",
    "Setup Node",
    "Install dependencies",
    "Prepare database",
    "Run Unit Tests (full)",
    "Generate Quality Report",
    "Upload Coverage Reports",
    "Upload Quality Report",
    "Upload Architecture Audit Report",
    "Upload Playwright Artifacts",
    "Create or update failure issue",
}


def _load_workflow() -> dict[str, Any]:
    """Load the workflow as data without evaluating any workflow command."""

    loaded = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _steps_by_name(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a job's declared steps by their literal display name."""

    steps = job.get("steps")
    assert isinstance(steps, list)
    named_steps = [
        step for step in steps if isinstance(step, dict) and isinstance(step.get("name"), str)
    ]
    return {step["name"]: step for step in named_steps}


def _evaluate_workflow_condition(
    expression: str,
    *,
    event_name: str,
    workflow_name: str,
    suite: str | None,
) -> bool:
    """Evaluate the literal workflow boolean subset for representative GitHub contexts."""

    body = expression.removeprefix("${{").removesuffix("}}").strip()
    values = {
        "github.event_name": event_name,
        "github.workflow": workflow_name,
        "inputs.suite": suite,
    }
    for variable, value in values.items():
        body = body.replace(variable, repr(value))
    body = body.replace("||", " or ").replace("&&", " and ")
    tree = ast.parse(body, mode="eval")

    def evaluate(node: ast.expr) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(evaluate(value)) for value in node.values)
            if isinstance(node.op, ast.Or):
                return any(bool(evaluate(value)) for value in node.values)
        if isinstance(node, ast.Compare):
            left = evaluate(node.left)
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                right = evaluate(comparator)
                if isinstance(operator, ast.Eq):
                    matches = left == right
                elif isinstance(operator, ast.NotEq):
                    matches = left != right
                else:
                    raise AssertionError(
                        f"Unsupported workflow comparison: {type(operator).__name__}"
                    )
                if not matches:
                    return False
                left = right
            return True
        raise AssertionError(f"Unsupported workflow condition node: {type(node).__name__}")

    result = evaluate(tree.body)
    assert isinstance(result, bool)
    return result


def test_manual_scope_defaults_full_and_other_triggers_remain_full() -> None:
    """Only workflow_dispatch exposes reduced diagnostic scopes."""

    workflow = _load_workflow()
    events = workflow["on"]
    dispatch = events["workflow_dispatch"]["inputs"]["suite"]
    assert dispatch["type"] == "choice"
    assert dispatch["default"] == "full"
    assert dispatch["options"] == ["full", "unit-only", "critical-pg-only"]
    assert events["workflow_call"] == ""
    assert events["schedule"] == [{"cron": "0 2 * * *"}]

    jobs = workflow["jobs"]
    assert jobs["nightly"]["if"] == (
        "${{ github.event_name != 'workflow_dispatch' || github.workflow != 'Nightly Tests' "
        "|| inputs.suite != 'critical-pg-only' }}"
    )
    assert jobs["critical-postgres"]["if"] == (
        "${{ github.event_name != 'workflow_dispatch' || github.workflow != 'Nightly Tests' "
        "|| inputs.suite != 'unit-only' }}"
    )


def test_unit_only_keeps_only_unit_gates_and_skips_global_ratchet() -> None:
    """The manual diagnostic runs the complete unit selection but is not RC qualification."""

    workflow = _load_workflow()
    steps = _steps_by_name(workflow["jobs"]["nightly"])
    assert FULL_ONLY_STEPS <= steps.keys()
    assert FULL_ONLY_STEPS | UNIT_DIAGNOSTIC_ALLOWED_STEPS == steps.keys()
    for name in FULL_ONLY_STEPS:
        assert steps[name]["if"] == FULL_ONLY_IF

    unit_step = steps["Run Unit Tests (full)"]
    assert unit_step["timeout-minutes"] == "45"
    assert unit_step.get("if") is None
    report_gate = steps["Build final coverage report and enforce ratchet"]
    assert "generate_coverage_reports.py --check" in report_gate["run"]

    quality = steps["Generate Quality Report"]
    assert quality["if"] == "always()"
    assert steps["Upload Quality Report"]["if"] == "always()"
    assert steps["Create or update failure issue"]["if"] == (
        "failure() && github.workflow == 'Nightly Tests' && "
        "(github.event_name != 'workflow_dispatch' || inputs.suite != 'unit-only')"
    )


def test_workflow_conditions_default_to_full_except_explicit_standalone_unit_only() -> None:
    """Evaluate the actual YAML conditions across caller and manual event contexts."""

    jobs = _load_workflow()["jobs"]
    nightly_if = jobs["nightly"]["if"]
    postgres_if = jobs["critical-postgres"]["if"]
    steps = _steps_by_name(jobs["nightly"])
    full_only_if = steps[next(iter(FULL_ONLY_STEPS))]["if"]

    scenarios: list[tuple[str, str, str, str | None, bool, bool, bool]] = [
        ("scheduled nightly", "schedule", "Nightly Tests", None, True, True, True),
        ("workflow_call from manual RC", "workflow_dispatch", "RC Gate", None, True, True, True),
        ("workflow_call from PR", "pull_request", "RC Gate", None, True, True, True),
        (
            "standalone manual default",
            "workflow_dispatch",
            "Nightly Tests",
            "full",
            True,
            True,
            True,
        ),
        ("standalone manual full", "workflow_dispatch", "Nightly Tests", "full", True, True, True),
        (
            "standalone manual unit-only",
            "workflow_dispatch",
            "Nightly Tests",
            "unit-only",
            True,
            False,
            False,
        ),
        (
            "standalone manual critical-pg-only",
            "workflow_dispatch",
            "Nightly Tests",
            "critical-pg-only",
            False,
            True,
            True,
        ),
        (
            "standalone manual unknown scope",
            "workflow_dispatch",
            "Nightly Tests",
            "unexpected",
            True,
            True,
            True,
        ),
        (
            "standalone manual missing scope",
            "workflow_dispatch",
            "Nightly Tests",
            None,
            True,
            True,
            True,
        ),
    ]

    for (
        name,
        event_name,
        workflow_name,
        suite,
        expected_nightly,
        expected_postgres,
        expected_full,
    ) in scenarios:
        assert (
            _evaluate_workflow_condition(
                nightly_if,
                event_name=event_name,
                workflow_name=workflow_name,
                suite=suite,
            )
            is expected_nightly
        ), name
        assert (
            _evaluate_workflow_condition(
                postgres_if,
                event_name=event_name,
                workflow_name=workflow_name,
                suite=suite,
            )
            is expected_postgres
        ), name
        assert (
            _evaluate_workflow_condition(
                full_only_if,
                event_name=event_name,
                workflow_name=workflow_name,
                suite=suite,
            )
            is expected_full
        ), name


def test_unit_coverage_collection_and_reports_use_separate_processes() -> None:
    """Pytest keeps coverage collection and JUnit; report CLIs remain blocking."""

    unit_run = _steps_by_name(_load_workflow()["jobs"]["nightly"])["Run Unit Tests (full)"]["run"]
    pytest_command = unit_run.split("; then", maxsplit=1)[0]
    assert "tests/unit/ -vv -ra" in pytest_command
    assert "--timeout=300" in pytest_command
    assert "--timeout-method=thread" in pytest_command
    assert "--cov-config=.coveragerc" in pytest_command
    assert "--cov-report= " in pytest_command
    assert pytest_command.count("--cov-report=") == 1
    assert "--junitxml=reports/quality/nightly-unit.xml" in pytest_command
    assert "--no-cov" not in pytest_command

    report_commands = (
        "python -m coverage report --rcfile=.coveragerc --data-file=reports/quality/nightly-unit.coverage --show-missing",
        "python -m coverage xml --rcfile=.coveragerc --data-file=reports/quality/nightly-unit.coverage -o coverage-unit.xml",
        "python -m coverage html --rcfile=.coveragerc --data-file=reports/quality/nightly-unit.coverage -d htmlcov-unit",
    )
    offsets = [unit_run.index(command) for command in report_commands]
    assert offsets == sorted(offsets)
    assert unit_run.index("if python -m pytest") < offsets[0]
    assert unit_run.index("test -s .coverage") < offsets[0]
    assert unit_run.index("cp -- .coverage reports/quality/nightly-unit.coverage") < offsets[0]
    assert all(
        "--data-file=reports/quality/nightly-unit.coverage" in command
        for command in report_commands
    )
    assert (
        "--cov-append"
        in _steps_by_name(_load_workflow()["jobs"]["nightly"])["Run Component Tests"]["run"]
    )
    assert (
        "reports/quality/"
        in _steps_by_name(_load_workflow()["jobs"]["nightly"])["Upload Quality Report"]["with"][
            "path"
        ]
    )
    assert "set -euo pipefail" in unit_run
    assert 'exit "$pytest_status"' in unit_run
