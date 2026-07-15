"""Dependency contracts for the AI Capability and Terminal boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_CAPABILITY_ROOT = REPO_ROOT / "apps/ai_capability"


def _absolute_imports(source: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def test_ai_capability_does_not_import_terminal() -> None:
    """Keep the runtime dependency direction Terminal -> AI Capability."""
    violations: list[str] = []
    for path in AI_CAPABILITY_ROOT.rglob("*.py"):
        imports = _absolute_imports(path.read_text(encoding="utf-8"))
        if any(name == "apps.terminal" or name.startswith("apps.terminal.") for name in imports):
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []


def test_terminal_gateway_module_is_domain_neutral() -> None:
    """Keep the inversion contract free of Terminal implementation imports."""
    path = AI_CAPABILITY_ROOT / "application/terminal_gateway.py"
    source = path.read_text(encoding="utf-8")
    imports = _absolute_imports(source)
    assert not any(name.startswith("apps.") for name in imports)
