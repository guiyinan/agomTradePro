"""Selected component browsers need their Python runtime before pytest starts."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_python_chromium_is_installed_before_any_runtime_pytest_step() -> None:
    """Account component journeys run even when the TUI change flag is false."""
    path = Path(__file__).resolve().parents[3] / ".github/workflows/ci-fast-feedback.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["fast-feedback"]["steps"]
    browser_index, browser_step = next(
        (index, step)
        for index, step in enumerate(steps)
        if "python -m playwright install chromium" in step.get("run", "")
    )
    pytest_indexes = [index for index, step in enumerate(steps) if "pytest" in step.get("run", "")]
    assert pytest_indexes
    assert browser_index < min(pytest_indexes)
    assert "if" not in browser_step


def test_targeted_pytest_uses_bounded_xdist_without_changing_selection() -> None:
    """Runtime targets keep the same selector under bounded xdist workers."""
    path = Path(__file__).resolve().parents[3] / ".github/workflows/ci-fast-feedback.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["fast-feedback"]
    assert job["timeout-minutes"] == "45"
    targeted_step = next(
        step for step in job["steps"] if step.get("name") == "Run targeted pytest suite"
    )
    run = targeted_step["run"]
    assert "pytest -p django" in run
    assert "-p tests.support.api_migrations_xdist" in run
    assert "-n 2 --dist=load --max-worker-restart=0" in run
    assert "-p no:cacheprovider" in run
    assert "--durations=15" in run
    assert "${{ needs.detect-tests.outputs.test-paths }}" in run
    assert run.count("${{ needs.detect-tests.outputs.test-paths }}") == 1
    assert "--junitxml" not in run
    assert "--no-migrations" not in run
    assert " -m " not in run
    assert " -k " not in run

    selector_step = next(
        step
        for step in workflow["jobs"]["detect-tests"]["steps"]
        if step.get("name") == "Select pytest targets"
    )
    assert "--profile logic_guardrails" in selector_step["run"]
