"""Dependency contract for the isolated Pulse and Regime cycle."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(source: str) -> set[str]:
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_pulse_does_not_import_regime() -> None:
    violations = []
    for path in (ROOT / "apps/pulse").rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(name.startswith("apps.regime") for name in _imports(path.read_text("utf-8"))):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []
