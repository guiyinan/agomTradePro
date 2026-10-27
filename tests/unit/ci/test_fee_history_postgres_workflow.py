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
HISTORY_NODES = (
    "tests/component/simulated_trading/test_execution_settlement_v4_history_guard.py::"
    "test_postgres_cross_account_receipt_blocks_without_waiting_for_foreign_lock",
    "tests/component/simulated_trading/test_execution_settlement_v4_history_guard.py::"
    "test_postgres_position_write_does_not_wait_for_cross_account_receipt_parent_lock",
)
FEE_CLASS = "tests.component.simulated_trading.test_fee_correction_v4_history"
FEE_NAME = "test_fee_correction_preserves_nonempty_v4_fill_prefix_and_history_projection"
HISTORY_CLASS = "tests.component.simulated_trading.test_execution_settlement_v4_history_guard"
HISTORY_CASES = tuple(
    (HISTORY_CLASS, f"{test_name}[{foreign_locator}]")
    for test_name in (
        "test_postgres_cross_account_receipt_blocks_without_waiting_for_foreign_lock",
        "test_postgres_position_write_does_not_wait_for_cross_account_receipt_parent_lock",
    )
    for foreign_locator in ("reservation", "trade")
)
FEE_NATIVE_FILES = (
    "tests/component/simulated_trading/test_fee_correction_concurrency.py",
    "tests/component/simulated_trading/test_fee_correction_confirmation_concurrency.py",
    "tests/migrations/test_simulated_fee_correction_migrations.py",
)
FEE_NATIVE_CASES = (
    *(
        ("tests.component.simulated_trading.test_fee_correction_concurrency", name)
        for name in (
            "test_postgres_same_idempotency_key_writes_one_event_across_two_backends",
            "test_postgres_different_keys_competing_for_one_predecessor_commit_once",
            "test_postgres_reservation_writer_holds_parent_before_correction_rejects_active_hold",
            "test_real_posting_failure_rolls_back_event_and_preserves_trade_and_receipts",
        )
    ),
    *(
        ("tests.component.simulated_trading.test_fee_correction_confirmation_concurrency", name)
        for name in (
            "test_postgres_same_session_same_key_serializes_on_session_row",
            "test_postgres_two_sessions_compete_on_one_fee_correction_head[same-key-cross-session]",
            "test_postgres_two_sessions_compete_on_one_fee_correction_head[different-key-same-head]",
            "test_postgres_confirmation_rechecks_password_after_account_lock_wait",
            "test_postgres_disabled_policy_blocks_confirmation_after_account_lock_wait",
        )
    ),
    (
        "tests.migrations.test_simulated_fee_correction_migrations",
        "test_0040_roundtrip_preserves_legacy_rows_and_reverse_refuses_evidence",
    ),
)
REQUIRED_CASES = ((FEE_CLASS, FEE_NAME), *HISTORY_CASES, *FEE_NATIVE_CASES)
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


def _write_junit(
    tmp_path: Path,
    fee_case_bodies: list[str],
    history_case_overrides: dict[tuple[str, str], list[str]] | None = None,
) -> None:
    """Write the full success fixture with requested per-case mutations."""

    overrides = history_case_overrides or {}
    cases = "".join(
        f'<testcase classname="{classname}" name="{name}">{body}</testcase>'
        for classname, name in REQUIRED_CASES
        for body in (
            fee_case_bodies
            if (classname, name) == (FEE_CLASS, FEE_NAME)
            else overrides.get((classname, name), [""])
        )
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
    for node in HISTORY_NODES:
        assert run_body.count(node) == 1, f"Expected one explicit PostgreSQL selector: {node}"
    for path in FEE_NATIVE_FILES:
        assert run_body.count(path) == 1, f"Expected one native fee test selector: {path}"
    assert "--migrations" in run_body
    assert "--reuse-db" in run_body and "--no-migrations" not in run_body
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


@pytest.mark.parametrize(
    "case_identity",
    HISTORY_CASES,
    ids=(
        "cross-account-reservation",
        "cross-account-trade",
        "position-write-reservation",
        "position-write-trade",
    ),
)
@pytest.mark.parametrize(
    "case_bodies",
    (
        pytest.param([], id="missing"),
        pytest.param(["", ""], id="duplicate"),
        pytest.param(["<skipped/>"], id="skipped"),
        pytest.param(["<failure/>"], id="failed"),
        pytest.param(["<error/>"], id="errored"),
    ),
)
def test_workflow_junit_guard_requires_each_history_guard_case_once_and_successful(
    case_identity: tuple[str, str],
    case_bodies: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject omission, duplication, or non-success for every required history case."""

    guard_body = cast(str, _step(_steps(), GUARD_STEP)["run"])
    _write_junit(tmp_path, [""], {case_identity: case_bodies})
    program = _guard_program(guard_body)
    with pytest.raises(AssertionError):
        _run_guard(program, tmp_path, monkeypatch)


@pytest.mark.parametrize("case_identity", FEE_NATIVE_CASES)
@pytest.mark.parametrize(
    "case_bodies",
    (
        pytest.param([], id="missing"),
        pytest.param(["", ""], id="duplicate"),
        pytest.param(["<skipped/>"], id="skipped"),
        pytest.param(["<failure/>"], id="failed"),
        pytest.param(["<error/>"], id="errored"),
    ),
)
def test_workflow_junit_guard_requires_each_native_fee_case(
    case_identity: tuple[str, str],
    case_bodies: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject missing or non-successful fee race, confirmation, and migration evidence."""

    guard_body = cast(str, _step(_steps(), GUARD_STEP)["run"])
    _write_junit(tmp_path, [""], {case_identity: case_bodies})
    with pytest.raises(AssertionError):
        _run_guard(_guard_program(guard_body), tmp_path, monkeypatch)
