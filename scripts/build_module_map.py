#!/usr/bin/env python
"""Build a generated, machine-readable per-module architecture map.

The module map is a *projection* of the source tree: it is fully derived by
static AST scanning (stdlib ``ast`` only, no Django import, no database) and
must never be edited by hand.  Regenerate with::

    python scripts/build_module_map.py

Determinism contract: the output contains no timestamps and no git hashes,
all keys and lists are sorted, and the file is rendered with
``json.dumps(..., indent=2, sort_keys=True)`` plus a trailing newline, so
byte-identical regeneration is expected on an unchanged tree.

Field semantics (paths are module-relative, POSIX style):

- ``layers``: per-layer ``.py`` file counts.  First-level directories that
  contain Python files are counted under their own name (the standard four
  layers ``domain/application/infrastructure/interface`` plus ``management``,
  and any extras such as ``tests`` or ``templatetags``); top-level ``.py``
  files of the module are counted under ``"root"``.  ``migrations`` and
  ``__pycache__`` are excluded everywhere.
- ``entrypoints``: for files directly under ``application/`` (no subdirs,
  ``__init__.py`` skipped), the public top-level class and (async) function
  names, i.e. definitions whose name does not start with ``_``.
- ``orm_models``: for files named ``models.py`` or inside a ``models/``
  package under ``infrastructure/``, the module-level ``ClassDef`` names
  whose bases look like Django models.  Heuristic: a base qualifies when the
  final identifier of the (possibly dotted) base expression is exactly
  ``"Model"`` or ends with ``"Model"`` (covers ``models.Model``,
  ``TypedModel``, ``TimeStampedModel``), excluding abstract-looking base
  names listed in ``_NON_MODEL_BASE_NAMES`` (e.g. ``abc.ABC``).  Nested
  classes such as ``Meta`` are ignored because only module-level class
  definitions are considered.
- ``celery_tasks``: module-level or nested ``FunctionDef``/``AsyncFunctionDef``
  names whose decorator list contains ``@shared_task`` or any
  ``@<something>.task`` attribute decorator, in plain or call form
  (``@shared_task(...)``, ``@app.task(...)``).
- ``http_routes``: for files named ``urls.py`` or ``api_urls.py`` anywhere
  under the module, the first positional string literal of every
  ``path(...)`` / ``re_path(...)`` call.  Calls without a literal first
  argument (typical ``include(...)``-only registrations) are skipped.
- ``depends_on``: import statements of ``apps.<other>`` resolved with the
  same relative-import algorithm as
  ``scripts/data_center_architecture_inventory.py``.  ``target_layers`` is
  the sorted set of the imported path's layer segment (the third dotted
  component, e.g. ``apps.macro.infrastructure.models`` -> ``infrastructure``;
  bare ``apps.macro`` -> ``root``).  Self-imports are never listed.
- ``depended_by``: reverse index of ``depends_on`` (import counts only).

Empty collections are omitted per module, except ``layers`` which is always
emitted.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"
DEFAULT_OUTPUT = ROOT / "governance" / "module_map.json"
SCHEMA_VERSION = "1.0"
GENERATED_BY = "scripts/build_module_map.py"
PROJECTION_NOTICE = (
    "GENERATED PROJECTION of the source tree. "
    "Do not edit by hand; run: python scripts/build_module_map.py"
)
EXCLUDED_PARTS = frozenset({"__pycache__", "migrations"})
ROUTE_FILENAMES = frozenset({"urls.py", "api_urls.py"})
ROUTE_FUNCTIONS = frozenset({"path", "re_path"})
NON_MODEL_BASE_NAMES = frozenset({"ABC", "ABCMeta", "Protocol", "Generic", "TypedDict"})

ModuleRecord = dict[str, object]
ModuleMap = dict[str, ModuleRecord]


def _iter_module_dirs(apps_root: Path) -> list[Path]:
    """Return immediate subdirectories of ``apps/`` that contain Python files."""

    modules: list[Path] = []
    for candidate in sorted(apps_root.iterdir()):
        if not candidate.is_dir() or candidate.name == "__pycache__":
            continue
        if any(True for _ in _iter_python_files(candidate)):
            modules.append(candidate)
    return modules


def _iter_python_files(module_dir: Path) -> Iterable[Path]:
    """Yield deterministic Python files under a module, excluding caches."""

    yield from sorted(
        path
        for path in module_dir.rglob("*.py")
        if not EXCLUDED_PARTS.intersection(path.relative_to(module_dir).parts)
    )


def _module_relative(path: Path, module_dir: Path) -> str:
    return path.relative_to(module_dir).as_posix()


def _parse_tree(path: Path, relative: str) -> ast.Module | None:
    """Parse a Python file, returning ``None`` on syntax errors."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return ast.parse(text, filename=relative)
    except SyntaxError:
        return None


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


def _dotted_name(node: ast.AST) -> str | None:
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


def _layer_of_relative(relative: str) -> str:
    """Return the first path segment of a module-relative file path."""

    parts = Path(relative).parts
    if len(parts) == 1:
        return "root"
    return parts[0]


def _scan_layers(files: list[Path], module_dir: Path) -> dict[str, int]:
    """Count Python files per first-level directory (``root`` for top-level)."""

    layers: dict[str, int] = {}
    for path in files:
        layer = _layer_of_relative(_module_relative(path, module_dir))
        layers[layer] = layers.get(layer, 0) + 1
    return layers


def _scan_entrypoints(tree: ast.Module) -> list[str]:
    """Return public top-level class and function names of a module."""

    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


def _is_model_base(base: ast.AST) -> bool:
    """Heuristic: base expression looks like a Django model base class."""

    dotted = _dotted_name(base)
    if dotted is None:
        return False
    final = dotted.rsplit(".", 1)[-1]
    if final in NON_MODEL_BASE_NAMES:
        return False
    return final == "Model" or final.endswith("Model")


def _scan_orm_models(tree: ast.Module) -> list[str]:
    """Return module-level class names whose bases look like Django models."""

    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any(_is_model_base(base) for base in node.bases)
    ]


def _is_celery_task_decorator(decorator: ast.AST) -> bool:
    """Match ``@shared_task`` / ``@<something>.task`` in plain or call form."""

    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "shared_task"
    if isinstance(target, ast.Attribute):
        return target.attr == "task"
    return False


def _scan_celery_tasks(tree: ast.Module) -> list[str]:
    """Return names of functions decorated as Celery tasks."""

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _is_celery_task_decorator(decorator) for decorator in node.decorator_list
        ):
            names.append(node.name)
    return sorted(set(names))


def _scan_http_routes(tree: ast.Module) -> list[str]:
    """Return first positional string literals of ``path``/``re_path`` calls."""

    routes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        is_route_call = (isinstance(func, ast.Name) and func.id in ROUTE_FUNCTIONS) or (
            isinstance(func, ast.Attribute) and func.attr in ROUTE_FUNCTIONS
        )
        if not is_route_call:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            routes.append(first.value)
    return routes


def _iter_import_modules(tree: ast.Module, relative: str) -> Iterable[str]:
    """Yield resolved absolute dotted module names imported by a file."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield _resolved_import_from_module(node, relative)


def _split_app_import(import_name: str) -> tuple[str, str] | None:
    """Split ``apps.<module>[.<layer>...]`` into (module, layer), if applicable."""

    parts = import_name.split(".")
    if len(parts) < 2 or parts[0] != "apps" or not parts[1]:
        return None
    layer = parts[2] if len(parts) > 2 and parts[2] else "root"
    return parts[1], layer


def _iter_dependency_edges(
    tree: ast.Module,
    relative: str,
    module_name: str,
    known_modules: set[str],
) -> Iterable[tuple[str, str]]:
    """Yield (target module, target layer) per cross-module import statement."""

    for import_name in _iter_import_modules(tree, relative):
        split = _split_app_import(import_name)
        if split is not None:
            target_module, target_layer = split
            if target_module != module_name and target_module in known_modules:
                yield target_module, target_layer
    # ``from apps import macro`` style: aliases carry the module names.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "apps":
            for alias in node.names:
                if alias.name in known_modules and alias.name != module_name:
                    yield alias.name, "root"


def build_module_map() -> dict[str, object]:
    """Scan ``apps/`` and return the deterministic module map payload."""

    module_dirs = _iter_module_dirs(APPS_ROOT)
    known_modules = {path.name for path in module_dirs}
    modules: ModuleMap = {}
    import_counts: dict[str, dict[str, int]] = {}

    for module_dir in module_dirs:
        module_name = module_dir.name
        files = list(_iter_python_files(module_dir))
        record: ModuleRecord = {"layers": _scan_layers(files, module_dir)}
        entrypoints: dict[str, list[str]] = {}
        orm_models: dict[str, list[str]] = {}
        celery_tasks: dict[str, list[str]] = {}
        http_routes: dict[str, list[str]] = {}
        dep_imports: dict[str, int] = {}
        dep_layers: dict[str, set[str]] = {}

        for path in files:
            relative = _module_relative(path, module_dir)
            tree = _parse_tree(path, relative)
            if tree is None:
                continue
            layer = _layer_of_relative(relative)
            filename = path.name

            if layer == "application" and len(Path(relative).parts) == 2 and filename != "__init__.py":
                names = _scan_entrypoints(tree)
                if names:
                    entrypoints[relative] = names

            if layer == "infrastructure" and (
                filename == "models.py" or Path(relative).parts[1] == "models"
            ):
                models = _scan_orm_models(tree)
                if models:
                    orm_models[relative] = models

            tasks = _scan_celery_tasks(tree)
            if tasks:
                celery_tasks[relative] = tasks

            if filename in ROUTE_FILENAMES:
                routes = _scan_http_routes(tree)
                if routes:
                    http_routes[relative] = routes

            for target_module, target_layer in _iter_dependency_edges(
                tree, relative, module_name, known_modules
            ):
                dep_imports[target_module] = dep_imports.get(target_module, 0) + 1
                dep_layers.setdefault(target_module, set()).add(target_layer)

        if entrypoints:
            record["entrypoints"] = {key: sorted(value) for key, value in entrypoints.items()}
        if orm_models:
            record["orm_models"] = orm_models
        if celery_tasks:
            record["celery_tasks"] = celery_tasks
        if http_routes:
            record["http_routes"] = http_routes
        if dep_imports:
            record["depends_on"] = {
                target: {
                    "imports": dep_imports[target],
                    "target_layers": sorted(dep_layers.get(target, set())),
                }
                for target in dep_imports
            }
        modules[module_name] = record
        import_counts[module_name] = dep_imports

    depended_by: dict[str, dict[str, int]] = {}
    for source_module, targets in import_counts.items():
        for target_module, count in targets.items():
            reverse = depended_by.setdefault(target_module, {})
            reverse[source_module] = reverse.get(source_module, 0) + count
    for module_name, sources in depended_by.items():
        existing = modules.get(module_name)
        if existing is not None:
            existing["depended_by"] = {
                source: {"imports": count} for source, count in sources.items()
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "projection_notice": PROJECTION_NOTICE,
        "modules": modules,
    }


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _edge_count(payload: dict[str, object]) -> int:
    modules = payload.get("modules", {})
    if not isinstance(modules, dict):
        return 0
    count = 0
    for record in modules.values():
        if isinstance(record, dict):
            depends_on = record.get("depends_on", {})
            if isinstance(depends_on, dict):
                count += len(depends_on)
    return count


def main() -> int:
    """Build the module map, write it, and print a summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="module map JSON output path",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the rendered module map to stdout instead of writing a file",
    )
    args = parser.parse_args()

    payload = build_module_map()
    rendered = _canonical_json(payload)
    if args.stdout:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    modules = payload["modules"]
    module_count = len(modules) if isinstance(modules, dict) else 0
    print(f"module map OK: modules={module_count} edges={_edge_count(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
