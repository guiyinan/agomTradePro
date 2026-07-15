"""Dependency contracts for Decision Rhythm integrations."""

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


@pytest.mark.parametrize("app_name", ["alpha", "alpha_trigger", "events", "simulated_trading"])
def test_consumer_apps_do_not_import_decision_rhythm(app_name: str) -> None:
    violations = []
    for path in (ROOT / "apps" / app_name).rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(
            name.startswith("apps.decision_rhythm") for name in _imports(path.read_text("utf-8"))
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_decision_request_registry_is_app_neutral() -> None:
    path = ROOT / "core/integration/decision_request_registry.py"
    assert path.exists()
    assert not any(name.startswith("apps.") for name in _imports(path.read_text("utf-8")))
