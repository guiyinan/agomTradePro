"""Dependency contracts for Events and Alpha Trigger."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS_ROOT = ROOT / "apps/events"


def _imports(source: str) -> set[str]:
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_events_does_not_import_alpha_trigger() -> None:
    violations = []
    for path in EVENTS_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(name.startswith("apps.alpha_trigger") for name in _imports(path.read_text("utf-8"))):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_alpha_candidate_registry_is_app_neutral() -> None:
    path = ROOT / "core/integration/alpha_candidate_registry.py"
    assert not any(name.startswith("apps.") for name in _imports(path.read_text("utf-8")))
