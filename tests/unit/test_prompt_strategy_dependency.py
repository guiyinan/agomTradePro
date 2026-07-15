"""Dependency contracts for the Prompt and Strategy boundary."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = ROOT / "apps/prompt"


def _imports(source: str) -> set[str]:
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_prompt_does_not_import_strategy() -> None:
    violations = []
    for path in PROMPT_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(name.startswith("apps.strategy") for name in _imports(path.read_text("utf-8"))):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_prompt_strategy_gateway_is_neutral() -> None:
    path = PROMPT_ROOT / "application/strategy_gateway.py"
    assert not any(name.startswith("apps.") for name in _imports(path.read_text("utf-8")))
