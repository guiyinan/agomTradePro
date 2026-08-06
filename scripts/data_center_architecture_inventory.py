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
SOURCE_ROOTS = ("apps", "core", "shared")
ALLOWED_PROVIDER_ROOT = "apps/data_center/infrastructure/"
PROVIDER_SDK_MODULES = frozenset({"tushare", "akshare", "xtquant", "baostock"})
HTTP_MODULES = frozenset({"requests", "httpx", "aiohttp"})
LEGACY_FACT_PATTERNS = (
    "MacroIndicator",
    "FinancialDataModel",
    "ValuationModel",
    "StockDailyModel",
    "FundNavModel",
    "SectorMembershipModel",
    "NewsModel",
    "CapitalFlowModel",
)
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


def build_inventory() -> dict[str, object]:
    """Return a deterministic source inventory with no generated timestamp."""

    provider_imports: list[dict[str, object]] = []
    direct_data_center_imports: list[dict[str, object]] = []
    external_http_imports: list[dict[str, object]] = []
    cross_app_orm: list[dict[str, object]] = []
    legacy_fact_reads: list[dict[str, object]] = []
    current_surfaces: list[dict[str, object]] = []
    data_tasks: list[dict[str, object]] = []
    runtime_parameters: set[str] = set()

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
                external_http_imports.append(
                    {"path": relative, "line": lineno, "import": import_name}
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
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            for pattern in LEGACY_FACT_PATTERNS:
                if pattern in stripped and not stripped.startswith(("#", '"""', "'''")):
                    legacy_fact_reads.append({"path": relative, "line": lineno, "symbol": pattern})
            if SURFACE_PATTERN.search(stripped) and "#" not in stripped[:2]:
                current_surfaces.append({"path": relative, "line": lineno, "text": stripped})
            if CELERY_DECORATOR_PATTERN.search(stripped):
                data_tasks.append({"path": relative, "line": lineno, "text": stripped})
            match = RUNTIME_ENV_PATTERN.search(stripped)
            if match:
                runtime_parameters.add(stripped[:200])

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
