"""Publication PostgreSQL evidence gate must follow the shared test inventory."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

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
