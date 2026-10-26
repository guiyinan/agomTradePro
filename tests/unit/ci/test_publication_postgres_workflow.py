"""Publication PostgreSQL evidence gate must follow the shared test inventory."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github/workflows/ci-publication-postgres.yml"
VALIDATOR_PATH = ROOT / "scripts/validate_release_rehearsal.py"
EVIDENCE_ARTIFACT = "publication-postgres-evidence"


def _required_postgresql_tests() -> tuple[str, ...]:
    """Read the validator's literal inventory without importing an operational script."""

    module = ast.parse(VALIDATOR_PATH.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "REQUIRED_POSTGRESQL_TESTS"
            for target in node.targets
        )
    )
    value = ast.literal_eval(assignment.value)
    assert isinstance(value, tuple)
    assert all(isinstance(item, str) for item in value)
    return value


def _evidence_gate_source() -> tuple[str, set[str]]:
    """Read the embedded validator and the official artifact's JUnit file list."""

    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["publication-postgres"]["steps"]
    evidence_step = next(
        step
        for step in steps
        if step.get("name") == "Reject missing or skipped PostgreSQL evidence"
    )
    run_script = evidence_step["run"]
    python_source = run_script.split("python - <<'PY'\n", maxsplit=1)[1].rsplit("\nPY", maxsplit=1)[
        0
    ]

    artifact_step = next(
        step
        for step in steps
        if step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == EVIDENCE_ARTIFACT
    )
    artifact_junit_files = {
        line.strip()
        for line in artifact_step["with"]["path"].splitlines()
        if line.strip().endswith(".xml")
    }
    return python_source, artifact_junit_files


def test_postgres_evidence_gate_uses_required_inventory_without_suite_counts() -> None:
    """Every retained JUnit suite is checked against the shared required identities."""

    python_source, artifact_junit_files = _evidence_gate_source()
    ast.parse(python_source)

    assert (
        "from scripts.validate_release_rehearsal import REQUIRED_POSTGRESQL_TESTS" in python_source
    )
    assert "set(REQUIRED_POSTGRESQL_TESTS) - observed_tests" in python_source
    assert "path.is_file() and path.stat().st_size > 0" in python_source
    assert "assert file_cases" in python_source
    assert "case.find('skipped') is None" in python_source
    assert "case.find('failure') is None and case.find('error') is None" in python_source
    assert "case.get('classname')" in python_source
    assert "case.get('name')" in python_source

    assert re.search(r"\blen\s*\([^)]*cases[^)]*\)\s*==\s*\d+\b", python_source) is None
    assert artifact_junit_files
    assert all(filename in python_source for filename in artifact_junit_files)


def test_postgres_evidence_gate_accepts_additional_testcases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """New observed JUnit cases pass when all shared required identities are present."""

    python_source, artifact_junit_files = _evidence_gate_source()
    extra_case = "tests.extra.test_future_publication_case::test_added_case"
    required_postgresql_tests = _required_postgresql_tests()

    def testcase(identity: str) -> str:
        classname, name = identity.rsplit("::", maxsplit=1)
        return f'<testcase classname="{classname}" name="{name}" />'

    for filename in artifact_junit_files:
        identities = (
            (*required_postgresql_tests, extra_case)
            if filename == "publication-postgres.xml"
            else (extra_case,)
        )
        case_elements = "".join(testcase(identity) for identity in identities)
        (tmp_path / filename).write_text(
            f"<testsuite>{case_elements}</testsuite>",
            encoding="utf-8",
        )
    (tmp_path / "sqlite-snapshot-rehearsal-report.json").write_text(
        json.dumps(
            {
                "outcome": "success",
                "fixture_row_count": 1,
                "source_serialized_row_count": 1,
                "source_row_count": 1,
                "mismatches": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    exec(compile(python_source, "publication-postgres-evidence-gate", "exec"), {})


def test_publication_workflow_keeps_standard_dispatch_behavior() -> None:
    """The ordinary publication workflow keeps its dispatch and concurrency contract."""
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = workflow["on"]
    assert "workflow_dispatch" in events
    assert events["workflow_dispatch"] == ""
    assert set(workflow["jobs"]) == {"publication-postgres"}
    assert "if" not in workflow["jobs"]["publication-postgres"]
    assert workflow["concurrency"]["group"] == (
        "publication-postgres-${{ github.workflow }}-${{ github.ref }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def _authority_flush_gate_source() -> str:
    """Read the exact inline cleanup gate, independently of publication suites."""
    workflow = yaml.load(
        (ROOT / ".github/workflows/nightly-tests.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Run full-registry transaction cleanup regressions on PostgreSQL"
    )
    source = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    ast.parse(source)
    return source


def _write_authority_flush_gate_fixture(tmp_path: Path, mutation: str = "") -> None:
    """Build explicit synthetic JUnit for gate rejection tests, without a database."""
    counts = {
        "tests.component.data_center.test_audited_price_sync_transaction": 5,
        "tests.component.data_center.test_audited_macro_sync_transaction": 3,
        "tests.component.config_center.test_aud05_atomic_activation": 18,
        "tests.component.data_center.test_audited_quote_sync_transaction": 7,
        "tests.component.data_center.test_current_publication_staging": 30,
        "tests.component.data_center.test_financial_source_time_audit_claim": 2,
    }
    if mutation == "old_aba_scope":
        counts["tests.component.data_center.test_audited_quote_sync_transaction"] = 5
        counts["tests.component.data_center.test_current_publication_staging"] = 24
    races = (
        "test_postgresql_bootstrap_race_has_one_first_winner",
        "test_postgresql_successor_race_has_one_first_winner",
    )
    cases: list[str] = []
    properties: list[str] = []
    for module, count in counts.items():
        for index in range(count):
            name = races[index] if "atomic_activation" in module and index < 2 else f"test_{index}"
            if mutation == "missing_race" and name == races[0]:
                name = "test_unrelated"
            classname = "tests.wrong_module" if mutation == "wrong_module" and not cases else module
            outcome = (
                f"<{mutation}/>"
                if mutation in {"failure", "error", "skipped"} and not cases
                else ""
            )
            cases.append(f'<testcase classname="{classname}" name="{name}">{outcome}</testcase>')
        pairs = [[index, index + 1] for index in range(count)]
        if not properties:
            if mutation == "missing_flush":
                pairs.pop()
            elif mutation == "decreasing_flush":
                pairs[0] = [2, 1]
            elif mutation == "bool_flush":
                pairs[0] = [False, 1]
        value = json.dumps(pairs).replace('"', "&quot;")
        properties.append(f'<property name="authority_generation_flushes" value="{value}"/>')
    destination = tmp_path / "reports/quality/postgres/authority-generation-flush.xml"
    destination.parent.mkdir(parents=True)
    destination.write_text(
        "<testsuite><properties>"
        + "".join(properties)
        + "</properties>"
        + "".join(cases)
        + "</testsuite>",
        encoding="utf-8",
    )


def test_authority_flush_gate_accepts_exact_current_module_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The current six-module 65-case scope passes its exact cleanup evidence gate."""
    _write_authority_flush_gate_fixture(tmp_path)
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    exec(compile(source, "authority-generation-flush-gate", "exec"), {})


@pytest.mark.parametrize(
    "mutation",
    [
        "old_aba_scope",
        "wrong_module",
        "failure",
        "error",
        "skipped",
        "missing_flush",
        "decreasing_flush",
        "bool_flush",
        "missing_race",
    ],
)
def test_authority_flush_gate_rejects_incomplete_or_invalid_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Case distribution, native races and every valid flush remain mandatory."""
    _write_authority_flush_gate_fixture(tmp_path, mutation)
    source = _authority_flush_gate_source()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        exec(compile(source, "authority-generation-flush-gate", "exec"), {})
