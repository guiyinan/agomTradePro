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
