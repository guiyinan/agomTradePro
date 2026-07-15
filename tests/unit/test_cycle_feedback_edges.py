"""Structural contracts for the feedback edges that keep the long app cycle alive."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _imports(source: str) -> set[str]:
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            result.add(node.args[0].value)
    return result


@pytest.mark.parametrize(
    ("consumer", "provider"),
    [
        ("rotation", "simulated_trading"),
        ("policy", "account"),
        ("realtime", "account"),
        ("signal", "alpha"),
        ("signal", "factor"),
        ("policy", "realtime"),
        ("share", "decision_rhythm"),
    ],
)
def test_feedback_edge_is_removed(consumer: str, provider: str) -> None:
    violations = []
    for path in (ROOT / "apps" / consumer).rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(
            name == f"apps.{provider}" or name.startswith(f"apps.{provider}.")
            for name in _imports(path.read_text("utf-8"))
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []
