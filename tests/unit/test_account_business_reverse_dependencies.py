"""Dependency contracts for Account-owned identity and configuration code."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_ROOT = ROOT / "apps/account"
FORBIDDEN_APPS = (
    "audit",
    "backtest",
    "equity",
    "factor",
    "policy",
    "simulated_trading",
)


def _forbidden_imports(source: str) -> set[str]:
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imports.add(node.args[0].value)
    return {
        name
        for name in imports
        if any(name == f"apps.{app}" or name.startswith(f"apps.{app}.") for app in FORBIDDEN_APPS)
    }


def test_account_does_not_import_business_provider_apps() -> None:
    violations = []
    for path in ACCOUNT_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        forbidden = _forbidden_imports(path.read_text("utf-8"))
        if forbidden:
            violations.append((str(path.relative_to(ROOT)), sorted(forbidden)))
    assert violations == []
