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
    "Verify registered current-data contract result",
    "Verify registered Celery task contract result",
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
    "Download PostgreSQL coverage from this run",
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
    "Verify full unit test result",
    "Download unit measurements from this run",
    "Restore unit coverage and render reports",
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
    postgres_result: str = "success",
    cancelled: bool = False,
) -> bool:
    """Evaluate the literal workflow boolean subset for representative GitHub contexts."""

    body = expression.removeprefix("${{").removesuffix("}}").strip()
    values = {
        "github.event_name": event_name,
        "github.workflow": workflow_name,
        "inputs.suite": suite,
        "needs.critical-postgres.result": postgres_result,
        "!cancelled()": not cancelled,
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
    assert set(jobs["nightly"]["needs"]) == {
        "critical-postgres",
        "sqlite-contracts",
        "nightly-unit",
    }
    assert jobs["nightly"]["if"] == (
        "${{ !cancelled() && (needs.critical-postgres.result == 'success' || "
        "needs.critical-postgres.result == 'skipped') && "
        "(github.event_name != 'workflow_dispatch' || github.workflow != 'Nightly Tests' "
        "|| inputs.suite != 'critical-pg-only') }}"
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

    unit_step = _steps_by_name(workflow["jobs"]["nightly-unit"])["Run Unit Tests (full)"]
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
        assert _evaluate_workflow_condition(
            jobs["sqlite-contracts"]["if"],
            event_name=event_name,
            workflow_name=workflow_name,
            suite=suite,
        ) is (expected_nightly and expected_full), name
        assert (
            _evaluate_workflow_condition(
                jobs["nightly-unit"]["if"],
                event_name=event_name,
                workflow_name=workflow_name,
                suite=suite,
            )
            is expected_nightly
        ), name
        assert (
            _evaluate_workflow_condition(
                nightly_if,
                event_name=event_name,
                workflow_name=workflow_name,
                suite=suite,
                postgres_result="success" if expected_postgres else "skipped",
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


def test_full_coverage_requires_both_inputs_from_the_same_run_and_commit() -> None:
    jobs = _load_workflow()["jobs"]
    native = _steps_by_name(jobs["critical-postgres"])
    main = _steps_by_name(jobs["nightly"])
    upload = native["Upload PostgreSQL coverage for this run"]["with"]
    download = main["Download PostgreSQL coverage from this run"]["with"]
    assert (
        upload["name"]
        == download["name"]
        == "postgres-coverage-${{ github.run_id }}-${{ github.sha }}"
    )
    assert "run-id" not in download and "repository" not in download
    assert upload["path"] == jobs["critical-postgres"]["env"]["COVERAGE_FILE"]
    assert upload["if-no-files-found"] == "error"
    for name, step in native.items():
        command = step.get("run", "")
        if "python -m pytest" in command and not name.startswith(
            "Check PostgreSQL test entrypoint"
        ):
            assert "--cov --cov-config=.coveragerc --cov-append --cov-report=" in command, name
        if "contract manifest on PostgreSQL" in name:
            for option in ("--cov", "--cov-config=.coveragerc", "--cov-append", "--cov-report="):
                assert f"--pytest-arg={option} " in command, name
    gate = main["Build final coverage report and enforce ratchet"]["run"]
    assert gate.index("test -s .coverage") < gate.index(
        'coverage combine --append --keep "$native"'
    )
    assert gate.index('test -s "$native"') < gate.index("coverage combine") < gate.index("--check")
    for result in ("failure", "cancelled"):
        assert not _evaluate_workflow_condition(
            jobs["nightly"]["if"],
            event_name="workflow_dispatch",
            workflow_name="Nightly Tests",
            suite="full",
            postgres_result=result,
        )


def test_unit_coverage_collection_and_reports_use_separate_processes() -> None:
    """Pytest keeps coverage collection and JUnit; report CLIs remain blocking."""

    jobs = _load_workflow()["jobs"]
    main = _steps_by_name(jobs["nightly"])
    producer = _steps_by_name(jobs["nightly-unit"])
    assert "needs" not in jobs["nightly-unit"]
    unit_run = producer["Run Unit Tests (full)"]["run"]
    upload = producer["Upload unit measurements for this run"]
    download = main["Download unit measurements from this run"]["with"]
    assert (
        upload["with"]["name"]
        == download["name"]
        == "nightly-unit-${{ github.run_id }}-${{ github.sha }}"
    )
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert {"reports/quality/nightly-unit.xml", "reports/quality/nightly-unit.coverage"} <= set(
        upload["with"]["path"].splitlines()
    )
    assert "run-id" not in download and "repository" not in download
    assert download["path"] == "reports/quality"
    verify = main["Verify full unit test result"]
    assert (
        verify["id"] == "unit"
        and verify["env"]["UNIT_RESULT"] == "${{ needs.nightly-unit.result }}"
    )
    assert verify["run"] == 'test "$UNIT_RESULT" = success'
    report_run = main["Restore unit coverage and render reports"]["run"]
    step_names = list(main)
    assert (
        step_names.index("Download unit measurements from this run")
        < step_names.index("Restore unit coverage and render reports")
        < step_names.index("Run Component Tests")
    )
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
    assert all(command not in unit_run for command in report_commands)
    offsets = [report_run.index(command) for command in report_commands]
    assert offsets == sorted(offsets)
    assert (
        unit_run.index("if python -m pytest")
        < unit_run.index("test -s .coverage")
        < unit_run.index("cp -- .coverage reports/quality/nightly-unit.coverage")
    )
    assert (
        report_run.index("test -s reports/quality/nightly-unit.coverage")
        < report_run.index("cp -- reports/quality/nightly-unit.coverage .coverage")
        < offsets[0]
    )
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


def test_sqlite_contract_results_reach_main_quality_report() -> None:
    """The independent runner returns each untraced manifest result to the main gate."""
    jobs = _load_workflow()["jobs"]
    runner = jobs["sqlite-contracts"]
    assert "needs" not in runner
    assert runner["runs-on"] == jobs["nightly"]["runs-on"]
    steps = _steps_by_name(runner)
    main = _steps_by_name(jobs["nightly"])
    for name in (
        "Checkout",
        "Setup Python",
        "Setup Node",
        "Install dependencies",
        "Prepare database",
    ):
        assert steps[name] == main[name]
    for label, key in (("current-data", "current_data"), ("Celery task", "celery")):
        producer = steps[f"Run registered {label} contract nodeids"]
        gate = main[f"Verify registered {label} contract result"]
        assert producer["id"] == gate["id"] == key
        assert "--cov" not in producer["run"]
        assert "--pytest-arg=--reuse-db" in producer["run"]
        assert "--pytest-arg=--timeout=300" in producer["run"]
        assert runner["outputs"][key] == "${{ steps." + key + ".outcome }}"
        assert (
            gate["env"]["CONTRACT_OUTCOME"] == "${{ needs.sqlite-contracts.outputs." + key + " }}"
        )
        assert gate["run"] == 'test "$CONTRACT_OUTCOME" = success'


def test_main_suites_defer_cumulative_reports_and_keep_required_xml() -> None:
    """Retain raw branch hits for the final ratchet and XML for its existing consumers."""
    steps = _load_workflow()["jobs"]["nightly"]["steps"]
    by_id = {step.get("id"): step for step in steps}
    slices = (
        "component",
        "api_migrations",
        "critical_sqlite",
        "app_local",
        "sdk",
        "mcp",
        "e2e",
        "integration",
        "guardrails",
    )
    xml_reports = {
        "integration": "xml:coverage-integration.xml",
        "guardrails": "xml:coverage-guardrail.xml",
    }
    for key in slices:
        args = by_id[key]["run"].split()
        assert {"--cov", "--cov-config=.coveragerc", "--cov-append"} <= set(args)
        assert [arg for arg in args if arg.startswith("--cov-report=")] == [
            "--cov-report=" + xml_reports.get(key, "")
        ]
