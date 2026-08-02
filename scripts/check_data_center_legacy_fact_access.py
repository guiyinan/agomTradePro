"""Reject new business access to retired Data Center fact projections.

The canonical Data Center facts are the only runtime source for D0/D1/D4/D5/D7.
Legacy model definitions, migrations, tests, and the frozen read-only admin
projection remain visible until the M9 destructive-cleanup gate.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import TypedDict


class Contract(TypedDict):
    legacy_modules: dict[str, list[str]]
    allowed_path_patterns: list[str]


class Violation(TypedDict):
    path: str
    line: int
    symbol: str
    kind: str


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "data_center_legacy_access_contracts.json"


def _load_contract() -> Contract:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return Contract(
        legacy_modules={
            str(module): [str(value) for value in symbols]
            for module, symbols in dict(raw["legacy_modules"]).items()
        },
        allowed_path_patterns=[str(value) for value in raw["allowed_path_patterns"]],
    )


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, path) for pattern in patterns)


def _python_files() -> list[Path]:
    paths: list[Path] = []
    for source_root in (ROOT / "apps", ROOT / "core", ROOT / "shared"):
        paths.extend(source_root.rglob("*.py"))
    return sorted(paths)


def _scan_file(path: Path, contract: Contract) -> list[Violation]:
    relative = path.relative_to(ROOT).as_posix()
    if _allowed(relative, contract["allowed_path_patterns"]):
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError) as exc:
        return [{"path": relative, "line": 1, "symbol": type(exc).__name__, "kind": "parse"}]

    symbols_by_module = {
        module: set(symbols) for module, symbols in contract["legacy_modules"].items()
    }
    imported_legacy_names: set[str] = set()
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in symbols_by_module:
            symbols = symbols_by_module[node.module]
            for alias in node.names:
                if alias.name == "*" or alias.name in symbols:
                    imported_legacy_names.add(alias.asname or alias.name)
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": alias.name,
                            "kind": "legacy_model_import",
                        }
                    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_legacy_names:
            violations.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "symbol": node.id,
                    "kind": "legacy_model_reference",
                }
            )
    return violations


def main() -> int:
    contract = _load_contract()
    violations = [violation for path in _python_files() for violation in _scan_file(path, contract)]
    if violations:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
        return 1
    print("Data Center legacy fact access guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
