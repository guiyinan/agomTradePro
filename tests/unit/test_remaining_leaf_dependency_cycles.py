"""Dependency contracts for the remaining non-Account leaf cycles."""

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
    return result


@pytest.mark.parametrize(
    ("consumer", "provider"),
    [
        ("backtest", "audit"),
        ("policy", "signal"),
        ("realtime", "simulated_trading"),
        ("strategy", "simulated_trading"),
    ],
)
def test_consumer_does_not_import_provider(consumer: str, provider: str) -> None:
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
