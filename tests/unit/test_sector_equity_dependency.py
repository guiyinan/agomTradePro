"""Dependency contracts for the Sector and Equity boundary."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SECTOR_ROOT = REPO_ROOT / "apps/sector"


def _imports(source: str) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            result.add(node.module)
    return result


def test_sector_does_not_import_equity() -> None:
    violations = []
    for path in SECTOR_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(name.startswith("apps.equity") for name in _imports(path.read_text("utf-8"))):
            violations.append(str(path.relative_to(REPO_ROOT)))
    assert violations == []


def test_sector_market_gateway_is_neutral() -> None:
    path = SECTOR_ROOT / "application/market_returns_gateway.py"
    assert not any(name.startswith("apps.") for name in _imports(path.read_text("utf-8")))
