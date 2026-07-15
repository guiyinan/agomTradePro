"""Dependency contracts for the Share and Simulated Trading boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARE_ROOT = REPO_ROOT / "apps/share"


def _absolute_imports(source: str) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def test_share_does_not_import_simulated_trading() -> None:
    """Keep the runtime dependency direction Simulated Trading -> Share."""
    violations: list[str] = []
    for path in SHARE_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        imports = _absolute_imports(path.read_text(encoding="utf-8"))
        if any(
            name == "apps.simulated_trading" or name.startswith("apps.simulated_trading.")
            for name in imports
        ):
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []


def test_share_account_gateway_contract_is_domain_only() -> None:
    """Keep the gateway contract free of business-module imports."""
    path = SHARE_ROOT / "domain/account_gateway.py"
    imports = _absolute_imports(path.read_text(encoding="utf-8"))
    assert not any(name.startswith("apps.") for name in imports)
