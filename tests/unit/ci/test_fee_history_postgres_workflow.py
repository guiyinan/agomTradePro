from __future__ import annotations

import textwrap
from pathlib import Path
from typing import cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-tests.yml"
JOB = "critical-postgres"
TEST_STEP = "Run PostgreSQL critical reliability tests"
GUARD_STEP = "Verify fee correction PostgreSQL case in critical JUnit"
MIGRATION_STEP = "Run PostgreSQL migration integrity tests"
FEE_NODE = (
    "tests/component/simulated_trading/test_fee_correction_v4_history.py::"
    "test_fee_correction_preserves_nonempty_v4_fill_prefix_and_history_projection"
)
FEE_CLASS = "tests.component.simulated_trading.test_fee_correction_v4_history"
FEE_NAME = "test_fee_correction_preserves_nonempty_v4_fill_prefix_and_history_projection"
REPORT = "reports/quality/postgres/critical.xml"


def _steps() -> list[dict[str, object]]:
    """Read the steps of the actual critical PostgreSQL workflow job."""

    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    jobs = document.get("jobs")
    assert isinstance(jobs, dict) and isinstance(jobs.get(JOB), dict)
    steps = cast(dict[str, object], jobs[JOB]).get("steps")
    assert isinstance(steps, list) and all(isinstance(step, dict) for step in steps)
    return cast(list[dict[str, object]], steps)


def _step(steps: list[dict[str, object]], name: str) -> dict[str, object]:
    """Find one workflow step by its display name."""

    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, f"Expected one step named {name!r}"
    return matches[0]


def _guard_program(run_body: str) -> str:
    """Extract the executable Python heredoc from the workflow JUnit step."""

    lines = run_body.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "python - <<'PY'"]
    assert len(starts) == 1
    end = next(
        (index for index in range(starts[0] + 1, len(lines)) if lines[index].strip() == "PY"),
        None,
    )
    assert end is not None
    return textwrap.dedent("\n".join(lines[starts[0] + 1 : end]))


def _write_junit(tmp_path: Path, case_bodies: list[str]) -> None:
    """Write a synthetic JUnit report with the requested matching case bodies."""

    cases = "".join(
        f'<testcase classname="{FEE_CLASS}" name="{FEE_NAME}">{body}</testcase>'
        for body in case_bodies
    )
    report = tmp_path / REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")


def _run_guard(program: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute the actual workflow guard against the temporary JUnit report."""

    monkeypatch.chdir(tmp_path)
    exec(compile(program, "critical_postgres_junit_guard.py", "exec"), {"__name__": "__main__"})


def test_fee_history_node_is_explicitly_routed_to_critical_postgres() -> None:
    """Require one exact fee node, explicit PostgreSQL settings, and its adjacent guard."""

    steps = _steps()
    job = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["jobs"][JOB]
    assert job["services"]["postgres"]["image"] == "postgres:16"
    test_step = _step(steps, TEST_STEP)
    assert test_step["env"]["DJANGO_SETTINGS_MODULE"] == "core.settings.critical_postgres_test"
    assert test_step["env"]["AGOM_CRITICAL_TEST_DB_NAME"] == "test_agomtradepro_critical"
    run_body = cast(str, test_step["run"])
    assert run_body.count(FEE_NODE) == 1 and "tests/critical/" in run_body
    assert "--reuse-db" in run_body and "--no-migrations" in run_body
    assert f"--junitxml={REPORT}" in run_body

    guard_step = _step(steps, GUARD_STEP)
    migration_step = _step(steps, MIGRATION_STEP)
    assert steps.index(guard_step) == steps.index(test_step) + 1 < steps.index(migration_step)
    assert REPORT in cast(str, guard_step["run"])


@pytest.mark.parametrize(
    ("case_bodies", "should_pass"),
    [
        pytest.param([""], True, id="one-passed-case"),
        pytest.param([], False, id="missing-case"),
        pytest.param(["", ""], False, id="duplicate-case"),
        pytest.param(["<skipped/>"], False, id="skipped-case"),
        pytest.param(["<failure/>"], False, id="failed-case"),
        pytest.param(["<error/>"], False, id="errored-case"),
    ],
)
def test_workflow_junit_guard_requires_one_successful_case(
    case_bodies: list[str],
    should_pass: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the workflow's real guard over success and rejection reports."""

    guard_body = cast(str, _step(_steps(), GUARD_STEP)["run"])
    _write_junit(tmp_path, case_bodies)
    program = _guard_program(guard_body)
    if should_pass:
        _run_guard(program, tmp_path, monkeypatch)
    else:
        with pytest.raises(AssertionError):
            _run_guard(program, tmp_path, monkeypatch)
