"""Build a deterministic inventory for the canonical data-center migration.

The inventory is intentionally static-source based.  It does not import the
Django project, touch a database, or execute provider code, so CI can run it
before migrations and production credentials are available.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "governance" / "data_center_architecture_inventory.json"
LEGACY_ACCESS_CONTRACT = ROOT / "governance" / "data_center_legacy_access_contracts.json"
EXTERNAL_HTTP_DISPOSITIONS = ROOT / "governance" / "data_center_external_http_dispositions.json"
SOURCE_ROOTS = ("apps", "core", "shared")
ALLOWED_PROVIDER_ROOT = "apps/data_center/infrastructure/"
PROVIDER_SDK_MODULES = frozenset({"tushare", "akshare", "xtquant", "baostock"})
HTTP_MODULES = frozenset({"requests", "httpx", "aiohttp"})
NON_DATA_HTTP_SCOPES = frozenset({"ai_inference", "internal_control_plane", "alert_delivery"})
SURFACE_PATTERN = re.compile(r"\b(current|latest|realtime|summary)\b", re.IGNORECASE)
RUNTIME_ENV_PATTERN = re.compile(r"\b(?:os\.getenv|os\.environ|getenv|env)\s*\(")
CELERY_DECORATOR_PATTERN = re.compile(r"@(?:shared_task|app\.task|celery\.task)\b")


def _iter_python_files() -> Iterable[Path]:
    """Yield deterministic production Python files, excluding generated caches."""

    for root_name in SOURCE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        yield from sorted(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and "migrations" not in path.parts
        )


def _source_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _import_names(tree: ast.AST) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, node.lineno))
    return imports


def _load_legacy_access_contract() -> tuple[dict[str, set[str]], list[re.Pattern[str]]]:
    """Load module-qualified legacy symbols and explicitly retained owner paths."""

    payload = json.loads(LEGACY_ACCESS_CONTRACT.read_text(encoding="utf-8"))
    modules = {
        str(module): {str(symbol) for symbol in symbols}
        for module, symbols in dict(payload["legacy_modules"]).items()
    }
    allowed = [re.compile(str(pattern)) for pattern in payload.get("allowed_path_patterns", [])]
    return modules, allowed


def _load_external_http_dispositions() -> dict[tuple[str, str], dict[str, str]]:
    """Load exact, owner-bound dispositions for outbound non-data HTTP imports."""

    payload = json.loads(EXTERNAL_HTTP_DISPOSITIONS.read_text(encoding="utf-8"))
    if set(payload) != {"schema_version", "owner", "policy", "entries"}:
        raise ValueError("external HTTP disposition contract keys are invalid")
    if payload["schema_version"] != "1.0" or payload["owner"] != "data-center-architecture":
        raise ValueError("external HTTP disposition contract identity is invalid")
    if not isinstance(payload["policy"], str) or not payload["policy"].strip():
        raise ValueError("external HTTP disposition policy is required")
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise ValueError("external HTTP disposition entries must be a list")

    dispositions: dict[tuple[str, str], dict[str, str]] = {}
    expected_keys = {"path", "import", "owner", "scope", "reason"}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != expected_keys:
            raise ValueError("external HTTP disposition entry keys are invalid")
        if any(not isinstance(raw_entry[key], str) for key in expected_keys):
            raise ValueError("external HTTP disposition fields must be strings")
        entry = {key: raw_entry[key].strip() for key in expected_keys}
        path = entry["path"]
        import_name = entry["import"]
        if (
            not path.endswith(".py")
            or not path.startswith(tuple(f"{root}/" for root in SOURCE_ROOTS))
            or "*" in path
            or "?" in path
            or import_name not in HTTP_MODULES
            or not entry["owner"]
            or any(character.isspace() for character in entry["owner"])
            or entry["scope"] not in NON_DATA_HTTP_SCOPES
            or len(entry["reason"]) < 20
        ):
            raise ValueError("external HTTP disposition entry is invalid")
        key = (path, import_name)
        if key in dispositions:
            raise ValueError("external HTTP disposition entry is duplicated")
        dispositions[key] = entry
    return dispositions


def _resolved_import_from_module(node: ast.ImportFrom, relative: str) -> str:
    """Resolve an absolute module name for both absolute and relative imports."""

    if node.level == 0:
        return node.module or ""
    package_parts = Path(relative).with_suffix("").parts[:-1]
    retained = max(0, len(package_parts) - (node.level - 1))
    prefix = list(package_parts[:retained])
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _dotted_attribute(node: ast.AST) -> str | None:
    """Return a dotted name for a simple Name/Attribute expression."""

    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _legacy_fact_references(
    *,
    tree: ast.AST,
    relative: str,
    modules: dict[str, set[str]],
    allowed_paths: list[re.Pattern[str]],
) -> list[dict[str, object]]:
    """Return semantic legacy references without same-name domain false positives."""

    if any(pattern.search(relative) for pattern in allowed_paths):
        return []
    imported_names: dict[str, str] = {}
    module_aliases: dict[str, str] = {}
    imported_modules: set[str] = set()
    references: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolved_import_from_module(node, relative)
            symbols = modules.get(module)
            if symbols is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    for symbol in sorted(symbols):
                        imported_names[symbol] = symbol
                        references.append(
                            {
                                "path": relative,
                                "line": node.lineno,
                                "symbol": symbol,
                                "kind": "legacy_model_wildcard_import",
                            }
                        )
                elif alias.name in symbols:
                    imported_names[alias.asname or alias.name] = alias.name
                    references.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": alias.name,
                            "kind": "legacy_model_import",
                        }
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
                    else:
                        imported_modules.add(alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_names:
            references.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "symbol": imported_names[node.id],
                    "kind": "legacy_model_reference",
                }
            )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
            and node.attr in modules[module_aliases[node.value.id]]
        ):
            references.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "symbol": node.attr,
                    "kind": "legacy_module_attribute_reference",
                }
            )
        elif isinstance(node, ast.Attribute):
            dotted = _dotted_attribute(node)
            if dotted is None:
                continue
            for module in imported_modules:
                prefix = f"{module}."
                if dotted.startswith(prefix) and dotted.removeprefix(prefix) in modules[module]:
                    references.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "symbol": dotted.removeprefix(prefix),
                            "kind": "legacy_module_attribute_reference",
                        }
                    )
    return references


def build_inventory() -> dict[str, object]:
    """Return a deterministic source inventory with no generated timestamp."""

    provider_imports: list[dict[str, object]] = []
    direct_data_center_imports: list[dict[str, object]] = []
    external_http_imports: list[dict[str, object]] = []
    approved_non_data_http_imports: list[dict[str, object]] = []
    cross_app_orm: list[dict[str, object]] = []
    legacy_fact_reads: list[dict[str, object]] = []
    current_surfaces: list[dict[str, object]] = []
    data_tasks: list[dict[str, object]] = []
    runtime_parameters: set[str] = set()
    legacy_modules, legacy_allowed_paths = _load_legacy_access_contract()
    http_dispositions = _load_external_http_dispositions()
    matched_http_dispositions: set[tuple[str, str]] = set()

    for path in _iter_python_files():
        relative = _source_path(path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            continue
        for import_name, lineno in _import_names(tree):
            top_level = import_name.split(".", 1)[0]
            if (
                "tests/" not in relative
                and relative != "apps/data_center"
                and not relative.startswith("apps/data_center/")
                and (
                    import_name.startswith("apps.data_center.infrastructure")
                    or import_name.startswith("apps.data_center.application.interface_services")
                    or import_name.startswith("apps.data_center.application.query_services")
                    or import_name.startswith("apps.data_center.application.read_facade")
                )
            ):
                direct_data_center_imports.append(
                    {
                        "path": relative,
                        "line": lineno,
                        "import": import_name,
                    }
                )
            if top_level in PROVIDER_SDK_MODULES:
                if not relative.startswith(ALLOWED_PROVIDER_ROOT):
                    provider_imports.append(
                        {
                            "path": relative,
                            "line": lineno,
                            "import": import_name,
                        }
                    )
            elif top_level in HTTP_MODULES and not relative.startswith(ALLOWED_PROVIDER_ROOT):
                row: dict[str, object] = {
                    "path": relative,
                    "line": lineno,
                    "import": import_name,
                }
                disposition_key = (relative, import_name)
                disposition = http_dispositions.get(disposition_key)
                if disposition is None:
                    external_http_imports.append(row)
                else:
                    matched_http_dispositions.add(disposition_key)
                    approved_non_data_http_imports.append(
                        {
                            **row,
                            "owner": disposition["owner"],
                            "scope": disposition["scope"],
                            "reason": disposition["reason"],
                        }
                    )
            if ".infrastructure.models" in import_name and relative.startswith("apps/"):
                source_app = relative.split("/", 2)[1]
                target_parts = import_name.split(".")
                target_app = target_parts[1] if len(target_parts) > 1 else ""
                if source_app != target_app:
                    cross_app_orm.append(
                        {
                            "path": relative,
                            "line": lineno,
                            "import": import_name,
                        }
                    )
        legacy_fact_reads.extend(
            _legacy_fact_references(
                tree=tree,
                relative=relative,
                modules=legacy_modules,
                allowed_paths=legacy_allowed_paths,
            )
        )
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if SURFACE_PATTERN.search(stripped) and "#" not in stripped[:2]:
                current_surfaces.append({"path": relative, "line": lineno, "text": stripped})
            if CELERY_DECORATOR_PATTERN.search(stripped):
                data_tasks.append({"path": relative, "line": lineno, "text": stripped})
            match = RUNTIME_ENV_PATTERN.search(stripped)
            if match:
                runtime_parameters.add(stripped[:200])

    stale_http_dispositions = set(http_dispositions) - matched_http_dispositions
    if stale_http_dispositions:
        stale = ", ".join(f"{path}:{module}" for path, module in sorted(stale_http_dispositions))
        raise ValueError(f"stale external HTTP dispositions: {stale}")

    grouped_legacy: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in legacy_fact_reads:
        grouped_legacy[str(item["symbol"])].append(item)

    return {
        "schema_version": "1.0",
        "scan_roots": list(SOURCE_ROOTS),
        "provider_imports_outside_data_center": sorted(
            provider_imports, key=lambda row: (str(row["path"]), int(str(row["line"])))
        ),
        "direct_data_center_imports_outside_data_center": sorted(
            direct_data_center_imports,
            key=lambda row: (str(row["path"]), int(str(row["line"]))),
        ),
        "external_http_imports_for_review": sorted(
            external_http_imports,
            key=lambda row: (str(row["path"]), int(str(row["line"]))),
        ),
        "approved_non_data_http_imports": sorted(
            approved_non_data_http_imports,
            key=lambda row: (str(row["path"]), int(str(row["line"]))),
        ),
        "cross_app_orm_imports": sorted(
            cross_app_orm, key=lambda row: (str(row["path"]), int(str(row["line"])))
        ),
        "legacy_fact_references": {
            key: sorted(value, key=lambda row: (str(row["path"]), int(str(row["line"]))))
            for key, value in sorted(grouped_legacy.items())
        },
        "current_surface_references": sorted(
            current_surfaces, key=lambda row: (str(row["path"]), int(str(row["line"])))
        ),
        "data_write_task_decorators": sorted(
            data_tasks, key=lambda row: (str(row["path"]), int(str(row["line"])))
        ),
        "runtime_parameter_references": sorted(runtime_parameters),
        "counts": {
            "provider_imports_outside_data_center": len(provider_imports),
            "direct_data_center_imports_outside_data_center": len(direct_data_center_imports),
            "external_http_imports_for_review": len(external_http_imports),
            "approved_non_data_http_imports": len(approved_non_data_http_imports),
            "cross_app_orm_imports": len(cross_app_orm),
            "legacy_fact_references": len(legacy_fact_reads),
            "current_surface_references": len(current_surfaces),
            "data_write_task_decorators": len(data_tasks),
            "runtime_parameter_references": len(runtime_parameters),
        },
    }


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Build, optionally write, and validate the inventory."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the governance inventory")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="inventory JSON output path"
    )
    args = parser.parse_args()
    payload = build_inventory()
    rendered = _canonical_json(payload)
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    elif args.output.exists() and args.output.read_text(encoding="utf-8") != rendered:
        raise SystemExit(f"inventory is stale: {args.output}")
    print(json.dumps(payload["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
