from __future__ import annotations

from pathlib import Path

import pytest


DISALLOWED_PATTERNS = (
    "MockModel",
    "SYNTH",
    "np.random.seed",
    "random.seed",
    "uniform(",
    "gauss(",
    "MCP_TEST_IND",
    "Using mock data",
)

ALLOWED_FILES = {
    "apps/account/management/commands/bootstrap_cold_start.py",
    "apps/account/management/commands/bootstrap_mcp_cold_start.py",
    "apps/decision_rhythm/interface/views.py",
}

IGNORED_PARTS = ("tests", "fixtures", "factories")


@pytest.mark.guardrail
def test_guardrail_no_new_runtime_mock_patterns_in_primary_code():
    violations = []

    for file_path in Path("apps").rglob("*.py"):
        normalized = file_path.as_posix()
        if normalized in ALLOWED_FILES:
            continue
        if any(part in file_path.parts for part in IGNORED_PARTS):
            continue

        content = file_path.read_text(encoding="utf-8")
        for pattern in DISALLOWED_PATTERNS:
            if pattern in content:
                violations.append(f"{normalized}: {pattern}")

    for file_path in Path("core").rglob("*.py"):
        content = file_path.read_text(encoding="utf-8")
        for pattern in DISALLOWED_PATTERNS:
            if pattern in content:
                violations.append(f"{file_path.as_posix()}: {pattern}")

    for file_path in Path("shared").rglob("*.py"):
        normalized = file_path.as_posix()
        if any(part in file_path.parts for part in IGNORED_PARTS):
            continue
        content = file_path.read_text(encoding="utf-8")
        for pattern in DISALLOWED_PATTERNS:
            if pattern in content:
                violations.append(f"{normalized}: {pattern}")

    assert not violations, "Runtime mock/fallback guardrail violations:\n" + "\n".join(violations)
