"""Dependency contracts for Data Center business runtime integrations."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_CENTER_ROOT = ROOT / "apps/data_center"
FORBIDDEN_PROVIDER_IMPORTS = (
    "apps.alpha",
    "apps.dashboard",
    "apps.pulse",
    "apps.realtime",
)


def _imports(source: str) -> set[str]:
    result = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_data_center_does_not_import_business_runtime_providers() -> None:
    violations = []
    for path in DATA_CENTER_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        imports = _imports(path.read_text("utf-8"))
        if any(
            name == provider or name.startswith(f"{provider}.")
            for name in imports
            for provider in FORBIDDEN_PROVIDER_IMPORTS
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []
