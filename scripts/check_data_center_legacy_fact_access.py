"""Reject production and executable-script access to retired fact projections."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict


class Contract(TypedDict):
    legacy_modules: dict[str, list[str]]
    legacy_tables: list[str]
    allowed_path_patterns: list[str]


class Violation(TypedDict):
    path: str
    line: int
    symbol: str
    kind: str


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "data_center_legacy_access_contracts.json"
PYTHON_ROOTS = ("apps", "core", "shared", "scripts", "sdk")
EXECUTABLE_TEXT_ROOTS = ("scripts", "docker", ".github")
EXECUTABLE_TEXT_SUFFIXES = frozenset({".sql", ".sh", ".ps1", ".bat", ".yml", ".yaml"})


def _load_contract() -> Contract:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return Contract(
        legacy_modules={
            str(module): [str(value) for value in symbols]
            for module, symbols in dict(raw["legacy_modules"]).items()
        },
        legacy_tables=[str(value) for value in raw.get("legacy_tables", [])],
        allowed_path_patterns=[str(value) for value in raw["allowed_path_patterns"]],
    )


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, path) for pattern in patterns)


def _python_files() -> list[Path]:
    paths: list[Path] = []
    for root_name in PYTHON_ROOTS:
        root = ROOT / root_name
        if root.exists():
            paths.extend(root.rglob("*.py"))
    return sorted(path for path in paths if "__pycache__" not in path.parts)


def _executable_text_files() -> Iterable[Path]:
    for root_name in EXECUTABLE_TEXT_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in EXECUTABLE_TEXT_SUFFIXES:
                yield path


def _resolved_import_from_module(node: ast.ImportFrom, relative: str) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = Path(relative).with_suffix("").parts[:-1]
    retained = max(0, len(package_parts) - (node.level - 1))
    prefix = list(package_parts[:retained])
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _dotted_attribute(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _legacy_table_selector_assignments(
    tree: ast.AST,
    legacy_tables: set[str],
) -> list[tuple[int, str]]:
    """Return legacy table literals assigned to table-selector variables."""

    matches: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        target_names = {target.id.lower() for target in targets if isinstance(target, ast.Name)}
        if not any("table" in name for name in target_names):
            continue
        value = node.value
        if value is None:
            continue
        for child in ast.walk(value):
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value in legacy_tables
            ):
                matches.append((child.lineno, child.value))
    return matches


def _raw_sql_violations(*, path: str, text: str, legacy_tables: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for table in legacy_tables:
        pattern = re.compile(
            rf"\b(?:from|join|insert\s+into|update|delete\s+from|truncate\s+table)\s+"
            rf"[\"'`]?{re.escape(table)}\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            violations.append(
                {
                    "path": path,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "symbol": table,
                    "kind": "legacy_table_sql_reference",
                }
            )
    return violations


def _scan_file(path: Path, contract: Contract) -> list[Violation]:
    relative = path.relative_to(ROOT).as_posix()
    if _allowed(relative, contract["allowed_path_patterns"]):
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        return [{"path": relative, "line": 1, "symbol": type(exc).__name__, "kind": "parse"}]

    symbols_by_module = {
        module: set(symbols) for module, symbols in contract["legacy_modules"].items()
    }
    known_symbols = {symbol for symbols in symbols_by_module.values() for symbol in symbols}
    legacy_tables = set(contract["legacy_tables"])
    imported_legacy_names: dict[str, str] = {}
    module_aliases: dict[str, str] = {}
    imported_modules: set[str] = set()
    violations: list[Violation] = []
    violations.extend(
        {
            "path": relative,
            "line": line,
            "symbol": table,
            "kind": "legacy_table_dynamic_reference",
        }
        for line, table in _legacy_table_selector_assignments(tree, legacy_tables)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolved_import_from_module(node, relative)
            symbols = symbols_by_module.get(module)
            if symbols is None:
                continue
            for alias in node.names:
                imported = sorted(symbols) if alias.name == "*" else [alias.name]
                for symbol in imported:
                    if symbol not in symbols:
                        continue
                    imported_legacy_names[alias.asname or symbol] = symbol
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": symbol,
                            "kind": (
                                "legacy_model_wildcard_import"
                                if alias.name == "*"
                                else "legacy_model_import"
                            ),
                        }
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in symbols_by_module:
                    continue
                if alias.asname:
                    module_aliases[alias.asname] = alias.name
                else:
                    imported_modules.add(alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_legacy_names:
            violations.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "symbol": imported_legacy_names[node.id],
                    "kind": "legacy_model_reference",
                }
            )
        elif isinstance(node, ast.Attribute):
            dotted = _dotted_attribute(node)
            if dotted is None:
                continue
            if isinstance(node.value, ast.Name) and node.value.id in module_aliases:
                module = module_aliases[node.value.id]
                if node.attr in symbols_by_module[module]:
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": node.attr,
                            "kind": "legacy_module_attribute_reference",
                        }
                    )
            for module in imported_modules:
                prefix = f"{module}."
                symbol = dotted.removeprefix(prefix) if dotted.startswith(prefix) else ""
                if symbol in symbols_by_module[module]:
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": symbol,
                            "kind": "legacy_module_attribute_reference",
                        }
                    )
        elif isinstance(node, ast.Call):
            call_name = _dotted_attribute(node.func) or ""
            string_args = [
                str(argument.value)
                for argument in node.args
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            ]
            if call_name.endswith("get_model") and any(
                value in known_symbols for value in string_args
            ):
                violations.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "symbol": next(value for value in string_args if value in known_symbols),
                        "kind": "legacy_dynamic_model_reference",
                    }
                )
            if call_name in {"importlib.import_module", "import_module", "__import__"} and any(
                value in symbols_by_module for value in string_args
            ):
                violations.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "symbol": next(
                            value for value in string_args if value in symbols_by_module
                        ),
                        "kind": "legacy_dynamic_module_import",
                    }
                )
    violations.extend(
        _raw_sql_violations(path=relative, text=text, legacy_tables=contract["legacy_tables"])
    )
    return violations


def _scan_executable_text(path: Path, contract: Contract) -> list[Violation]:
    relative = path.relative_to(ROOT).as_posix()
    if _allowed(relative, contract["allowed_path_patterns"]):
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return _raw_sql_violations(
        path=relative,
        text=text,
        legacy_tables=contract["legacy_tables"],
    )


def collect_violations(contract: Contract | None = None) -> list[Violation]:
    """Return deterministic semantic and raw-SQL legacy access violations."""

    loaded = contract or _load_contract()
    violations = [violation for path in _python_files() for violation in _scan_file(path, loaded)]
    violations.extend(
        violation
        for path in _executable_text_files()
        for violation in _scan_executable_text(path, loaded)
    )
    unique = {
        (item["path"], item["line"], item["symbol"], item["kind"]): item for item in violations
    }
    return [unique[key] for key in sorted(unique)]


def main() -> int:
    violations = collect_violations()
    if violations:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
        return 1
    print("Data Center legacy fact access guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
