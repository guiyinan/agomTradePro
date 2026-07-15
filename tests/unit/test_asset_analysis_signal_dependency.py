"""Dependency contracts for the Asset Analysis and Signal boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ANALYSIS_ROOT = REPO_ROOT / "apps/asset_analysis"


def _absolute_imports(source: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def test_asset_analysis_does_not_import_signal() -> None:
    """Keep the runtime dependency direction Signal -> Asset Analysis."""
    violations: list[str] = []
    for path in ASSET_ANALYSIS_ROOT.rglob("*.py"):
        imports = _absolute_imports(path.read_text(encoding="utf-8"))
        if any(name == "apps.signal" or name.startswith("apps.signal.") for name in imports):
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []


def test_signal_context_gateway_is_domain_neutral() -> None:
    """Keep the inversion contract free of Signal implementation imports."""
    path = ASSET_ANALYSIS_ROOT / "application/signal_context_gateway.py"
    imports = _absolute_imports(path.read_text(encoding="utf-8"))
    assert not any(name.startswith("apps.") for name in imports)
